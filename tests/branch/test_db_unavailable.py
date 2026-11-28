"""Mất CSDL giữa chừng, chuyển primary (vòng 7, PT-08, PT-12).

- Lỗi kết nối CSDL (`psycopg.OperationalError`) ở chi nhánh trả 503 `db_unavailable` thay cho 500, để POS giữ
  `request_id`: lượt bán đứt lúc COMMIT có thể đã ghi (standby đã nhận WAL), gửi lại thì nhận kết quả cũ.
- Pool kiểm kết nối lúc lấy ra (`check`), nên kết nối tới primary cũ đã chết không làm hỏng lượt bán kế tiếp.

Test dùng app thật (`main.app`, có xử lý lỗi) nhưng không chạy lifespan (không heartbeat, không luồng phục hồi).
"""
import psycopg
import pytest
from fastapi.testclient import TestClient
from fixtures import branch_qty, count, seed_branch

from common.config import DATABASE_URL
from common.db import pool
from services import branch


@pytest.fixture
def app_client(db) -> TestClient:
    from main import app
    return TestClient(app)


def lost(*_args, **_kw):
    raise psycopg.OperationalError("server closed the connection unexpectedly")


@pytest.mark.parametrize("method, path, fn, body", [
    ("post", "/api/sale", "change_stock", {"product_id": 1, "qty": 1, "request_id": "r-lost"}),
    ("post", "/api/receipt", "change_stock", {"product_id": 1, "qty": 1, "request_id": "r-lost"}),
    ("get", "/api/inventory", "list_inventory", None),
])
def test_db_connection_error_is_503_db_unavailable(app_client, monkeypatch, method, path, fn, body):
    """PT-08: mất kết nối CSDL thì 503 `db_unavailable` (POS giữ `request_id`), không phải 500 (POS từng bỏ mã)."""
    monkeypatch.setattr(branch, fn, lost)
    r = getattr(app_client, method)(path, **({"json": body} if body else {}))
    assert r.status_code == 503
    assert r.json()["detail"]["error"] == "db_unavailable"


def test_sale_committed_but_reply_lost_is_applied_once_on_retry(app_client, monkeypatch):
    """PT-08, PT-12: COMMIT xong (standby đã nhận) rồi kết nối đứt trước khi trả lời: 503; gửi lại cùng `request_id`
    thì trả kết quả cũ (`replayed`), tồn chỉ trừ một lần, một dòng sổ cái."""
    stock = seed_branch()
    real = branch.change_stock

    def commit_then_lose(*args):
        real(*args)
        lost()

    monkeypatch.setattr(branch, "change_stock", commit_then_lose)
    body = {"product_id": 1, "qty": 2, "request_id": "r-commit-lost"}
    assert app_client.post("/api/sale", json=body).status_code == 503

    monkeypatch.setattr(branch, "change_stock", real)
    again = app_client.post("/api/sale", json=body)
    assert again.status_code == 200 and again.json()["replayed"] is True
    assert branch_qty(1) == stock[1] - 2
    assert count("stock_movement") == len(stock) + 1


def test_pool_replaces_dead_connection_before_use(db):
    """PT-12: sau promote, kết nối cũ trong pool đã chết; lấy kết nối ra pool phải được kết nối dùng được ngay."""
    with pool.connection() as conn:
        conn.execute("SELECT 1")  # chắc chắn pool đang giữ ít nhất một kết nối rảnh
    with psycopg.connect(DATABASE_URL, autocommit=True) as admin:
        # Giết mọi kết nối khác tới CSDL test (kết nối của pool), chờ tới khi chết hẳn (tham số timeout, PG 14+)
        admin.execute("""SELECT pg_terminate_backend(pid, 5000) FROM pg_stat_activity
                         WHERE datname = current_database() AND pid <> pg_backend_pid()
                           AND backend_type = 'client backend'""")
    with pool.connection() as conn:
        assert conn.execute("SELECT 1 AS ok").fetchone()["ok"] == 1
