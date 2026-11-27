"""Ghi hộ, phía bản sao (vòng 6, PT-14): nhận lượt bán khi đa số kết luận chi nhánh OFFLINE, kiểm tồn tạm tính, cho chi
nhánh kéo về và nhận báo kết quả. Bản sao không ghi vào CSDL chi nhánh (PT-07).

Trong test chỉ cấu hình một bản sao (NODE_NAME=T, REPLICA_URLS rỗng) nên kết luận đa số = góc nhìn của chính nó:
heartbeat cũ 20 giây là OFFLINE, 10 giây SUSPECT, 0 giây ONLINE.
"""
import time

import pytest
from fixtures import count, handoff_rows, node, replica_cell, snapshot_cell


def offline(branch_id: int = 2) -> None:
    node(branch_id, None, seen_ago_s=20)


def sale(client, request_id: str = "r1", qty: int = 2, product_id: int = 1, branch_id: int = 2):
    return client.post("/api/handoff", json={"branch_id": branch_id, "product_id": product_id,
                                             "qty": qty, "request_id": request_id})


def pull(client, branch_id: int = 2) -> dict:
    r = client.get(f"/api/handoff?branch_id={branch_id}")
    assert r.status_code == 200
    return r.json()


def ack(client, results: list[dict], branch_id: int = 2) -> dict:
    r = client.post("/api/handoff/ack", json={"branch_id": branch_id, "results": results})
    assert r.status_code == 200
    return r.json()


# ---------------------------------------------------------------------------
# Nhận ghi hộ
# ---------------------------------------------------------------------------
def test_handoff_accepted_when_majority_offline(replica_client):
    """PT-14, PT-13: kết luận OFFLINE thì nhận lượt ghi hộ, PENDING, trả tồn tạm tính; snapshot không đổi."""
    offline()
    replica_cell(2, 1, 10)

    r = sale(replica_client, qty=3)

    assert r.status_code == 200
    body = r.json()
    assert (body["node"], body["status"], body["qty_on_hand"], body["branch_id"]) == ("T", "PENDING", 7, 2)
    assert body["handoff_id"] > 0
    assert snapshot_cell(2, 1)["qty_on_hand"] == 10  # ghi hộ không đổi snapshot, dấu vân tay


def test_handoff_rejected_when_provisional_stock_insufficient(replica_client):
    """PT-14, PT-09: tồn tạm tính = snapshot trừ lượt PENDING; 5 - 3 = 2 thì xin 3 bị từ chối, không lưu."""
    offline()
    replica_cell(2, 1, 5)
    assert sale(replica_client, "r1", qty=3).status_code == 200

    r = sale(replica_client, "r2", qty=3)

    assert r.status_code == 422
    assert r.json()["detail"] == {"error": "insufficient_stock", "qty_on_hand": 2}
    assert count("handoff") == 1


@pytest.mark.parametrize("seen_ago_s", [0, 10])  # ONLINE, SUSPECT
def test_handoff_rejected_when_branch_not_offline(replica_client, seen_ago_s):
    """PT-13, PT-14: kết luận chưa phải OFFLINE (sống hoặc mới nghi ngờ) thì không ghi hộ."""
    node(2, None, seen_ago_s=seen_ago_s)
    replica_cell(2, 1, 10)

    r = sale(replica_client)

    assert r.status_code == 409
    assert r.json()["detail"] == {"error": "branch_not_offline"}
    assert count("handoff") == 0


def test_handoff_for_unknown_branch_is_not_offline(replica_client):
    """PT-13: chi nhánh chưa từng gửi heartbeat tới bản sao này thì không có kết luận OFFLINE: không ghi hộ."""
    replica_cell(2, 1, 10)

    assert sale(replica_client).status_code == 409


def test_handoff_without_snapshot_cell_is_404(replica_client):
    """PT-14: bản sao không có ô (chi nhánh, mã hàng) thì không tính được tồn tạm tính."""
    offline()

    r = sale(replica_client, product_id=999)

    assert r.status_code == 404
    assert r.json()["detail"] == {"error": "product_not_found"}


def test_same_request_id_stored_once(replica_client):
    """PT-08, PT-14: POS gửi lại cùng request_id (lỗi mạng) thì chỉ lưu một lần, trả lượt cũ kèm replayed."""
    offline()
    replica_cell(2, 1, 10)

    first = sale(replica_client, qty=2).json()
    again = sale(replica_client, qty=2).json()

    assert again["replayed"] is True
    assert again["handoff_id"] == first["handoff_id"]
    assert count("handoff") == 1
    assert {s["product_id"]: s["qty_on_hand"] for s in pull(replica_client)["stock"]} == {1: 8}


def test_request_id_is_required(replica_client):
    """PT-08: ghi hộ bắt buộc có request_id, không thì không chống trùng được."""
    offline()
    replica_cell(2, 1, 10)

    r = replica_client.post("/api/handoff", json={"branch_id": 2, "product_id": 1, "qty": 1})

    assert r.status_code == 422
    assert count("handoff") == 0


# ---------------------------------------------------------------------------
# Chi nhánh kéo về
# ---------------------------------------------------------------------------
def test_pull_lists_pending_in_order_with_accepting_counts_stock(replica_client):
    """PT-14, PT-07: GET /api/handoff trả lượt PENDING theo handoff_id, accepting, bộ đếm, tồn tạm tính; không ghi gì."""
    offline()
    replica_cell(2, 1, 10)
    replica_cell(2, 2, 4)
    replica_cell(3, 1, 9)
    sale(replica_client, "r1", qty=2, product_id=1)
    sale(replica_client, "r2", qty=1, product_id=2)
    before = handoff_rows()

    g = pull(replica_client)

    assert (g["node"], g["branch_id"], g["accepting"]) == ("T", 2, True)
    assert [i["request_id"] for i in g["pending"]] == ["r1", "r2"]
    assert g["pending"][0]["handoff_id"] < g["pending"][1]["handoff_id"]
    assert set(g["pending"][0]) == {"handoff_id", "request_id", "product_id", "qty"}
    assert g["counts"] == {"pending": 2, "applied": 0, "rejected": 0}
    stock = {s["product_id"]: s for s in g["stock"]}
    assert {p: s["qty_on_hand"] for p, s in stock.items()} == {1: 8, 2: 3}  # chỉ chi nhánh 2
    assert stock[1]["version"] is None and stock[1]["name"] and stock[1]["unit"] and "reorder_point" in stock[1]
    assert handoff_rows() == before


def test_not_accepting_once_branch_is_back(replica_client):
    """PT-14: chi nhánh đã gửi heartbeat lại (kết luận không còn OFFLINE) thì accepting = false, lượt PENDING vẫn còn."""
    offline()
    replica_cell(2, 1, 10)
    sale(replica_client)
    replica_client.post("/api/heartbeat", json={"branch_id": 2, "branch_name": "CN2",
                                               "node_time_ms": int(time.time() * 1000), "recovering": True})

    g = pull(replica_client)

    assert g["accepting"] is False
    assert len(g["pending"]) == 1


# ---------------------------------------------------------------------------
# Chi nhánh báo kết quả (sau khi đã commit)
# ---------------------------------------------------------------------------
def test_ack_marks_status_once(replica_client):
    """PT-14: ack đổi lượt PENDING thành APPLIED / REJECTED; ack lại (trùng hoặc khác) không đổi lượt đã chốt."""
    offline()
    replica_cell(2, 1, 10)
    h1 = sale(replica_client, "r1").json()["handoff_id"]
    h2 = sale(replica_client, "r2").json()["handoff_id"]

    first = ack(replica_client, [{"handoff_id": h1, "status": "APPLIED", "movement_id": 57},
                                 {"handoff_id": h2, "status": "REJECTED", "reason": "insufficient_stock"}])
    again = ack(replica_client, [{"handoff_id": h1, "status": "REJECTED", "reason": "insufficient_stock"}])

    assert (first["updated"], again["updated"]) == (2, 0)
    rows = {r["handoff_id"]: r for r in handoff_rows()}
    assert (rows[h1]["status"], rows[h1]["movement_id"]) == ("APPLIED", 57)
    assert (rows[h2]["status"], rows[h2]["reason"]) == ("REJECTED", "insufficient_stock")
    g = pull(replica_client)
    assert g["pending"] == []
    assert g["counts"] == {"pending": 0, "applied": 1, "rejected": 1}


def test_ack_for_other_branch_changes_nothing(replica_client):
    """PT-14: ack của chi nhánh 3 không đổi được lượt ghi hộ của chi nhánh 2."""
    offline()
    replica_cell(2, 1, 10)
    h1 = sale(replica_client).json()["handoff_id"]

    res = ack(replica_client, [{"handoff_id": h1, "status": "APPLIED", "movement_id": 1}], branch_id=3)

    assert res["updated"] == 0
    assert handoff_rows()[0]["status"] == "PENDING"


def test_applied_handoff_no_longer_reduces_provisional_stock(replica_client):
    """PT-14: lượt đã chốt không còn trừ vào tồn tạm tính (số tồn mới sẽ tới qua Redpanda như mọi lượt bán)."""
    offline()
    replica_cell(2, 1, 10)
    h1 = sale(replica_client, qty=4).json()["handoff_id"]
    ack(replica_client, [{"handoff_id": h1, "status": "REJECTED", "reason": "insufficient_stock"}])

    assert {s["product_id"]: s["qty_on_hand"] for s in pull(replica_client)["stock"]} == {1: 10}


# ---------------------------------------------------------------------------
# Cho dashboard
# ---------------------------------------------------------------------------
def test_heartbeat_recovering_shown_in_nodes(replica_client):
    """PT-13, PT-14: chi nhánh tự báo recovering qua heartbeat; nodes có recovering, kết luận đa số không đổi."""
    hb = {"branch_id": 2, "branch_name": "CN2", "node_time_ms": int(time.time() * 1000)}
    replica_client.post("/api/heartbeat", json={**hb, "branch_id": 1})
    replica_client.post("/api/heartbeat", json={**hb, "recovering": True})

    nodes = {n["branch_id"]: n for n in replica_client.get("/api/nodes").json()}

    assert (nodes[1]["recovering"], nodes[2]["recovering"]) == (False, True)
    assert nodes[2]["verdict"] == "ONLINE"


def test_digest_counts_handoffs_by_branch(replica_client):
    """PT-14: digest có số lượt ghi hộ theo chi nhánh, để dashboard cộng qua các bản sao."""
    offline()
    replica_cell(2, 1, 10)
    h1 = sale(replica_client, "r1").json()["handoff_id"]
    sale(replica_client, "r2")
    ack(replica_client, [{"handoff_id": h1, "status": "APPLIED", "movement_id": 9}])

    d = replica_client.get("/api/digest").json()

    assert d["handoff"] == {"2": {"pending": 1, "applied": 1, "rejected": 0}}
