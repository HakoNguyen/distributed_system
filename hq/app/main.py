"""
api (bản sao trung tâm) — nhận heartbeat và phục vụ dashboard.

Mỗi máy chạy một bản sao như thế này, và nginx ở máy A chia yêu cầu cho chúng.
Người dùng chỉ biết một địa chỉ (nginx), không biết mình đang được bản sao nào
phục vụ. Mỗi phản hồi vẫn ghi rõ "served_by" để lúc demo nhìn thấy được.

api KHÔNG tự đọc Redpanda (đó là việc của sink, một tiến trình riêng), và KHÔNG
gọi thẳng CSDL của chi nhánh. Nó chỉ đọc CSDL của bản sao mình.
"""
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

from config import NODE_NAME, NODE_TIMEOUT_S
from db import open_pool, pool

STATIC = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    open_pool()
    yield
    pool.close()


app = FastAPI(title=f"replica {NODE_NAME}", lifespan=lifespan)


@app.middleware("http")
async def served_by_header(request: Request, call_next):
    """Gắn tên bản sao vào MỌI phản hồi. Thử: curl -I http://<IP máy A>/api/stats"""
    response = await call_next(request)
    response.headers["X-Served-By"] = f"replica-{NODE_NAME}"
    return response


@app.get("/", include_in_schema=False)
def dashboard():
    return FileResponse(STATIC / "dashboard.html")


@app.get("/health")
def health():
    with pool.connection() as conn:
        conn.execute("SELECT 1")
    return {"status": "ok", "node": NODE_NAME}


# ---------------------------------------------------------------------------
# Heartbeat từ các chi nhánh
# ---------------------------------------------------------------------------
class Heartbeat(BaseModel):
    branch_id: int
    branch_name: str
    node_time_ms: int
    outbox_backlog: int = 0
    rtt_ms: int | None = None


@app.post("/api/heartbeat")
def heartbeat(hb: Heartbeat):
    node_time = datetime.fromtimestamp(hb.node_time_ms / 1000, tz=timezone.utc)
    with pool.connection() as conn:
        conn.execute(
            """INSERT INTO node_status (branch_id, branch_name, last_seen, node_time,
                                        outbox_backlog, rtt_ms)
               VALUES (%s, %s, now(), %s, %s, %s)
               ON CONFLICT (branch_id) DO UPDATE
               SET branch_name = EXCLUDED.branch_name, last_seen = now(),
                   node_time = EXCLUDED.node_time, outbox_backlog = EXCLUDED.outbox_backlog,
                   rtt_ms = EXCLUDED.rtt_ms""",
            (hb.branch_id, hb.branch_name, node_time, hb.outbox_backlog, hb.rtt_ms),
        )
    return {"ok": True, "node": NODE_NAME}


# ---------------------------------------------------------------------------
# Các truy vấn cho dashboard
# ---------------------------------------------------------------------------
def query_nodes(conn):
    """Chi nhánh nào còn sống THEO BẢN SAO NÀY. Mỗi bản sao tự phán đoán theo
    heartbeat nó nhận được, nên lúc mạng bị chia cắt, hai bản sao có thể thấy khác nhau."""
    return conn.execute(
        """SELECT n.branch_id, n.branch_name, n.outbox_backlog, n.rtt_ms, n.last_seen,
                  n.last_seen > now() - make_interval(secs => %s)      AS alive,
                  round(extract(epoch FROM now() - n.last_seen))::int  AS seconds_since_seen,
                  -- giờ chi nhánh trừ giờ bản sao lúc nhận heartbeat.
                  -- Gồm cả lệch đồng hồ lẫn thời gian gói tin đi trên mạng.
                  round(extract(epoch FROM n.node_time - n.last_seen) * 1000)::int AS clock_offset_ms,
                  s.snapshot_updated_at, s.last_movement
           FROM node_status n
           LEFT JOIN (SELECT branch_id, max(updated_at) AS snapshot_updated_at,
                             max(last_movement) AS last_movement
                      FROM inventory_snapshot GROUP BY branch_id) s USING (branch_id)
           ORDER BY n.branch_id""",
        (NODE_TIMEOUT_S,),
    ).fetchall()


def query_inventory(conn):
    """Tồn toàn chuỗi. Người xem thấy MỘT bảng, không cần biết số đến từ máy nào."""
    rows = conn.execute(
        """SELECT p.product_id, p.name, p.unit, p.reorder_point,
                  s.branch_id, s.qty_on_hand, s.updated_at
           FROM product p
           LEFT JOIN inventory_snapshot s USING (product_id)
           ORDER BY p.product_id, s.branch_id"""
    ).fetchall()
    products: dict[int, dict] = {}
    for r in rows:
        p = products.setdefault(r["product_id"], {
            "product_id": r["product_id"], "name": r["name"], "unit": r["unit"],
            "reorder_point": r["reorder_point"], "total": 0, "by_branch": {},
        })
        if r["branch_id"] is not None:
            p["by_branch"][r["branch_id"]] = {
                "qty": r["qty_on_hand"],
                "below_reorder": r["qty_on_hand"] < r["reorder_point"],
                "updated_at": r["updated_at"],
            }
            p["total"] += r["qty_on_hand"]
    return list(products.values())


def query_events(conn, limit=30):
    return conn.execute(
        """SELECT e.*, p.name AS product_name,
                  -- trễ từ lúc chi nhánh ghi nhận tới lúc bản sao này nhận được
                  round(extract(epoch FROM e.received_at - e.node_time) * 1000)::int AS lag_ms
           FROM event_log e JOIN product p USING (product_id)
           WHERE e.move_type <> 'INIT'
           ORDER BY e.received_at DESC, e.movement_id DESC
           LIMIT %s""",
        (min(limit, 200),),
    ).fetchall()


def query_digest(conn):
    """Bản tóm tắt để SO SÁNH các bản sao với nhau.

    fingerprint = mã băm của toàn bộ bảng tổng hợp. Hai bản sao có cùng
    fingerprint nghĩa là chúng giữ ĐÚNG cùng một số liệu, đến từng ô.
    """
    d = conn.execute(
        """SELECT coalesce(sum(qty_on_hand), 0)::int AS total_qty,
                  count(*)::int AS rows,
                  md5(coalesce(string_agg(branch_id || ':' || product_id || ':' || qty_on_hand,
                                          ',' ORDER BY branch_id, product_id), '')) AS fingerprint
           FROM inventory_snapshot"""
    ).fetchone()
    d["last_movement_by_branch"] = {
        r["branch_id"]: r["m"] for r in conn.execute(
            "SELECT branch_id, max(last_movement) AS m FROM inventory_snapshot GROUP BY branch_id"
        ).fetchall()
    }
    d.update(conn.execute("SELECT processed, duplicates, last_event_at FROM sink_stats").fetchone())
    d["node"] = NODE_NAME
    d["fingerprint"] = d["fingerprint"][:8]  # 8 ký tự đầu là đủ để so bằng mắt
    return d


@app.get("/api/overview")
def overview():
    """Mọi thứ dashboard cần, lấy trong MỘT lần gọi, để mỗi lần làm mới chỉ do
    đúng một bản sao trả lời (không trộn số của hai bản sao)."""
    with pool.connection() as conn:
        return {
            "served_by": NODE_NAME,
            "nodes": query_nodes(conn),
            "inventory": query_inventory(conn),
            "events": query_events(conn),
            "digest": query_digest(conn),
        }


@app.get("/api/digest")
def digest():
    with pool.connection() as conn:
        return query_digest(conn)


# Giữ các endpoint rời để gọi bằng tay khi cần
@app.get("/api/nodes")
def nodes():
    with pool.connection() as conn:
        return query_nodes(conn)


@app.get("/api/inventory")
def inventory():
    with pool.connection() as conn:
        return query_inventory(conn)


@app.get("/api/events")
def events(limit: int = 30):
    with pool.connection() as conn:
        return query_events(conn, limit)


@app.get("/api/stats")
def stats():
    with pool.connection() as conn:
        return conn.execute("SELECT processed, duplicates, last_event_at FROM sink_stats").fetchone()
