"""Áp sự kiện ở bản sao: các quy tắc đã có từ vòng 0."""
from fixtures import count, event, snapshot_cell

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
