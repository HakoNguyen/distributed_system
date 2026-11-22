"""Áp sự kiện ở bản sao: các quy tắc đã có từ vòng 0."""
from fixtures import cell, count, event, snapshot_cell, snapshot_rows

from services import replica
from services.replica import apply_event


def test_duplicate_event_is_ignored(db):
    """PT-04: nhận lại cùng (branch_id, movement_id) thì bỏ qua, snapshot không đổi, bộ đếm trùng tăng."""
    assert apply_event(event(7, qty_after=40)) == "new"
    assert apply_event(event(7, qty_after=40)) == "duplicate"

    assert snapshot_cell(2, 1) == {"qty_on_hand": 40, "last_movement": 7}
    assert count("event_log") == 1


def test_older_event_arriving_late_does_not_overwrite_newer(db):
    """PT-05: sự kiện cũ đến sau vẫn vào nhật ký nhưng không ghi đè số mới hơn trong snapshot."""
    apply_event(event(9, qty_after=10))
    apply_event(event(5, qty_after=99))

    assert snapshot_cell(2, 1) == {"qty_on_hand": 10, "last_movement": 9}
    assert count("event_log") == 2


def test_event_already_patched_by_gossip_is_logged_without_overwrite(db):
    """PT-04, PT-10: gossip vá ô #9 trước, sink nhận #9 sau: vào nhật ký, ô giữ nguyên và giữ nguồn gossip."""
    replica.merge_replica_snapshot("A", [cell(2, 1, 9, 40)])

    assert apply_event(event(9, qty_after=40)) == "new"

    assert count("event_log") == 1
    assert snapshot_rows() == [{"branch_id": 2, "product_id": 1, "qty_on_hand": 40,
                                "last_movement": 9, "source": "gossip"}]


def test_newer_event_from_kafka_takes_over_patched_cell(db):
    """PT-05, PT-10: sink áp sự kiện mới hơn ô đã vá thì ghi đè, nguồn trở về kafka."""
    replica.merge_replica_snapshot("A", [cell(2, 1, 5, 50)])

    apply_event(event(6, qty_after=49))

    assert snapshot_rows() == [{"branch_id": 2, "product_id": 1, "qty_on_hand": 49,
                                "last_movement": 6, "source": "kafka"}]
