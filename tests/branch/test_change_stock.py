"""Bán ở chi nhánh: các quy tắc đã có từ vòng 0."""
from fixtures import count, seed_branch

from common.db import pool


def test_sale_writes_inventory_ledger_and_outbox_together(branch_client):
    """PT-02: một lượt bán sửa tồn, thêm một dòng sổ cái và một dòng outbox mang đúng số tồn mới."""
    stock = seed_branch()
    movements, events = count("stock_movement"), count("outbox")

    r = branch_client.post("/api/sale", json={"product_id": 1, "qty": 2})

    assert r.status_code == 200
    assert r.json()["qty_on_hand"] == stock[1] - 2
    assert count("stock_movement") == movements + 1
    assert count("outbox") == events + 1
    with pool.connection() as conn:
        payload = conn.execute("SELECT payload FROM outbox ORDER BY event_id DESC LIMIT 1").fetchone()["payload"]
    assert payload["movement_id"] == r.json()["movement_id"]
    assert payload["qty_after"] == stock[1] - 2


def test_oversell_is_rejected_and_leaves_no_event(branch_client):
    """PT-09, PT-02: bán quá tồn trả 422, không đổi tồn, không có sự kiện nào lọt vào outbox."""
    stock = seed_branch()
    events = count("outbox")

    r = branch_client.post("/api/sale", json={"product_id": 1, "qty": stock[1] + 1})

    assert r.status_code == 422
    assert r.json()["detail"]["error"] == "insufficient_stock"
    assert count("outbox") == events
    assert seed_branch()[1] == stock[1]


def test_same_request_id_is_applied_once(branch_client):
    """PT-08: gửi lại cùng request_id thì trả kết quả cũ, chỉ trừ tồn một lần."""
    stock = seed_branch()
    body = {"product_id": 1, "qty": 3, "request_id": "pos-123"}

    first = branch_client.post("/api/sale", json=body).json()
    again = branch_client.post("/api/sale", json=body).json()

    assert again["replayed"] is True
    assert again["movement_id"] == first["movement_id"]
    assert seed_branch()[1] == stock[1] - 3
