"""Endpoint của bản sao trung tâm (ROLE=replica): nhận heartbeat, phục vụ dashboard.

Nginx ở máy A chia yêu cầu cho các bản sao. Người dùng không biết mình đang được
bản sao nào phục vụ; mỗi phản hồi vẫn ghi "served_by" để lúc demo nhìn thấy được.
"""
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse

from common.config import NODE_NAME
from common.db import pool
from common.models import Heartbeat
from services import replica

WEB = Path(__file__).resolve().parent.parent / "web"

router = APIRouter()


@router.get("/", include_in_schema=False)
def dashboard():
    return FileResponse(WEB / "dashboard.html")


@router.get("/health")
def health():
    with pool.connection() as conn:
        conn.execute("SELECT 1")
    return {"status": "ok", "node": NODE_NAME}


@router.post("/api/heartbeat")
def heartbeat(hb: Heartbeat):
    replica.record_heartbeat(hb)
    return {"ok": True, "node": NODE_NAME}


@router.get("/api/overview")
def overview():
    """Mọi thứ dashboard cần, lấy trong MỘT lần gọi, để mỗi lần làm mới chỉ do
    đúng một bản sao trả lời (không trộn số của hai bản sao)."""
    with pool.connection() as conn:
        return {
            "served_by": NODE_NAME,
            "nodes": replica.query_nodes(conn),
            "inventory": replica.query_inventory(conn),
            "events": replica.query_events(conn),
            "digest": replica.query_digest(conn),
        }


@router.get("/api/digest")
def digest():
    with pool.connection() as conn:
        return replica.query_digest(conn)


# Các endpoint rời để gọi bằng tay khi cần
@router.get("/api/nodes")
def nodes():
    with pool.connection() as conn:
        return replica.query_nodes(conn)


@router.get("/api/inventory")
def inventory():
    with pool.connection() as conn:
        return replica.query_inventory(conn)


@router.get("/api/events")
def events(limit: int = 30):
    with pool.connection() as conn:
        return replica.query_events(conn, limit)


@router.get("/api/stats")
def stats():
    with pool.connection() as conn:
        return replica.query_stats(conn)
