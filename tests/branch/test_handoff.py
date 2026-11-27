"""Ghi hộ, phía chi nhánh (vòng 6, PT-14): tự kéo ghi hộ từ các bản sao, áp đúng một lần, theo thứ tự, trước lượt bán
mới; lượt không áp được thành REJECTED và được ghi lại.

Phần gọi bản sao thay bằng hàm `pull`, `ack` giả (như `send` của relay), nên test không gọi mạng.
"""
import time

import psycopg
import pytest
from fixtures import branch_qty, committed_moves, count, handoff_pull, rejected_rows, seed_branch, set_qty, unsent_ids

from services import branch


def collect(pulls: dict) -> list[dict]:
    return branch.collect_handoffs(pulls)


def apply(pulls: dict) -> list[dict]:
    results, error = branch.apply_handoffs(collect(pulls))
    assert error is None
    return results


# ---------------------------------------------------------------------------
# Áp đúng một lần
# ---------------------------------------------------------------------------
def test_apply_twice_deducts_once(db):
    """PT-14, PT-08: áp cùng lượt ghi hộ hai lần (ack bị mất, kéo lại) thì chỉ trừ tồn một lần."""
    stock = seed_branch()
    pulls = {"A": handoff_pull("A", [(1, "r1", 1, 2)])}

    first = apply(pulls)
    again = apply(pulls)

    assert first[0]["status"] == again[0]["status"] == "APPLIED"
    assert first[0]["movement_id"] == again[0]["movement_id"]
    assert branch_qty(1) == stock[1] - 2
    assert count("stock_movement") == len(stock) + 1


def test_applied_handoff_goes_out_like_a_sale(db):
    """PT-14, PT-02: lượt áp được đi qua đúng đường bán hàng: tồn, sổ cái, outbox cùng một transaction."""
    stock = seed_branch()
    before = unsent_ids()

    res = apply({"A": handoff_pull("A", [(1, "r1", 1, 2)])})

    assert unsent_ids() == before + [res[0]["movement_id"]]
    assert committed_moves(["r1"]) == [("r1", "SALE", -2)]
    assert branch_qty(1) == stock[1] - 2


# ---------------------------------------------------------------------------
# Thứ tự áp: thứ tự bản sao trong REPLICA_URLS, rồi handoff_id (không dùng đồng hồ)
# ---------------------------------------------------------------------------
def test_apply_follows_handoff_order_within_replica(db):
    """PT-14: tồn 5, lượt #1 xin 4, lượt #2 xin 3: #1 áp được, #2 bị từ chối."""
    seed_branch()
    set_qty(1, 5)

    res = apply({"A": handoff_pull("A", [(1, "r1", 1, 4), (2, "r2", 1, 3)])})

    assert [(r["request_id"], r["status"]) for r in res] == [("r1", "APPLIED"), ("r2", "REJECTED")]


def test_handoff_id_not_list_position_decides_order(db):
    """PT-14: bản sao trả lượt không theo thứ tự thì chi nhánh vẫn áp theo handoff_id."""
    seed_branch()
    set_qty(1, 5)

    res = apply({"A": handoff_pull("A", [(2, "r2", 1, 3), (1, "r1", 1, 4)])})

    assert [(r["request_id"], r["status"]) for r in res] == [("r1", "APPLIED"), ("r2", "REJECTED")]


def test_replicas_applied_in_configured_order(db):
    """PT-14: lượt ở bản sao đứng trước trong REPLICA_URLS (thứ tự của `pulls`) áp trước, không theo tên hay giờ."""
    seed_branch()
    set_qty(1, 5)

    res = apply({"B": handoff_pull("B", [(1, "rb", 1, 4)]), "A": handoff_pull("A", [(1, "ra", 1, 3)])})

    assert [(r["request_id"], r["status"]) for r in res] == [("rb", "APPLIED"), ("ra", "REJECTED")]


# ---------------------------------------------------------------------------
# Lượt vượt tồn thật: REJECTED, ghi lại, không mất lặng lẽ
# ---------------------------------------------------------------------------
def test_real_oversell_becomes_rejected_and_is_recorded(db):
    """PT-14, PT-09: tồn thật 2, ghi hộ 5: REJECTED, ghi handoff_rejected; tồn, sổ cái, outbox không đổi."""
    stock = seed_branch()
    set_qty(1, 2)
    before = unsent_ids()

    res = apply({"A": handoff_pull("A", [(1, "r1", 1, 5)])})

    assert (res[0]["status"], res[0]["reason"], res[0]["movement_id"]) == ("REJECTED", "insufficient_stock", None)
    assert branch_qty(1) == 2
    assert count("stock_movement") == len(stock)
    assert unsent_ids() == before
    assert rejected_rows() == [{"request_id": "r1", "product_id": 1, "qty": 5,
                                "reason": "insufficient_stock", "qty_on_hand": 2}]


def test_rejected_decision_is_final_even_after_restock(db):
    """PT-14: kéo lại lượt đã từ chối (ack bị mất) sau khi nhập thêm hàng thì vẫn REJECTED, không trừ."""
    seed_branch()
    set_qty(1, 2)
    pulls = {"A": handoff_pull("A", [(1, "r1", 1, 5)])}
    apply(pulls)
    branch.change_stock(1, +10, "RECEIPT", None, None)

    again = apply(pulls)

    assert again[0]["status"] == "REJECTED"
    assert branch_qty(1) == 12
    assert len(rejected_rows()) == 1


def test_unknown_product_is_rejected(db):
    """PT-14: mã hàng chi nhánh không có thì REJECTED product_not_found, không ném lỗi."""
    seed_branch()

    res = apply({"A": handoff_pull("A", [(1, "r1", 999, 1)])})

    assert (res[0]["status"], res[0]["reason"]) == ("REJECTED", "product_not_found")
    assert rejected_rows()[0]["reason"] == "product_not_found"


# ---------------------------------------------------------------------------
# Gom từ nhiều bản sao: không trùng, không sót
# ---------------------------------------------------------------------------
def test_collect_from_many_replicas_no_duplicate_no_loss(db):
    """PT-14: cùng request_id ở A và B (POS chuyển bản sao giữa chừng) gộp thành một lượt, nhớ cả hai nơi giữ;
    bản sao không gọi được (None) bị bỏ qua; mọi lượt còn lại đều có."""
    pulls = {"A": handoff_pull("A", [(1, "r1", 1, 1), (2, "dup", 2, 1)]),
             "B": handoff_pull("B", [(7, "dup", 2, 1), (8, "r3", 3, 1)]),
             "C": None}

    items = collect(pulls)

    assert [i["request_id"] for i in items] == ["r1", "dup", "r3"]
    assert [tuple(h) for h in items[1]["holders"]] == [("A", 2), ("B", 7)]
    assert [tuple(h) for h in items[2]["holders"]] == [("B", 8)]


# ---------------------------------------------------------------------------
# Một vòng phục hồi: ack chỉ sau commit, tới mọi nơi giữ lượt
# ---------------------------------------------------------------------------
def test_ack_only_after_commit_and_to_every_holder(db):
    """PT-14: lúc báo bản sao, kết nối khác đã thấy các lượt trong sổ cái (đã commit); lượt trùng báo cả A và B."""
    seed_branch()
    pulls = {"A": handoff_pull("A", [(1, "r1", 1, 1), (2, "dup", 2, 1)]),
             "B": handoff_pull("B", [(7, "dup", 2, 1)])}
    acks, committed = {}, []

    def ack(name, payload):
        committed.append(len(committed_moves(["r1", "dup"])))  # kết nối khác: chỉ thấy dữ liệu đã commit
        acks[name] = payload

    branch.recovery_once(lambda name: pulls[name], ack, ["A", "B"])

    assert committed == [2, 2]
    assert acks["A"]["branch_id"] == acks["B"]["branch_id"] == 1
    assert [(r["handoff_id"], r["status"]) for r in acks["A"]["results"]] == [(1, "APPLIED"), (2, "APPLIED")]
    assert [(r["handoff_id"], r["status"]) for r in acks["B"]["results"]] == [(7, "APPLIED")]
    assert acks["B"]["results"][0]["movement_id"] == acks["A"]["results"][1]["movement_id"]


def test_unexpected_error_stops_and_acks_only_done(db, monkeypatch):
    """PT-14: lỗi bất ngờ (mất CSDL) ở lượt 2 thì dừng: lượt 3 không được áp (giữ thứ tự), chỉ báo lượt 1."""
    seed_branch()
    real, calls = branch.change_stock, []

    def flaky(*args):
        calls.append(args)
        if len(calls) == 2:
            raise psycopg.OperationalError("mất CSDL")
        return real(*args)

    monkeypatch.setattr(branch, "change_stock", flaky)
    pulls = {"A": handoff_pull("A", [(1, "r1", 1, 1), (2, "r2", 2, 1), (3, "r3", 3, 1)])}
    acks = {}

    branch.recovery_once(lambda name: pulls[name], lambda name, p: acks.__setitem__(name, p), ["A"])

    assert [r["handoff_id"] for r in acks["A"]["results"]] == [1]
    assert len(calls) == 2
    assert branch.recovery["state"] == "RECOVERING"
    assert "mất CSDL" in branch.recovery["last_error"]


def test_invalid_data_from_replica_is_not_applied(db):
    """PT-14: dữ liệu hỏng từ bản sao (qty 0) thì coi như không gọi được bản sao đó, không áp gì."""
    stock = seed_branch()
    pulls = {"A": handoff_pull("A", [(1, "r1", 1, 0)])}

    branch.recovery_once(lambda name: pulls[name], lambda name, p: None, ["A"])

    assert count("stock_movement") == len(stock)
    assert branch.recovery["unreachable"] == ["A"]


# ---------------------------------------------------------------------------
# Luồng phục hồi không chết vì một lần lỗi
# ---------------------------------------------------------------------------
def test_recovery_once_survives_any_error_and_records_last_run(db, monkeypatch):
    """PT-14: lỗi bất kỳ trong một lần chạy bị bắt và ghi lại; lần chạy sau vẫn làm việc bình thường."""
    seed_branch()

    def boom(pulls):
        raise RuntimeError("lỗi bất ngờ")

    monkeypatch.setattr(branch, "collect_handoffs", boom)
    branch.recovery["checked_at"] = time.monotonic() - 100
    branch.recovery_once(lambda name: handoff_pull(name, []), lambda name, p: None, ["A"])  # không ném lỗi

    assert "lỗi bất ngờ" in branch.recovery["last_error"]
    assert branch.recovery["last_run_at"] is not None
    assert time.monotonic() - branch.recovery["checked_at"] < 5

    monkeypatch.undo()
    branch.recovery_once(lambda name: handoff_pull(name, []), lambda name, p: None, ["A"])
    assert branch.recovery["last_error"] is None
    assert branch.recovery["state"] == "ONLINE"


def test_ack_failure_for_one_replica_does_not_block_others(db):
    """PT-14: báo bản sao A lỗi (mất mạng) thì vẫn báo bản sao B; lượt của A còn PENDING, lần sau báo lại."""
    seed_branch()
    pulls = {"A": handoff_pull("A", [(1, "ra", 1, 1)]), "B": handoff_pull("B", [(1, "rb", 2, 1)])}
    acked = []

    def ack(name, payload):
        if name == "A":
            raise ConnectionError("A mất mạng")
        acked.append(name)

    branch.recovery_once(lambda name: pulls[name], ack, ["A", "B"])

    assert acked == ["B"]
    assert "A mất mạng" in branch.recovery["last_error"]


# ---------------------------------------------------------------------------
# RECOVERING: chặn lượt bán mới bằng mã lỗi rõ ràng
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("path, body", [
    ("/api/sale", {"product_id": 1, "qty": 1}),
    ("/api/receipt", {"product_id": 1, "qty": 1}),
    ("/api/sale/random?count=3", None),
])
def test_sale_rejected_while_recovering(branch_client, path, body):
    """PT-14: đang RECOVERING thì bán, nhập trả 503 branch_recovering và không ghi gì."""
    stock = seed_branch()
    branch.recovery["state"] = "RECOVERING"

    r = branch_client.post(path, json=body)

    assert r.status_code == 503
    assert r.json()["detail"] == {"error": "branch_recovering", "stale": False}
    assert count("stock_movement") == len(stock)


def test_sale_rejected_when_recovery_loop_is_stale(branch_client):
    """PT-14: luồng phục hồi không chạy trong 10 giây gần nhất (vừa unpause) thì chưa nhận bán, stale = true."""
    seed_branch()
    branch.recovery["checked_at"] = time.monotonic() - 11

    r = branch_client.post("/api/sale", json={"product_id": 1, "qty": 1})

    assert r.status_code == 503
    assert r.json()["detail"] == {"error": "branch_recovering", "stale": True}


def test_reads_still_work_while_recovering(branch_client):
    """PT-14: RECOVERING chỉ chặn ghi; POS vẫn đọc được tồn và trạng thái."""
    seed_branch()
    branch.recovery["state"] = "RECOVERING"

    assert branch_client.get("/api/inventory").status_code == 200
    assert branch_client.get("/api/status").json()["recovery"]["state"] == "RECOVERING"


# ---------------------------------------------------------------------------
# Chuyển trạng thái (hàm thuần, docs/spec.md mục 4)
# ---------------------------------------------------------------------------
def P(pending=(), accepting=False) -> dict:
    return {"pending": list(pending), "accepting": accepting}


CLEAN = P()


@pytest.mark.parametrize("state, incomplete, pulls, elapsed, expected", [
    # Đang RECOVERING
    ("RECOVERING", False, {"A": CLEAN, "B": CLEAN}, 1, ("ONLINE", False)),        # mọi bản sao trả lời, sạch
    ("RECOVERING", False, {"A": CLEAN, "B": P([1])}, 1, ("RECOVERING", False)),   # còn lượt chờ áp
    ("RECOVERING", False, {"A": CLEAN, "B": P(accepting=True)}, 1, ("RECOVERING", False)),  # B còn nhận ghi hộ
    ("RECOVERING", False, {"A": CLEAN, "B": None}, 59, ("RECOVERING", False)),    # B không gọi được: chờ
    ("RECOVERING", False, {"A": CLEAN, "B": None}, 60, ("ONLINE", True)),         # hết 60 giây: ONLINE kèm cảnh báo
    ("RECOVERING", False, {"A": P(accepting=True), "B": None}, 120, ("RECOVERING", False)),  # hết hạn chỉ cho bản sao không gọi được
    ("RECOVERING", False, {}, 0, ("ONLINE", False)),                               # không cấu hình bản sao nào
    # Đang ONLINE
    ("ONLINE", False, {"A": None, "B": None}, 0, ("ONLINE", False)),               # K3: cô lập hẳn vẫn bán tại chỗ
    ("ONLINE", False, {"A": None, "B": CLEAN}, 0, ("ONLINE", False)),
    ("ONLINE", False, {"A": CLEAN, "B": P([1])}, 0, ("RECOVERING", False)),       # có ghi hộ mới: áp trước khi bán tiếp
    ("ONLINE", False, {"A": P(accepting=True)}, 0, ("RECOVERING", False)),        # vừa unpause: đa số vẫn thấy OFFLINE
    ("ONLINE", True, {"A": CLEAN, "B": None}, 0, ("ONLINE", True)),                # vẫn chưa gom được từ B
    ("ONLINE", True, {"A": CLEAN, "B": CLEAN}, 0, ("ONLINE", False)),              # gom đủ: hết cảnh báo
])
def test_recovery_state_transitions(state, incomplete, pulls, elapsed, expected):
    """PT-14: ONLINE chỉ khi mọi bản sao trả lời, không còn PENDING, không còn nhận ghi hộ; hết 60 giây mà vẫn có bản
    sao không gọi được thì ONLINE kèm incomplete; đang ONLINE thì bản sao không gọi được không làm dừng quầy."""
    assert branch.next_recovery_state(state, incomplete, pulls, elapsed) == expected


# ---------------------------------------------------------------------------
# /api/status cho POS, dashboard
# ---------------------------------------------------------------------------
def test_status_shows_recovery_and_rejected_items(branch_client):
    """PT-14: /api/status có trạng thái phục hồi, số đã áp, đã từ chối, lần chạy cuối, các lượt bị từ chối."""
    seed_branch()
    set_qty(1, 2)
    pulls = {"A": handoff_pull("A", [(1, "r1", 1, 5), (2, "r2", 2, 1)])}

    branch.recovery_once(lambda name: pulls[name], lambda name, p: None, ["A"])
    branch.recovery_once(lambda name: pulls[name], lambda name, p: None, ["A"])  # ack mất, kéo lại: không đếm lại
    st = branch_client.get("/api/status").json()["recovery"]

    assert st["state"] == "RECOVERING"
    assert (st["pending"], st["applied"], st["rejected"]) == (2, 1, 1)
    assert st["incomplete"] is False and st["unreachable"] == []
    assert st["last_run_at"] is not None and st["last_error"] is None
    assert [(i["request_id"], i["qty"], i["qty_on_hand"], i["reason"]) for i in st["rejected_items"]] == [
        ("r1", 5, 2, "insufficient_stock")]
