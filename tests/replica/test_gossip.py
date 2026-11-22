"""Kênh trực tiếp (vòng 3): gossip giữa các bản sao, đối soát với chi nhánh khi mất broker.

Phần gọi mạng nằm trong workers/gossip.py; ở đây chỉ test hàm nhận dữ liệu đã lấy về (không gọi mạng).
"""
import pytest
from fixtures import cell, count, event, node, one_peer, sink_state, snapshot_rows

from common.db import pool
from services import replica
from services.replica import apply_event


def local_cells() -> list[dict]:
    with pool.connection() as conn:
        return replica.query_snapshot(conn)


def branch_payload(branch_id: int, *cells: tuple[int, int, int]) -> dict:
    """Phản hồi GET /api/snapshot của chi nhánh; mỗi ô (product_id, last_movement, qty)."""
    return {"branch_id": branch_id, "cells": [
        {"product_id": p, "last_movement": m, "qty_on_hand": q, "node_time": "2026-11-19T08:00:00+00:00"}
        for p, m, q in cells]}


# ---------------------------------------------------------------------------
# Gossip: chỉ vá ô lệch ở 2 lần kiểm liên tiếp với cùng bản sao (pick_stale là hàm thuần)
# ---------------------------------------------------------------------------
def test_first_mismatch_only_remembers_cells_ahead():
    """PT-10: lần kiểm đầu thấy lệch thì chưa vá, chỉ nhớ ô bản sao kia đi trước và movement_id của nó."""
    patch, pending = replica.pick_stale([cell(2, 1, 9, 40), cell(2, 2, 3, 70)],
                                        [cell(2, 1, 8, 41), cell(2, 2, 3, 70)], {})

    assert patch == []
    assert pending == {(2, 1): 9}


def test_sink_catching_up_between_checks_patches_nothing():
    """PT-10: sink đã đưa ô tới movement_id thấy ở lần trước thì không vá, dù bản sao kia lại đi trước."""
    patch, pending = replica.pick_stale([cell(2, 1, 10, 39)], [cell(2, 1, 9, 40)], {(2, 1): 9})

    assert patch == []
    assert pending == {(2, 1): 10}


def test_cell_still_behind_after_two_checks_is_patched_with_latest_value():
    """PT-10: ô vẫn thiếu sau 2 lần kiểm (kể cả ô chưa có) thì vá bằng giá trị mới nhất của bản sao kia."""
    remote = [cell(2, 1, 11, 38), cell(2, 2, 3, 70), cell(2, 3, 4, 20)]
    local = [cell(2, 1, 8, 41), cell(2, 2, 3, 70)]

    patch, pending = replica.pick_stale(remote, local, {(2, 1): 9, (2, 3): 4})

    assert sorted((c["branch_id"], c["product_id"], c["last_movement"]) for c in patch) == [(2, 1, 11), (2, 3, 4)]
    assert pending == {}


def test_cell_where_this_replica_is_ahead_is_never_patched():
    """PT-05, PT-10: bản sao này đi trước thì không vá, không nhớ."""
    patch, pending = replica.pick_stale([cell(2, 1, 5, 50)], [cell(2, 1, 9, 40)], {(2, 1): 5})

    assert patch == []
    assert pending == {}


def test_normal_sink_lag_never_counts_as_patched(db):
    """PT-10 (K1): sink chậm vài giây, kịp áp trước lần kiểm sau, thì cells_patched vẫn 0."""
    apply_event(event(8, qty_after=41))
    remote = [cell(2, 1, 9, 40)]
    patch, pending = replica.pick_stale(remote, local_cells(), {})
    replica.merge_replica_snapshot("A", patch)

    apply_event(event(9, qty_after=40))  # sink giao trước lần kiểm sau
    patch, pending = replica.pick_stale(remote, local_cells(), pending)
    replica.merge_replica_snapshot("A", patch)

    assert one_peer("A")["cells_patched"] == 0
    assert one_peer("A")["last_ok_at"] is not None
    assert snapshot_rows()[0]["source"] == "kafka"


def test_replica_snapshot_merge_records_exchange_and_counts_patched(db):
    """PT-10: mỗi lần trao đổi ghi last_ok_at; cells_patched cộng đúng số ô thật sự được vá."""
    assert replica.merge_replica_snapshot("A", [cell(2, 1, 9, 40), cell(2, 2, 3, 70)]) == 2
    assert replica.merge_replica_snapshot("A", [cell(2, 1, 9, 40)]) == 0

    p = one_peer("A")
    assert p["channel"] == "gossip"
    assert p["cells_patched"] == 2
    assert p["last_ok_at"] is not None and p["failing_since"] is None
    assert {r["source"] for r in snapshot_rows()} == {"gossip"}


def test_peer_error_keeps_last_ok_and_first_failure(db):
    """Gọi bản sao khác lỗi nhiều lần: giữ lần được cuối và mốc lỗi đầu; gọi được lại thì xoá mốc lỗi."""
    replica.merge_replica_snapshot("B", [])
    ok_at = one_peer("B")["last_ok_at"]
    replica.record_peer_error("B", "gossip", "ConnectTimeout")
    first = one_peer("B")["failing_since"]
    replica.record_peer_error("B", "gossip", "ConnectError")

    p = one_peer("B")
    assert p["last_ok_at"] == ok_at
    assert first is not None and p["failing_since"] == first
    assert p["last_error"] == "ConnectError"

    replica.merge_replica_snapshot("B", [])
    assert one_peer("B")["failing_since"] is None


def test_invalid_cell_from_peer_is_rejected_and_writes_nothing(db):
    """PT-10: dữ liệu từ node khác được kiểm trước khi merge; sai thì không ghi gì."""
    with pytest.raises(ValueError):
        replica.merge_replica_snapshot("A", [cell(2, 1, 9, 40), cell(2, 2, 3, -5)])

    assert count("inventory_snapshot") == 0
    assert count("sync_peer") == 0


# ---------------------------------------------------------------------------
# Đối soát với chi nhánh
# ---------------------------------------------------------------------------
def test_branch_snapshot_merge_marks_reconcile(db):
    """PT-10: ô vá từ snapshot chi nhánh mang nguồn reconcile; ô không thiếu giữ nguyên nguồn."""
    replica.merge_replica_snapshot("A", [cell(2, 2, 3, 70)])

    n = replica.merge_branch_snapshot(2, branch_payload(2, (1, 8, 47), (2, 3, 70)))

    assert n == 1
    assert [(r["product_id"], r["qty_on_hand"], r["source"]) for r in snapshot_rows()] == [
        (1, 47, "reconcile"), (2, 70, "gossip")]
    p = one_peer("CN2")
    assert p["channel"] == "reconcile" and p["cells_patched"] == 1


def test_branch_snapshot_with_wrong_branch_id_is_rejected(db):
    """PT-07, PT-10: gọi CN2 mà nhận số của chi nhánh khác thì từ chối, không ghi gì."""
    with pytest.raises(ValueError):
        replica.merge_branch_snapshot(2, branch_payload(3, (1, 8, 47)))

    assert count("inventory_snapshot") == 0


def targets() -> list[int]:
    with pool.connection() as conn:
        return [r["branch_id"] for r in replica.reconcile_targets(conn)]


def test_no_reconcile_while_broker_unchecked_or_ok(db):
    """PT-10: đường đọc Redpanda chưa kiểm hoặc đang được thì không đối soát."""
    node(2, "http://branch-b:8000")
    assert targets() == []

    sink_state(True)
    assert targets() == []


def test_no_reconcile_before_15s_of_broker_loss(db):
    """PT-10: mất broker chưa quá 15 giây (giờ của replica_db) thì chưa đối soát."""
    node(2, "http://branch-b:8000")
    sink_state(False, lost_ago_s=10)

    assert targets() == []


def test_reconcile_only_alive_branches_with_url_after_15s(db):
    """PT-10: mất broker quá 15 giây thì đối soát mọi chi nhánh có heartbeat trong 15 giây và có branch_url."""
    node(1, "http://branch-a:8000")
    node(2, "http://branch-b:8000")
    node(3, "http://branch-c:8000", seen_ago_s=30)
    node(4, None)
    sink_state(False, lost_ago_s=16)

    with pool.connection() as conn:
        rows = replica.reconcile_targets(conn)
    assert [(r["branch_id"], r["branch_url"]) for r in rows] == [
        (1, "http://branch-a:8000"), (2, "http://branch-b:8000")]


def test_no_reconcile_when_sink_itself_is_dead(db):
    """Sink đã dừng (lần kiểm broker cũ quá 15 giây) thì không đối soát; gossip lo phần vá."""
    node(2, "http://branch-b:8000")
    sink_state(False, lost_ago_s=40, checked_ago_s=20)

    assert targets() == []


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------
def test_snapshot_endpoint_lists_cells(replica_client):
    """PT-10: GET /api/snapshot trả mọi ô kèm last_movement để bản sao khác merge."""
    replica.merge_replica_snapshot("A", [cell(2, 1, 9, 40)])

    body = replica_client.get("/api/snapshot").json()

    assert body["node"] == "T"
    assert [{k: c[k] for k in ("branch_id", "product_id", "qty_on_hand", "last_movement")}
            for c in body["cells"]] == [{"branch_id": 2, "product_id": 1, "qty_on_hand": 40, "last_movement": 9}]
    assert "node_time" in body["cells"][0]


def test_heartbeat_stores_branch_url(replica_client):
    """Heartbeat mang branch_url; bản sao lưu vào node_status để đối soát."""
    hb = {"branch_id": 2, "branch_name": "CN2", "node_time_ms": 1_763_000_000_000,
          "branch_url": "http://branch-b:8000"}

    assert replica_client.post("/api/heartbeat", json=hb).status_code == 200
    with pool.connection() as conn:
        url = conn.execute("SELECT branch_url FROM node_status WHERE branch_id = 2").fetchone()["branch_url"]
    assert url == "http://branch-b:8000"


def test_heartbeat_rejects_non_http_branch_url(replica_client):
    """branch_url là dữ liệu từ ngoài vào: chỉ nhận http:// hoặc https://."""
    hb = {"branch_id": 2, "branch_name": "CN2", "node_time_ms": 1, "branch_url": "file:///etc/passwd"}

    assert replica_client.post("/api/heartbeat", json=hb).status_code == 422


def test_digest_and_inventory_expose_sync_state(replica_client):
    """Dashboard: digest có sync_peers (cột Gossip), mỗi ô tồn có source (nhãn "qua đối soát")."""
    replica.merge_branch_snapshot(2, branch_payload(2, (1, 8, 47)))

    d = replica_client.get("/api/digest").json()
    inv = replica_client.get("/api/inventory").json()

    assert [(p["peer"], p["channel"], p["cells_patched"]) for p in d["sync_peers"]] == [("CN2", "reconcile", 1)]
    assert inv[0]["by_branch"]["2"]["source"] == "reconcile"


def test_source_is_not_part_of_fingerprint(replica_client):
    """PT-10: cùng số liệu mà khác nguồn vẫn cùng dấu vân tay."""
    replica.merge_replica_snapshot("A", [cell(2, 1, 9, 40)])
    gossip_fp = replica_client.get("/api/digest").json()["fingerprint"]
    with pool.connection() as conn:
        conn.execute("DELETE FROM inventory_snapshot")
    apply_event(event(9, qty_after=40))

    assert replica_client.get("/api/digest").json()["fingerprint"] == gossip_fp
