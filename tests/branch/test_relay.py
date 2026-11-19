"""Relay: chỉ đánh dấu đã gửi sau khi Redpanda xác nhận (PT-03); ghi trạng thái gửi cho POS (PT-11).

Phần gọi Redpanda được thay bằng hàm `send` giả, nên test không cần broker.
"""
import pytest
from fixtures import one_row, seed_branch, unsent_ids

from services import branch


class BrokerDown(Exception):
    pass


def test_relay_marks_sent_only_after_send_succeeds(db):
    """PT-03: cả lô được gửi theo thứ tự event_id; gửi xong mới đánh dấu sent_at."""
    seed_branch()
    ids = unsent_ids()
    seen = []

    def send(payloads):
        seen.extend(p["movement_id"] for p in payloads)
        assert unsent_ids() == ids  # đang gửi: chưa dòng nào bị đánh dấu

    assert branch.relay_batch(send) == len(ids)
    assert seen == ids
    assert unsent_ids() == []


def test_relay_send_failure_marks_nothing(db):
    """PT-03: mất kết nối giữa chừng (send ném lỗi) thì không dòng nào của lô bị đánh dấu."""
    seed_branch()
    ids = unsent_ids()

    def send(payloads):
        raise BrokerDown("2 thông điệp chưa có xác nhận")

    with pytest.raises(BrokerDown):
        branch.relay_batch(send)
    assert unsent_ids() == ids


def test_event_written_during_send_stays_unsent(db):
    """PT-03: sự kiện ghi trong lúc lô đang gửi không bị đánh dấu nhầm là đã gửi."""
    seed_branch()
    ids = unsent_ids()

    def send(payloads):
        branch.change_stock(1, -1, "SALE", None, None)

    branch.relay_batch(send)
    new = unsent_ids()
    assert len(new) == 1
    assert new[0] > max(ids)


def test_empty_outbox_does_not_call_send(db):
    """PT-03: outbox trống thì không gọi Redpanda."""
    def send(payloads):
        raise AssertionError("không được gọi send khi outbox trống")

    assert branch.relay_batch(send) == 0


def test_relay_error_keeps_first_failing_since(db):
    """PT-11: lỗi liên tiếp giữ mốc lỗi đầu tiên, last_error là lỗi mới nhất."""
    branch.record_relay_result("lỗi 1")
    first = one_row("relay_status")
    branch.record_relay_result("lỗi 2")
    second = one_row("relay_status")

    assert first["failing_since"] is not None
    assert second["failing_since"] == first["failing_since"]
    assert second["last_error"] == "lỗi 2"


def test_relay_success_clears_failure(db):
    """PT-11: gửi được lại thì xoá mốc lỗi, ghi lần gửi được."""
    branch.record_relay_result("mất broker")
    branch.record_relay_result(None)
    row = one_row("relay_status")

    assert row["failing_since"] is None
    assert row["last_ok_at"] is not None


def test_sale_still_works_and_status_shows_relay_failure(branch_client):
    """PT-11, PT-01: relay đang lỗi (mất đa số broker) thì quầy vẫn bán; /api/status báo lỗi gửi."""
    seed_branch()
    backlog = len(unsent_ids())
    branch.record_relay_result("mất đa số broker")

    r = branch_client.post("/api/sale", json={"product_id": 1, "qty": 1})
    status = branch_client.get("/api/status").json()

    assert r.status_code == 200
    assert status["outbox_backlog"] == backlog + 1
    assert status["relay"]["failing_since"] is not None
    assert status["relay"]["last_error"] == "mất đa số broker"
