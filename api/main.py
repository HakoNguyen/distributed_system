"""
Một ứng dụng FastAPI cho cả hai vai, chọn bằng biến ROLE:
  ROLE=branch   quầy chi nhánh: POS, bán, nhập; gửi heartbeat tới mọi bản sao; tự kéo ghi hộ khi phục hồi (workers/recovery.py)
  ROLE=replica  bản sao trung tâm: nhận heartbeat, phục vụ dashboard; gossip, đối soát (workers/gossip.py)

Tiến trình nền chạy riêng, cùng image: workers/relay.py (chi nhánh), workers/sink.py (bản sao).
"""
from contextlib import asynccontextmanager

import psycopg
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from common.config import BRANCH_ID, NODE_NAME, ROLE
from common.db import open_pool, pool
from routers import branch, replica
from services.branch import seed_if_empty
from workers import gossip, heartbeat, recovery


@asynccontextmanager
async def lifespan(app: FastAPI):
    open_pool()
    if ROLE == "branch":
        seed_if_empty()
        heartbeat.start()
        recovery.start()  # vòng 6: khởi động ở RECOVERING, kéo và áp ghi hộ rồi mới nhận bán
    else:
        gossip.start()
    yield
    pool.close()


if ROLE == "branch":
    app = FastAPI(title=f"api_cn{BRANCH_ID}", lifespan=lifespan)
    app.include_router(branch.router)

    @app.exception_handler(psycopg.OperationalError)
    async def db_unavailable(_request: Request, _exc: psycopg.OperationalError) -> JSONResponse:
        """Mất CSDL, kết nối đứt giữa chừng, pool hết chờ (vòng 7): 503 thay cho 500. Lượt bán đứt lúc COMMIT có thể đã
        ghi (standby đã nhận WAL), nên POS phải giữ request_id và gửi lại (PT-08); 503 nói rõ "thử lại sau"."""
        return JSONResponse(status_code=503, content={"detail": {"error": "db_unavailable"}})
else:
    app = FastAPI(title=f"replica {NODE_NAME}", lifespan=lifespan)
    app.include_router(replica.router)

    @app.middleware("http")
    async def served_by_header(request: Request, call_next):
        """Gắn tên bản sao vào MỌI phản hồi. Thử: curl -I http://<IP máy A>/api/stats"""
        response = await call_next(request)
        response.headers["X-Served-By"] = f"replica-{NODE_NAME}"
        return response
