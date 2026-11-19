"""
Một ứng dụng FastAPI cho cả hai vai, chọn bằng biến ROLE:
  ROLE=branch   quầy chi nhánh: POS, bán, nhập; gửi heartbeat tới mọi bản sao
  ROLE=replica  bản sao trung tâm: nhận heartbeat, phục vụ dashboard

Tiến trình nền chạy riêng, cùng image: workers/relay.py (chi nhánh), workers/sink.py (bản sao).
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request

from common.config import BRANCH_ID, NODE_NAME, ROLE
from common.db import open_pool, pool
from routers import branch, replica
from services.branch import seed_if_empty
from workers import heartbeat


@asynccontextmanager
async def lifespan(app: FastAPI):
    open_pool()
    if ROLE == "branch":
        seed_if_empty()
        heartbeat.start()
    yield
    pool.close()


if ROLE == "branch":
    app = FastAPI(title=f"api_cn{BRANCH_ID}", lifespan=lifespan)
    app.include_router(branch.router)
else:
    app = FastAPI(title=f"replica {NODE_NAME}", lifespan=lifespan)
    app.include_router(replica.router)

    @app.middleware("http")
    async def served_by_header(request: Request, call_next):
        """Gắn tên bản sao vào MỌI phản hồi. Thử: curl -I http://<IP máy A>/api/stats"""
        response = await call_next(request)
        response.headers["X-Served-By"] = f"replica-{NODE_NAME}"
        return response
