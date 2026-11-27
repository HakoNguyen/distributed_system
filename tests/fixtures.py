"""Hàm dựng dữ liệu và đọc trạng thái dùng chung cho test."""
import os

import psycopg

from common.db import pool
from services.branch import seed_if_empty


def seed_branch() -> dict[int, int]:
    """Tạo tồn ban đầu như lần chạy đầu tiên của chi nhánh; trả {product_id: qty_on_hand}."""
    seed_if_empty()
    with pool.connection() as conn:
        rows = conn.execute("SELECT product_id, qty_on_hand FROM inventory").fetchall()
    return {r["product_id"]: r["qty_on_hand"] for r in rows}


def event(movement_id: int, qty_after: int, *, branch_id: int = 2, product_id: int = 1,
          move_type: str = "SALE", qty_delta: int = -1) -> dict:
    """Một sự kiện đúng định dạng relay gửi lên Redpanda (docs/api.md mục 3)."""
    return {"branch_id": branch_id, "movement_id": movement_id, "product_id": product_id,
            "move_type": move_type, "qty_delta": qty_delta, "qty_after": qty_after,
            "node_time": "2026-11-19T08:00:00+00:00"}


def cell(branch_id: int, product_id: int, last_movement: int, qty: int) -> dict:
    """Một ô snapshot đúng định dạng GET /api/snapshot của bản sao (docs/api.md mục 2)."""
    return {"branch_id": branch_id, "product_id": product_id, "qty_on_hand": qty,
            "last_movement": last_movement, "node_time": "2026-11-19T08:00:00+00:00"}


def snapshot_rows() -> list[dict]:
    with pool.connection() as conn:
        return conn.execute(
            """SELECT branch_id, product_id, qty_on_hand, last_movement, source
               FROM inventory_snapshot ORDER BY branch_id, product_id"""
        ).fetchall()


def sink_state(ok: bool | None, lost_ago_s: int | None = None, checked_ago_s: int = 0) -> None:
    """Đặt trạng thái đường đọc Redpanda như sink đã ghi, mốc tính lùi từ giờ CSDL."""
    with pool.connection() as conn:
        conn.execute(
            """UPDATE sink_stats SET broker_ok = %s,
                      broker_lost_at = now() - make_interval(secs => %s),
                      broker_checked_at = now() - make_interval(secs => %s)""",
            (ok, lost_ago_s, checked_ago_s),
        )


def node(branch_id: int, branch_url: str | None, seen_ago_s: int = 0) -> None:
    """Một chi nhánh đã gửi heartbeat cách đây seen_ago_s giây."""
    with pool.connection() as conn:
        conn.execute(
            """INSERT INTO node_status (branch_id, branch_name, last_seen, node_time, branch_url)
               VALUES (%s, %s, now() - make_interval(secs => %s), now(), %s)""",
            (branch_id, f"CN{branch_id}", seen_ago_s, branch_url),
        )


def one_peer(peer: str) -> dict | None:
    with pool.connection() as conn:
        return conn.execute("SELECT * FROM sync_peer WHERE peer = %s", (peer,)).fetchone()


def count(table: str) -> int:
    with pool.connection() as conn:
        return conn.execute(f"SELECT count(*) AS n FROM {table}").fetchone()["n"]


def snapshot_cell(branch_id: int, product_id: int) -> dict | None:
    with pool.connection() as conn:
        return conn.execute(
            "SELECT qty_on_hand, last_movement FROM inventory_snapshot"
            " WHERE branch_id = %s AND product_id = %s",
            (branch_id, product_id),
        ).fetchone()


def unsent_ids() -> list[int]:
    """event_id của các dòng outbox chưa gửi, theo thứ tự."""
    with pool.connection() as conn:
        rows = conn.execute("SELECT event_id FROM outbox WHERE sent_at IS NULL ORDER BY event_id").fetchall()
    return [r["event_id"] for r in rows]


def one_row(table: str) -> dict:
    """Dòng duy nhất của bảng một dòng (relay_status, sink_stats)."""
    with pool.connection() as conn:
        return conn.execute(f"SELECT * FROM {table}").fetchone()


def peer_view(peer: str, branch_id: int, state: str, received_ago_s: float = 0) -> None:
    """Góc nhìn của bản sao `peer` về chi nhánh, nhận cách đây received_ago_s giây (giờ CSDL)."""
    with pool.connection() as conn:
        conn.execute(
            """INSERT INTO peer_view (peer, branch_id, state, seconds_since_seen, received_at)
               VALUES (%s, %s, %s, 0, now() - make_interval(secs => %s))""",
            (peer, branch_id, state, received_ago_s),
        )


def peer_view_rows() -> list[dict]:
    with pool.connection() as conn:
        return conn.execute(
            "SELECT peer, branch_id, state, seconds_since_seen FROM peer_view ORDER BY peer, branch_id"
        ).fetchall()


# ---------------------------------------------------------------------------
# Ghi hộ (vòng 6, PT-14)
# ---------------------------------------------------------------------------
def set_qty(product_id: int, qty: int) -> None:
    """Đặt tồn chi nhánh của một mã hàng (sau seed_branch), không qua sổ cái: chỉ để dựng tình huống."""
    with pool.connection() as conn:
        conn.execute("UPDATE inventory SET qty_on_hand = %s WHERE product_id = %s", (qty, product_id))


def branch_qty(product_id: int) -> int:
    with pool.connection() as conn:
        return conn.execute("SELECT qty_on_hand FROM inventory WHERE product_id = %s", (product_id,)).fetchone()["qty_on_hand"]


def handoff_pull(node: str, items: list[tuple[int, str, int, int]], accepting: bool = False) -> dict:
    """Phản hồi GET /api/handoff của bản sao `node` (docs/api.md mục 2); items = (handoff_id, request_id, product_id, qty)."""
    return {"node": node, "branch_id": 1, "accepting": accepting,
            "counts": {"pending": len(items), "applied": 0, "rejected": 0},
            "pending": [{"handoff_id": h, "request_id": r, "product_id": p, "qty": q} for h, r, p, q in items],
            "stock": []}


def rejected_rows() -> list[dict]:
    with pool.connection() as conn:
        return conn.execute(
            "SELECT request_id, product_id, qty, reason, qty_on_hand FROM handoff_rejected ORDER BY rejected_at, request_id"
        ).fetchall()


def replica_cell(branch_id: int, product_id: int, qty: int, last_movement: int = 1) -> None:
    """Một ô snapshot ở bản sao, như sink đã áp."""
    with pool.connection() as conn:
        conn.execute(
            """INSERT INTO inventory_snapshot (branch_id, product_id, qty_on_hand, last_movement)
               VALUES (%s, %s, %s, %s)""",
            (branch_id, product_id, qty, last_movement),
        )


def handoff_rows() -> list[dict]:
    with pool.connection() as conn:
        return conn.execute(
            "SELECT handoff_id, branch_id, request_id, product_id, qty, status, movement_id, reason FROM handoff ORDER BY handoff_id"
        ).fetchall()


def committed_moves(request_ids: list[str]) -> list[tuple]:
    """(request_id, move_type, qty_delta) trong sổ cái nhìn từ MỘT KẾT NỐI KHÁC: chỉ thấy dữ liệu đã commit."""
    with psycopg.connect(os.environ["DATABASE_URL"]) as other:
        return other.execute(
            """SELECT request_id, move_type, qty_delta FROM stock_movement
               WHERE request_id = ANY(%s) ORDER BY movement_id""",
            (request_ids,),
        ).fetchall()
