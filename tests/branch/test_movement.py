"""Chi nhánh cho dashboard đọc một dòng sổ cái kèm lúc relay gửi xong, để truy vết (vòng 4). Chỉ đọc."""
from fixtures import count, seed_branch

from services import branch


def sell(client, product_id: int = 1, qty: int = 2) -> int:
    r = client.post("/api/sale", json={"product_id": product_id, "qty": qty})
    assert r.status_code == 200
    return r.json()["movement_id"]


def test_movement_shows_ledger_row_not_yet_sent(branch_client):
    """PT-03: biến động chưa được relay gửi thì sent_at là null; các trường khớp sổ cái."""
    seed_branch()
    mid = sell(branch_client)

    r = branch_client.get(f"/api/movement/{mid}")

    assert r.status_code == 200
    m = r.json()
    assert (m["branch_id"], m["movement_id"], m["product_id"]) == (1, mid, 1)
    assert (m["move_type"], m["qty_delta"]) == ("SALE", -2)
    assert m["qty_after"] is not None
    assert m["node_time"] is not None
    assert m["sent_at"] is None


def test_movement_sent_at_set_after_relay_confirms(branch_client):
    """PT-03: relay gửi xong cả lô thì sent_at có giá trị."""
    seed_branch()
    mid = sell(branch_client)
    branch.relay_batch(lambda batch: None)

    assert branch_client.get(f"/api/movement/{mid}").json()["sent_at"] is not None


def test_unknown_movement_is_404(branch_client):
    """PT-07: không có biến động thì trả 404 movement_not_found, không bịa dữ liệu."""
    seed_branch()

    r = branch_client.get("/api/movement/999999")

    assert r.status_code == 404
    assert r.json()["detail"]["error"] == "movement_not_found"


def test_movement_writes_nothing(branch_client):
    """PT-07: đọc biến động qua API không ghi gì vào CSDL chi nhánh."""
    seed_branch()
    mid = sell(branch_client)
    before = (count("stock_movement"), count("outbox"))

    assert branch_client.get(f"/api/movement/{mid}").status_code == 200
    assert (count("stock_movement"), count("outbox")) == before
