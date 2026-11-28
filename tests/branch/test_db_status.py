"""Trạng thái CSDL chi nhánh (vòng 7, PT-12): vai trò, chế độ đồng bộ, standby, timeline; POS (P-11) và dashboard (D-21)
cảnh báo khi primary không có standby đang streaming.

CSDL test chỉ có một Postgres (không standby), nên phần có standby kiểm bằng hàm thuần `summarize_db` nhận dòng đã đọc.
"""
from services import branch


def raw(**o) -> dict:
    """Một dòng như `db_status` đọc được: primary, async, không standby nào nối."""
    return {"in_recovery": False, "standby_names": "", "timeline": 1, "state": None, "lag_bytes": None, **o}


def test_primary_async_without_standby():
    """PT-12: mặc định bất đồng bộ; không có standby thì `connected` false (P-11, D-21 vàng)."""
    assert branch.summarize_db(raw()) == {
        "role": "primary", "sync_mode": "async",
        "standby": {"connected": False, "state": None, "lag_bytes": None}, "timeline": 1}


def test_sync_mode_with_streaming_standby():
    """PT-12: `synchronous_standby_names` khác rỗng là đồng bộ; standby `streaming` thì `connected`."""
    db = branch.summarize_db(raw(standby_names="*", state="streaming", lag_bytes=0, timeline=2))
    assert db["sync_mode"] == "sync"
    assert db["standby"] == {"connected": True, "state": "streaming", "lag_bytes": 0}
    assert db["timeline"] == 2


def test_standby_catching_up_is_not_connected():
    """PT-12: standby vừa `rejoin`, còn `catchup`, chưa tính là có standby (lượt bán đồng bộ vẫn chưa an toàn)."""
    db = branch.summarize_db(raw(standby_names="*", state="catchup", lag_bytes=4096))
    assert db["standby"] == {"connected": False, "state": "catchup", "lag_bytes": 4096}


def test_any_non_empty_standby_names_is_sync():
    """PT-12: dạng `ANY 1 (...)`, `FIRST 1 (...)` cũng là đồng bộ; chỉ chuỗi rỗng (kể cả khoảng trắng) là bất đồng bộ."""
    assert branch.summarize_db(raw(standby_names="ANY 1 (a, b)"))["sync_mode"] == "sync"
    assert branch.summarize_db(raw(standby_names="  "))["sync_mode"] == "async"


def test_connected_to_standby_reports_standby_role():
    """PT-12: `pg_is_in_recovery()` đúng nghĩa là đang nối vào standby (không xảy ra khi có `target_session_attrs`)."""
    assert branch.summarize_db(raw(in_recovery=True))["role"] == "standby"


def test_status_endpoint_reports_db_of_test_database(branch_client):
    """PT-12: `/api/status` có `db`, đọc thật trên CSDL test: primary, async, không standby, timeline >= 1."""
    db = branch_client.get("/api/status").json()["db"]
    assert db["role"] == "primary"
    assert db["sync_mode"] == "async"
    assert db["standby"] == {"connected": False, "state": None, "lag_bytes": None}
    assert isinstance(db["timeline"], int) and db["timeline"] >= 1
