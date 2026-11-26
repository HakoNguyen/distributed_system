"""Bộ phát hiện lỗi (vòng 5, PT-13): trạng thái từng chi nhánh theo tuổi heartbeat, kết luận theo đa số bản sao.

Góc nhìn của bản sao khác lấy qua GET /api/views (workers/gossip.py: view_loop); ở đây chỉ test hàm nhận dữ liệu đã
lấy về (record_peer_view) và hàm thuần, không gọi mạng. Mốc thời gian lùi bằng SQL, không sleep.
"""
import pytest
from fixtures import count, node, peer_view, peer_view_rows

from common.db import pool
from services import replica

ON, SUS, OFF = "ONLINE", "SUSPECT", "OFFLINE"


@pytest.fixture
def three_replicas(monkeypatch):
    """Cấu hình 3 bản sao A, T (bản sao đang test, NODE_NAME=T), C: đa số là 2."""
    monkeypatch.setattr(replica, "REPLICA_NAMES", ["A", "T", "C"])


def nodes() -> list[dict]:
    with pool.connection() as conn:
        return replica.query_nodes(conn)


# ---------------------------------------------------------------------------
# Trạng thái theo tuổi heartbeat (hàm thuần)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("age, state", [
    (0, ON), (7.9, ON),          # chưa lỡ nhịp nào (heartbeat mỗi 5 giây, dư 3 giây cho trễ mạng)
    (8, SUS), (14.9, SUS),       # đã lỡ ít nhất một nhịp
    (15, OFF), (60, OFF),        # = NODE_TIMEOUT_S: mất liên lạc như trước vòng 5
])
def test_state_thresholds_follow_heartbeat_age(age, state):
    """PT-13: ONLINE dưới 8 giây, SUSPECT từ 8 tới dưới 15 giây, OFFLINE từ 15 giây."""
    assert replica.branch_state(age) == state


# ---------------------------------------------------------------------------
# Kết luận theo đa số (hàm thuần): đa số tính trên TỔNG số bản sao cấu hình
# ---------------------------------------------------------------------------
def test_two_of_three_offline_is_offline():
    """PT-13: 2/3 bản sao thấy OFFLINE thì kết luận OFFLINE."""
    assert replica.majority_state([OFF, OFF, ON], 3) == OFF


def test_one_of_three_offline_is_not_offline():
    """PT-13 (K14 biến thể): chỉ một bản sao mất liên lạc với chi nhánh thì kết luận vẫn ONLINE."""
    assert replica.majority_state([OFF, ON, ON], 3) == ON


def test_two_offline_with_dead_replica_is_still_offline():
    """PT-13: bản sao thứ ba đã chết (không có góc nhìn) mà hai bản còn lại thấy OFFLINE thì vẫn đủ đa số."""
    assert replica.majority_state([OFF, OFF, None], 3) == OFF


def test_isolated_replica_cannot_conclude_offline():
    """PT-13 (K3): bản sao bị cô lập chỉ có góc nhìn của chính nó, 1/3 không đủ đa số: nghi ngờ, không OFFLINE."""
    assert replica.majority_state([OFF, None, None], 3) == SUS


@pytest.mark.parametrize("states", [[OFF, SUS, ON], [SUS, SUS, ON], [None, None, None]])
def test_no_quorum_either_way_is_suspect(states):
    """PT-13: không đủ đa số OFFLINE, cũng không đủ đa số ONLINE thì là SUSPECT."""
    assert replica.majority_state(states, 3) == SUS


def test_two_online_with_dead_replica_is_online():
    """PT-13: thiếu góc nhìn của một bản sao không làm chi nhánh đang sống bị nghi ngờ."""
    assert replica.majority_state([ON, ON, None], 3) == ON


# ---------------------------------------------------------------------------
# Góc nhìn của chính bản sao này: GET /api/views
# ---------------------------------------------------------------------------
def test_views_endpoint_reports_own_state(replica_client):
    """PT-13: /api/views trả trạng thái theo tuổi heartbeat mà CHÍNH bản sao này nhận."""
    node(1, None, seen_ago_s=0)
    node(2, None, seen_ago_s=10)
    node(3, None, seen_ago_s=20)

    body = replica_client.get("/api/views").json()

    assert body["node"] == "T"
    assert [(b["branch_id"], b["state"]) for b in body["branches"]] == [(1, ON), (2, SUS), (3, OFF)]
    assert [b["seconds_since_seen"] for b in body["branches"]] == [0, 10, 20]


def test_views_endpoint_writes_nothing(replica_client):
    """PT-13: đọc góc nhìn không ghi gì vào CSDL của bản sao."""
    node(2, None, seen_ago_s=10)

    replica_client.get("/api/views")

    assert count("peer_view") == 0


# ---------------------------------------------------------------------------
# Góc nhìn của bản sao khác: record_peer_view (dữ liệu đã lấy về qua mạng)
# ---------------------------------------------------------------------------
def views(*branches: tuple[int, str, int]) -> dict:
    """Phản hồi GET /api/views của một bản sao khác; mỗi chi nhánh (branch_id, state, seconds_since_seen)."""
    return {"node": "A", "branches": [
        {"branch_id": b, "state": s, "seconds_since_seen": a} for b, s, a in branches]}


def test_peer_view_upserts_latest_state(db):
    """PT-13: nhận góc nhìn hai lần thì mỗi (bản sao, chi nhánh) chỉ một dòng, giữ góc nhìn mới nhất."""
    replica.record_peer_view("A", views((1, ON, 2), (2, ON, 3)))
    replica.record_peer_view("A", views((1, ON, 1), (2, SUS, 9)))

    assert peer_view_rows() == [
        {"peer": "A", "branch_id": 1, "state": ON, "seconds_since_seen": 1},
        {"peer": "A", "branch_id": 2, "state": SUS, "seconds_since_seen": 9},
    ]


@pytest.mark.parametrize("bad", [
    views((2, "DEAD", 3)),                             # trạng thái lạ
    views((2, ON, -1)),                                # tuổi âm
    {"node": "A", "branches": [{"branch_id": 2}]},    # thiếu trường
])
def test_invalid_peer_view_writes_nothing(db, bad):
    """PT-13: dữ liệu hỏng từ bản sao khác bị từ chối trước khi ghi; dòng hợp lệ cùng lô cũng không được ghi."""
    payload = {"node": "A", "branches": [{"branch_id": 1, "state": ON, "seconds_since_seen": 0}] + bad["branches"]}

    with pytest.raises(ValueError):
        replica.record_peer_view("A", payload)

    assert count("peer_view") == 0


# ---------------------------------------------------------------------------
# query_nodes: góc nhìn của mình, của từng bản sao, kết luận đa số
# ---------------------------------------------------------------------------
def test_nodes_show_own_state_views_and_verdict(db, three_replicas):
    """PT-13: mỗi chi nhánh có state (góc nhìn của mình), views (từng bản sao) và verdict (đa số); alive giữ nghĩa cũ."""
    node(2, None, seen_ago_s=20)          # bản sao T (chính mình) thấy CN2 OFFLINE
    peer_view("A", 2, OFF)
    peer_view("C", 2, ON)

    [n] = nodes()

    assert n["state"] == OFF
    assert n["views"] == {"A": OFF, "T": OFF, "C": ON}
    assert n["verdict"] == OFF
    assert n["alive"] is False


def test_only_this_replica_lost_contact_keeps_verdict_online(db, three_replicas):
    """PT-13 (K14 biến thể): chỉ bản sao này mất liên lạc với chi nhánh thì góc nhìn riêng OFFLINE, kết luận ONLINE."""
    node(2, None, seen_ago_s=30)
    peer_view("A", 2, ON)
    peer_view("C", 2, ON)

    [n] = nodes()

    assert (n["state"], n["verdict"]) == (OFF, ON)


def test_stale_peer_view_is_ignored(db, three_replicas):
    """PT-13: góc nhìn nhận cũ quá 15 giây (bản sao kia đã chết hoặc bị cô lập) không được tính."""
    node(2, None, seen_ago_s=20)
    peer_view("A", 2, OFF, received_ago_s=20)

    [n] = nodes()

    assert n["views"] == {"A": None, "T": OFF, "C": None}
    assert n["verdict"] == SUS


def test_isolated_replica_without_peer_views_is_only_suspect(db, three_replicas):
    """PT-13 (K3): bản sao bị cô lập không có góc nhìn nào của bản sao khác: chi nhánh chỉ là nghi ngờ."""
    node(1, None, seen_ago_s=40)

    [n] = nodes()

    assert (n["state"], n["verdict"]) == (OFF, SUS)


def test_peer_view_of_other_branch_does_not_leak(db, three_replicas):
    """PT-13: góc nhìn về chi nhánh khác không được tính cho chi nhánh này."""
    node(2, None)
    peer_view("A", 3, OFF)
    peer_view("C", 3, OFF)

    [n] = nodes()

    assert n["views"] == {"A": None, "T": ON, "C": None}
    assert n["verdict"] == SUS
