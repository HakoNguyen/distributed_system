"""Nền cho test: CSDL test thật, pool dùng chung, client gọi thẳng router (không chạy lifespan).

Chạy bằng `make test`: pytest chạy trong container, CSDL là `test_db` (infra/compose.test.yml).
Một CSDL chứa cả schema chi nhánh lẫn bản sao (tên bảng không trùng), nên test được cả hai vai.
"""
import os
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
TEST_DB_URL = os.environ.get("TEST_DB_URL", "postgresql://app:app@localhost:55432/kho_test")

# Đặt env TRƯỚC khi import code: common/config.py đọc env lúc import.
os.environ.update(ROLE="branch", BRANCH_ID="1", BRANCH_NAME="CN test", NODE_NAME="T",
                  DATABASE_URL=TEST_DB_URL, REPLICA_URLS="")

import psycopg  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from common.db import pool  # noqa: E402
from routers import branch as branch_router  # noqa: E402
from routers import replica as replica_router  # noqa: E402


@pytest.fixture(scope="session")
def database():
    """Dựng lại schema từ db/*.sql một lần mỗi phiên test."""
    # Chặn xoá nhầm dữ liệu thật: chỉ dựng lại trên CSDL có tên kết thúc bằng _test
    if not TEST_DB_URL.rsplit("/", 1)[1].endswith("_test"):
        raise RuntimeError(f"TEST_DB_URL phải trỏ vào CSDL tên kết thúc bằng _test: {TEST_DB_URL}")
    try:
        with psycopg.connect(TEST_DB_URL, autocommit=True, connect_timeout=5) as conn:
            conn.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
            for name in ("product.sql", "branch.sql", "replica.sql"):
                conn.execute((REPO / "db" / name).read_text(encoding="utf-8"))
    except psycopg.OperationalError as e:
        pytest.skip(f"Không kết nối được CSDL test (chạy bằng `make test`): {e}")
    pool.open()
    pool.wait(timeout=10)
    yield
    pool.close()


@pytest.fixture
def db(database):
    """Mỗi test bắt đầu với CSDL trống, chỉ còn danh mục sản phẩm và các bảng một dòng
    (bộ đếm của sink, trạng thái relay)."""
    with pool.connection() as conn:
        tables = [r["tablename"] for r in conn.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public' AND tablename <> 'product'"
        ).fetchall()]
        conn.execute(f"TRUNCATE {', '.join(tables)} RESTART IDENTITY CASCADE")
        conn.execute("INSERT INTO sink_stats (id) VALUES (1)")
        conn.execute("INSERT INTO relay_status (id) VALUES (1)")


def _client(router) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


@pytest.fixture
def branch_client(db) -> TestClient:
    return _client(branch_router.router)


@pytest.fixture
def replica_client(db) -> TestClient:
    return _client(replica_router.router)
