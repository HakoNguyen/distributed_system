"""
Nghiệp vụ của MỘT bản sao trung tâm: áp sự kiện, ghi heartbeat, truy vấn dashboard.

Bản sao KHÔNG giữ bản chính của tồn kho và KHÔNG gọi thẳng CSDL của chi nhánh.
Nó chỉ đọc/ghi CSDL của chính mình: bảng tổng hợp dựng lại từ sự kiện.
"""
from datetime import datetime, timezone

from common.config import NODE_NAME, NODE_TIMEOUT_S
from common.db import pool
from common.models import Heartbeat


# ---------------------------------------------------------------------------
# 1. Áp sự kiện (sink gọi)
# ---------------------------------------------------------------------------
def apply_event(e: dict, partition: int | None = None, offset: int | None = None) -> str:
    """Áp một sự kiện vào CSDL trung tâm. Trả 'new' hoặc 'duplicate'.

    Chịu được hai chuyện chắc chắn xảy ra trong hệ phân tán:
      1. NHẬN TRÙNG: khoá chính (branch_id, movement_id) của event_log.
      2. NHẬN LỆCH THỨ TỰ: chỉ ghi đè snapshot khi movement_id MỚI HƠN.
    Nhờ vậy phát lại toàn bộ sự kiện từ đầu cũng không làm sai số liệu.
    """
    with pool.connection() as conn, conn.transaction():
        inserted = conn.execute(
            """INSERT INTO event_log (branch_id, movement_id, product_id, move_type,
                                      qty_delta, qty_after, node_time,
                                      kafka_partition, kafka_offset)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (branch_id, movement_id) DO NOTHING""",
            (e["branch_id"], e["movement_id"], e["product_id"], e["move_type"],
             e["qty_delta"], e["qty_after"], e["node_time"], partition, offset),
        ).rowcount

        if inserted == 0:  # lớp chống trùng thứ nhất
            conn.execute("UPDATE sink_stats SET duplicates = duplicates + 1")
            return "duplicate"

        # Lớp thứ hai: chỉ ghi đè khi sự kiện này MỚI HƠN cái đang có.
        # So sánh bằng movement_id chứ KHÔNG bằng node_time: đồng hồ các máy
        # lệch nhau nên không tin được, còn movement_id do chính chi nhánh tăng dần.
        conn.execute(
            """INSERT INTO inventory_snapshot (branch_id, product_id, qty_on_hand,
                                               last_movement, node_time, updated_at)
               VALUES (%s, %s, %s, %s, %s, now())
               ON CONFLICT (branch_id, product_id) DO UPDATE
               SET qty_on_hand   = EXCLUDED.qty_on_hand,
                   last_movement = EXCLUDED.last_movement,
                   node_time     = EXCLUDED.node_time,
                   updated_at    = now()
               WHERE inventory_snapshot.last_movement < EXCLUDED.last_movement""",
            (e["branch_id"], e["product_id"], e["qty_after"], e["movement_id"], e["node_time"]),
        )
        conn.execute("UPDATE sink_stats SET processed = processed + 1, last_event_at = now()")
        return "new"


# ---------------------------------------------------------------------------
# 2. Heartbeat từ các chi nhánh
# ---------------------------------------------------------------------------
def record_heartbeat(hb: Heartbeat) -> None:
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


# ---------------------------------------------------------------------------
# 3. Truy vấn cho dashboard. Mọi hàm nhận `conn` để /api/overview gom vào một kết nối.
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
    d.update(query_stats(conn))
    d["node"] = NODE_NAME
    d["fingerprint"] = d["fingerprint"][:8]  # 8 ký tự đầu là đủ để so bằng mắt
    return d


def query_stats(conn):
    return conn.execute(
        """SELECT processed, duplicates, last_event_at,
                  broker_ok, broker_lost_at, lag, broker_checked_at
           FROM sink_stats"""
    ).fetchone()


# ---------------------------------------------------------------------------
# 4. Trạng thái đường đọc Redpanda (sink gọi mỗi 5 giây, SAU khi đã hỏi Redpanda xong)
# ---------------------------------------------------------------------------
def record_broker_check(ok: bool, lag: int | None) -> None:
    """ok=False: giữ mốc mất broker đầu tiên của đợt này và giữ lag cũ.
    ok=True: xoá mốc mất, ghi lag mới. Dashboard dựa vào đây để báo "Đồng bộ dừng từ HH:MM:SS"."""
    with pool.connection() as conn:
        conn.execute(
            """UPDATE sink_stats
               SET broker_ok = %(ok)s,
                   broker_checked_at = now(),
                   broker_lost_at = CASE WHEN %(ok)s THEN NULL ELSE coalesce(broker_lost_at, now()) END,
                   lag = coalesce(%(lag)s::bigint, lag)""",
            {"ok": ok, "lag": lag},
        )
