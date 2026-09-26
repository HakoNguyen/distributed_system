"""
api_cn — dịch vụ của MỘT chi nhánh.

Nguyên tắc quan trọng nhất: dịch vụ này chỉ nói chuyện với CSDL của chính
chi nhánh mình (chạy trên cùng máy). Vì vậy khi mất mạng tới trung tâm,
quầy vẫn bán hàng bình thường. Việc báo lên trung tâm là việc của relay,
chạy riêng và không làm chậm việc bán.
"""
import random
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from psycopg.errors import UniqueViolation
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field

from config import BRANCH_ID, BRANCH_NAME, HEARTBEAT_EVERY_S, REPLICAS, STUCK_AFTER_S
from db import open_pool, pool

STATIC = Path(__file__).parent / "static"


# ---------------------------------------------------------------------------
# 1. Khởi tạo dữ liệu lần đầu
# ---------------------------------------------------------------------------
def seed_if_empty() -> None:
    """Lần chạy đầu tiên: tạo tồn kho ban đầu cho chi nhánh này.

    Mỗi dòng tồn ban đầu cũng được ghi thành một biến động loại INIT và
    đưa vào outbox. Nhờ vậy trung tâm nhận được số tồn ban đầu qua đúng
    con đường sự kiện như mọi lần bán sau này, không cần cơ chế riêng.
    """
    with pool.connection() as conn, conn.transaction():
        if conn.execute("SELECT 1 FROM inventory LIMIT 1").fetchone():
            return
        products = conn.execute("SELECT product_id FROM product ORDER BY product_id").fetchall()
        for p in products:
            pid = p["product_id"]
            # Số tồn giả lập, khác nhau giữa các chi nhánh nhưng cố định giữa các lần chạy
            qty = 40 + (pid * 37 * BRANCH_ID) % 120
            conn.execute(
                "INSERT INTO inventory (product_id, branch_id, qty_on_hand) VALUES (%s, %s, %s)",
                (pid, BRANCH_ID, qty),
            )
            record_movement(conn, pid, "INIT", qty, qty, None)
    print(f"[api cn{BRANCH_ID}] Đã tạo tồn kho ban đầu cho {len(products)} mã hàng")


def record_movement(conn, product_id, move_type, qty_delta, qty_after, request_id):
    """Ghi một dòng vào sổ cái stock_movement VÀ một dòng vào outbox.

    Hàm này luôn được gọi BÊN TRONG transaction của nghiệp vụ. Hoặc cả ba
    việc (sửa tồn, ghi sổ cái, ghi outbox) cùng thành công, hoặc không việc
    nào xảy ra. Đây là toàn bộ ý tưởng của outbox pattern.
    """
    m = conn.execute(
        """INSERT INTO stock_movement (product_id, move_type, qty_delta, qty_after, request_id)
           VALUES (%s, %s, %s, %s, %s)
           RETURNING movement_id, created_at""",
        (product_id, move_type, qty_delta, qty_after, request_id),
    ).fetchone()

    event = {
        "branch_id": BRANCH_ID,
        "movement_id": m["movement_id"],
        "product_id": product_id,
        "move_type": move_type,
        "qty_delta": qty_delta,
        "qty_after": qty_after,
        "node_time": m["created_at"].isoformat(),  # giờ theo đồng hồ chi nhánh
    }
    conn.execute(
        "INSERT INTO outbox (event_id, payload) VALUES (%s, %s)",
        (m["movement_id"], Jsonb(event)),
    )
    return m["movement_id"]


# ---------------------------------------------------------------------------
# 2. Nghiệp vụ: bán và nhập hàng
# ---------------------------------------------------------------------------
class StockChange(BaseModel):
    product_id: int
    qty: int = Field(gt=0, le=1000)
    # Không bắt buộc. Nếu gửi kèm, server chỉ sửa khi version vẫn khớp
    # (khoá lạc quan); lệch thì trả 409 để client đọc lại.
    version: int | None = None
    # Không bắt buộc. Client tự sinh (vd. uuid). Gửi lại cùng request_id thì
    # server trả kết quả cũ chứ không trừ tồn lần hai.
    request_id: str | None = None


def change_stock(product_id: int, delta: int, move_type: str,
                 expected_version: int | None, request_id: str | None) -> dict:
    try:
        return _change_stock(product_id, delta, move_type, expected_version, request_id)
    except UniqueViolation:
        # Hai yêu cầu cùng request_id tới gần như cùng lúc: yêu cầu sau
        # đụng ràng buộc UNIQUE. Trả kết quả của yêu cầu trước.
        with pool.connection() as conn:
            return _replayed_result(conn, request_id)


def _replayed_result(conn, request_id):
    m = conn.execute(
        "SELECT movement_id, product_id, qty_after FROM stock_movement WHERE request_id = %s",
        (request_id,),
    ).fetchone()
    return {"movement_id": m["movement_id"], "product_id": m["product_id"],
            "qty_on_hand": m["qty_after"], "replayed": True}


def _change_stock(product_id, delta, move_type, expected_version, request_id):
    with pool.connection() as conn, conn.transaction():
        # (a) Yêu cầu này đã xử lý rồi? Thì trả lại kết quả cũ.
        if request_id and conn.execute(
            "SELECT 1 FROM stock_movement WHERE request_id = %s", (request_id,)
        ).fetchone():
            return _replayed_result(conn, request_id)

        # (b) Sửa tồn bằng MỘT câu UPDATE có điều kiện.
        #     Postgres khoá dòng trong lúc sửa, nên hai quầy cùng bán một mã
        #     hàng sẽ xếp hàng lần lượt, không bao giờ bán lố tồn.
        sql = """UPDATE inventory
                 SET qty_on_hand = qty_on_hand + %(delta)s,
                     version = version + 1,
                     updated_at = now()
                 WHERE product_id = %(pid)s
                   AND qty_on_hand + %(delta)s >= 0"""
        if expected_version is not None:
            sql += " AND version = %(ver)s"
        row = conn.execute(
            sql + " RETURNING qty_on_hand, version",
            {"delta": delta, "pid": product_id, "ver": expected_version},
        ).fetchone()

        # (c) Không dòng nào được sửa: tìm lý do để trả mã lỗi đúng.
        if row is None:
            cur = conn.execute(
                "SELECT qty_on_hand, version FROM inventory WHERE product_id = %s", (product_id,)
            ).fetchone()
            if cur is None:
                raise HTTPException(404, {"error": "product_not_found"})
            if expected_version is not None and cur["version"] != expected_version:
                raise HTTPException(409, {"error": "version_conflict",
                                          "current_version": cur["version"]})
            raise HTTPException(422, {"error": "insufficient_stock",
                                      "qty_on_hand": cur["qty_on_hand"]})

        # (d) Ghi sổ cái + outbox trong CÙNG transaction.
        movement_id = record_movement(conn, product_id, move_type, delta,
                                      row["qty_on_hand"], request_id)

    return {"movement_id": movement_id, "product_id": product_id,
            "qty_on_hand": row["qty_on_hand"], "version": row["version"]}


# ---------------------------------------------------------------------------
# 3. Heartbeat: "tôi còn sống" gửi tới MỌI bản sao trung tâm, mỗi 5 giây
# ---------------------------------------------------------------------------
# Trạng thái đường nối tới từng bản sao, hiện lên màn hình POS.
links = {name: {"name": name, "url": url, "ok": False, "rtt_ms": None,
                "last_ok": None, "error": "chưa gửi heartbeat nào"}
         for name, url in REPLICAS}


def outbox_backlog(conn) -> dict:
    return conn.execute(
        """SELECT count(*) AS n,
                  extract(epoch FROM now() - min(created_at)) AS oldest_s
           FROM outbox WHERE sent_at IS NULL"""
    ).fetchone()


def heartbeat_loop(name: str, url: str) -> None:
    """Mỗi bản sao một luồng riêng, để một bản sao mất mạng không làm chậm các bản khác."""
    # Dùng lại một client: tạo client mới mỗi lần tốn vài chục ms, làm sai số đo RTT.
    client = httpx.Client(timeout=2.0)
    link = links[name]
    while True:
        try:
            with pool.connection() as conn:
                backlog = outbox_backlog(conn)["n"]
            t0 = time.perf_counter()
            client.post(
                f"{url}/api/heartbeat",
                json={
                    "branch_id": BRANCH_ID,
                    "branch_name": BRANCH_NAME,
                    "node_time_ms": int(time.time() * 1000),  # giờ máy chi nhánh
                    "outbox_backlog": backlog,
                    # RTT đo được ở lần trước, gửi kèm để trung tâm hiển thị
                    "rtt_ms": link["rtt_ms"],
                },
            ).raise_for_status()
            # RTT = thời gian một vòng đi và về của heartbeat. Bật Clumsy / tc
            # để thêm độ trễ là con số này tăng theo ngay.
            link.update(ok=True, last_ok=time.time(), error=None,
                        rtt_ms=round((time.perf_counter() - t0) * 1000))
        except Exception as e:  # mất mạng, bản sao tắt... chỉ ghi nhận rồi thử lại
            link.update(ok=False, error=type(e).__name__)
        time.sleep(HEARTBEAT_EVERY_S)


# ---------------------------------------------------------------------------
# 4. Ứng dụng FastAPI
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    open_pool()
    seed_if_empty()
    for name, url in REPLICAS:
        threading.Thread(target=heartbeat_loop, args=(name, url), daemon=True).start()
    yield
    pool.close()


app = FastAPI(title=f"api_cn{BRANCH_ID}", lifespan=lifespan)


@app.get("/", include_in_schema=False)
def pos_page():
    return FileResponse(STATIC / "pos.html")


@app.get("/health")
def health():
    with pool.connection() as conn:
        conn.execute("SELECT 1")
    return {"status": "ok", "branch_id": BRANCH_ID}


@app.get("/api/info")
def info():
    return {"branch_id": BRANCH_ID, "branch_name": BRANCH_NAME,
            "replicas": [name for name, _ in REPLICAS]}


@app.get("/api/inventory")
def inventory():
    with pool.connection() as conn:
        return conn.execute(
            """SELECT i.product_id, p.name, p.unit, p.reorder_point,
                      i.qty_on_hand, i.version, i.updated_at
               FROM inventory i JOIN product p USING (product_id)
               ORDER BY i.product_id"""
        ).fetchall()


@app.get("/api/status")
def status():
    """Trạng thái cho màn hình POS: outbox còn bao nhiêu, đường nối tới từng bản sao ra sao."""
    with pool.connection() as conn:
        b = outbox_backlog(conn)
    oldest = float(b["oldest_s"]) if b["oldest_s"] is not None else 0.0
    return {
        "branch_id": BRANCH_ID,
        "outbox_backlog": b["n"],
        "oldest_unsent_s": round(oldest, 1),
        # Sự kiện cũ nhất đã nằm chờ quá lâu -> relay đang không gửi được
        "sync_stuck": b["n"] > 0 and oldest >= STUCK_AFTER_S,
        "links": [
            {"name": l["name"], "ok": l["ok"], "rtt_ms": l["rtt_ms"],
             "seconds_since_ok": None if l["last_ok"] is None
             else round(time.time() - l["last_ok"], 1)}
            for l in links.values()
        ],
    }


def timed(fn, *args):
    """Chạy nghiệp vụ và ghi lại thời gian xử lý, để POS cho thấy bán tại chỗ nhanh cỡ nào."""
    t0 = time.perf_counter()
    result = fn(*args)
    result["elapsed_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    return result


@app.post("/api/sale")
def sale(req: StockChange):
    return timed(change_stock, req.product_id, -req.qty, "SALE", req.version, req.request_id)


@app.post("/api/receipt")
def receipt(req: StockChange):
    return timed(change_stock, req.product_id, +req.qty, "RECEIPT", req.version, req.request_id)


@app.post("/api/sale/random")
def random_sales(count: int = 20):
    """Bán nhanh `count` đơn ngẫu nhiên, mỗi đơn 1–3 đơn vị. Dùng khi demo."""
    with pool.connection() as conn:
        pids = [r["product_id"] for r in conn.execute("SELECT product_id FROM inventory").fetchall()]
    done, skipped = 0, 0
    for _ in range(count):
        try:
            change_stock(random.choice(pids), -random.randint(1, 3), "SALE", None, None)
            done += 1
        except HTTPException:  # hết hàng mã đó thì bỏ qua
            skipped += 1
    return {"sold": done, "skipped_out_of_stock": skipped}
