"""Truy vết một sự kiện ở bản sao (vòng 4): lưu timestamp Kafka, GET /api/trace cho biết bản sao biết sự kiện bằng đường nào.

Ô vá bằng gossip hoặc đối soát không có dòng event_log (docs/db.md mục 3), nên `via` dựa vào ô snapshot.
"""
from datetime import datetime, timezone

from fixtures import cell, event

from services import replica
from services.replica import apply_event

T1 = datetime(2026, 11, 22, 8, 0, 1, 250000, tzinfo=timezone.utc)
T2 = datetime(2026, 11, 22, 8, 5, 0, tzinfo=timezone.utc)


def trace(client, movement_id: int, product_id: int = 1, branch_id: int = 2) -> dict:
    r = client.get("/api/trace", params={"branch_id": branch_id, "movement_id": movement_id,
                                         "product_id": product_id})
    assert r.status_code == 200
    return r.json()


def test_kafka_timestamp_is_stored_and_traced(replica_client):
    """PT-04: dòng event_log (khoá branch_id, movement_id) giữ vị trí và timestamp Kafka; trace trả via=kafka."""
    apply_event(event(57, qty_after=40), 1, 42, T1)

    t = trace(replica_client, 57)

    assert t["node"] == "T"
    assert (t["branch_id"], t["movement_id"], t["product_id"]) == (2, 57, 1)
    assert t["via"] == "kafka"
    assert t["event"]["kafka_partition"] == 1
    assert t["event"]["kafka_offset"] == 42
    assert datetime.fromisoformat(t["event"]["kafka_ts"]) == T1
    assert t["event"]["received_at"] is not None
    assert t["event"]["qty_after"] == 40
    assert t["cell"]["last_movement"] == 57
    assert t["cell"]["source"] == "kafka"


def test_duplicate_keeps_first_kafka_position(replica_client):
    """PT-04: relay gửi lại tạo thông điệp mới (offset, timestamp khác); bản trùng bị bỏ, trace giữ lần đầu."""
    apply_event(event(57, qty_after=40), 1, 42, T1)
    apply_event(event(57, qty_after=40), 2, 99, T2)

    e = trace(replica_client, 57)["event"]

    assert (e["kafka_partition"], e["kafka_offset"]) == (1, 42)
    assert datetime.fromisoformat(e["kafka_ts"]) == T1


def test_cell_patched_by_gossip_has_no_log_row(replica_client):
    """PT-10: gossip vá ô mà không bịa dòng nhật ký; trace báo via=gossip, event=null."""
    replica.merge_replica_snapshot("A", [cell(2, 1, 57, 40)])

    t = trace(replica_client, 57)

    assert t["event"] is None
    assert t["via"] == "gossip"
    assert t["cell"]["last_movement"] == 57
    assert t["cell"]["qty_on_hand"] == 40
    assert t["cell"]["source"] == "gossip"


def test_older_event_covered_by_gossip_patch(replica_client):
    """PT-10: gossip vá ô tới #60 thì sự kiện #57 cũng đã nằm trong số tồn đó; via=gossip."""
    replica.merge_replica_snapshot("A", [cell(2, 1, 60, 37)])

    assert trace(replica_client, 57)["via"] == "gossip"


def test_cell_patched_by_reconcile(replica_client):
    """PT-07, PT-10: ô đọc thẳng từ chi nhánh (đối soát) không có dòng nhật ký; via=reconcile."""
    replica.merge_branch_snapshot(2, {"branch_id": 2, "cells": [
        {"product_id": 1, "last_movement": 57, "qty_on_hand": 40, "node_time": "2026-11-19T08:00:00+00:00"}]})

    t = trace(replica_client, 57)

    assert t["event"] is None
    assert t["via"] == "reconcile"
    assert t["cell"]["source"] == "reconcile"


def test_event_logged_after_patch_shows_both(replica_client):
    """PT-04, PT-10: sự kiện tới qua Redpanda sau khi ô đã vá bằng đối soát: có nhật ký (via=kafka), ô giữ nguồn cũ."""
    replica.merge_branch_snapshot(2, {"branch_id": 2, "cells": [
        {"product_id": 1, "last_movement": 57, "qty_on_hand": 40, "node_time": "2026-11-19T08:00:00+00:00"}]})
    apply_event(event(57, qty_after=40), 0, 5, T1)

    t = trace(replica_client, 57)

    assert t["via"] == "kafka"
    assert t["event"]["kafka_offset"] == 5
    assert t["cell"]["source"] == "reconcile"
    assert t["cell"]["last_movement"] == 57


def test_unknown_event_is_missing(replica_client):
    """PT-05: ô chưa tới movement_id (hoặc chưa có ô) thì bản sao chưa biết sự kiện; via=missing."""
    apply_event(event(5, qty_after=45), 0, 1, T1)

    behind = trace(replica_client, 9)
    no_cell = trace(replica_client, 9, product_id=7)

    assert behind["via"] == "missing"
    assert behind["event"] is None
    assert behind["cell"]["last_movement"] == 5
    assert no_cell["via"] == "missing"
    assert no_cell["cell"] is None


def test_skipped_event_is_superseded(replica_client):
    """PT-05: bản sao bỏ qua #57 (seek --to end) nhưng đã nhận #60 qua Redpanda: không có nhật ký, via=superseded."""
    apply_event(event(60, qty_after=37), 0, 9, T1)

    t = trace(replica_client, 57)

    assert t["event"] is None
    assert t["via"] == "superseded"
    assert t["cell"]["last_movement"] == 60


def test_inventory_exposes_cell_version(replica_client):
    """PT-05: mỗi ô có last_movement (phiên bản do chi nhánh cấp) để dashboard đọc đơn điệu, không so bằng đồng hồ."""
    apply_event(event(57, qty_after=40))

    inv = replica_client.get("/api/inventory").json()
    overview = replica_client.get("/api/overview").json()

    assert inv[0]["by_branch"]["2"]["last_movement"] == 57
    assert overview["inventory"][0]["by_branch"]["2"]["last_movement"] == 57
