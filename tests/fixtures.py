"""Hàm dựng dữ liệu và đọc trạng thái dùng chung cho test."""
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
