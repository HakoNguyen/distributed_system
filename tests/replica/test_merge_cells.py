"""Một luật merge cho mọi kênh cập nhật snapshot (PT-10): giao hoán, lũy đẳng, không ghi đè ô mới hơn."""
from fixtures import cell, snapshot_rows

from common.db import pool
from services import replica

# Hai bản snapshot chồng lên nhau ở ô (2,1) và (2,2), mỗi bên mới hơn ở một ô
A = [cell(2, 1, 9, 40), cell(2, 2, 3, 70), cell(1, 1, 5, 10)]
B = [cell(2, 1, 7, 55), cell(2, 2, 6, 61), cell(3, 4, 2, 90)]


def merge(rows: list[dict], source: str = "gossip") -> int:
    with pool.connection() as conn, conn.transaction():
        return replica.merge_cells(conn, rows, source)


def state() -> dict:
    return {(r["branch_id"], r["product_id"]): (r["qty_on_hand"], r["last_movement"]) for r in snapshot_rows()}


def test_merge_is_commutative(db):
    """PT-10: merge A rồi B cho cùng kết quả với merge B rồi A; mỗi ô giữ bản có movement_id lớn hơn."""
    merge(A)
    merge(B)
    ab = state()
    with pool.connection() as conn:
        conn.execute("DELETE FROM inventory_snapshot")
    merge(B)
    merge(A)

    assert state() == ab
    assert ab == {(1, 1): (10, 5), (2, 1): (40, 9), (2, 2): (61, 6), (3, 4): (90, 2)}


def test_merge_is_idempotent(db):
    """PT-10, PT-04: merge hai lần như một lần; lần hai không vá ô nào."""
    assert merge(A) == 3
    first = state()

    assert merge(A) == 0
    assert state() == first


def test_merge_does_not_overwrite_newer_or_equal_cell(db):
    """PT-05, PT-10: bản cũ hơn hoặc cùng movement_id không ghi đè ô đang có."""
    merge([cell(2, 1, 9, 40)])

    assert merge([cell(2, 1, 5, 99)]) == 0
    assert merge([cell(2, 1, 9, 12)]) == 0
    assert state() == {(2, 1): (40, 9)}


def test_merge_counts_patched_cells_and_sets_source(db):
    """PT-10: trả đúng số ô được vá; chỉ ô được vá đổi source sang kênh vừa merge."""
    merge([cell(2, 1, 9, 40), cell(2, 2, 3, 70)], "kafka")

    n = merge([cell(2, 1, 10, 39), cell(2, 2, 1, 99), cell(2, 3, 4, 20)], "gossip")

    assert n == 2
    assert {(r["branch_id"], r["product_id"]): r["source"] for r in snapshot_rows()} == {
        (2, 1): "gossip", (2, 2): "kafka", (2, 3): "gossip"}
