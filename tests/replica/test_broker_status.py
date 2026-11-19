"""Sink ghi trạng thái đường đọc Redpanda để dashboard báo "đồng bộ dừng" (PT-11)."""
from fixtures import one_row

from services import replica


def test_broker_loss_keeps_first_lost_time(db):
    """PT-11: mất broker nhiều lần kiểm liên tiếp vẫn giữ mốc mất đầu tiên."""
    replica.record_broker_check(False, None)
    first = one_row("sink_stats")
    replica.record_broker_check(False, None)
    second = one_row("sink_stats")

    assert second["broker_ok"] is False
    assert first["broker_lost_at"] is not None
    assert second["broker_lost_at"] == first["broker_lost_at"]
    assert second["broker_checked_at"] is not None


def test_broker_recovery_clears_lost_time_and_sets_lag(db):
    """PT-11: có lại kết nối thì xoá mốc mất, ghi lag mới."""
    replica.record_broker_check(False, None)
    replica.record_broker_check(True, 7)
    row = one_row("sink_stats")

    assert row["broker_ok"] is True
    assert row["broker_lost_at"] is None
    assert row["lag"] == 7


def test_lag_kept_when_broker_unreachable(db):
    """PT-11: không đo được lag (mất broker) thì giữ số đo được gần nhất."""
    replica.record_broker_check(True, 5)
    replica.record_broker_check(False, None)

    assert one_row("sink_stats")["lag"] == 5


def test_stats_endpoint_exposes_broker_state(replica_client):
    """PT-11: /api/stats (và digest trong /api/overview) có trạng thái broker cho dashboard."""
    replica.record_broker_check(False, None)
    stats = replica_client.get("/api/stats").json()

    assert stats["broker_ok"] is False
    assert stats["broker_lost_at"] is not None
    assert {"lag", "broker_checked_at"} <= stats.keys()
