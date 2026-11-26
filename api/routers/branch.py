"""Endpoint của chi nhánh (ROLE=branch): màn hình POS, bán, nhập, trạng thái đồng bộ."""
import time
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse

from common.config import BRANCH_ID, BRANCH_NAME, REPLICAS, STUCK_AFTER_S
from common.db import pool
from common.models import StockChange
from services import branch
from workers.heartbeat import links

WEB = Path(__file__).resolve().parent.parent / "web"

router = APIRouter()


@router.get("/", include_in_schema=False)
def pos_page():
    # no-cache: build lại image thì trình duyệt hỏi lại ngay, không hiện giao diện cũ lúc demo
    return FileResponse(WEB / "pos.html", headers={"Cache-Control": "no-cache"})


@router.get("/health")
def health():
    with pool.connection() as conn:
        conn.execute("SELECT 1")
    return {"status": "ok", "branch_id": BRANCH_ID}


@router.get("/api/info")
def info():
    return {"branch_id": BRANCH_ID, "branch_name": BRANCH_NAME,
            "replicas": [name for name, _ in REPLICAS]}


@router.get("/api/inventory")
def inventory():
    return branch.list_inventory()


@router.get("/api/snapshot")
def snapshot():
    """Bản sao gọi khi đối soát (mất broker quá 15 giây). Chỉ đọc."""
    return branch.snapshot()


@router.get("/api/movement/{movement_id}")
def movement(movement_id: int):
    """Dashboard truy vết một sự kiện: mốc ở chi nhánh và lúc relay gửi xong. Chỉ đọc."""
    return branch.movement(movement_id)


@router.get("/api/status")
def status():
    """Trạng thái cho màn hình POS: outbox còn bao nhiêu, đường nối tới từng bản sao ra sao."""
    b = branch.outbox_backlog()
    oldest = float(b["oldest_s"]) if b["oldest_s"] is not None else 0.0
    return {
        "branch_id": BRANCH_ID,
        "outbox_backlog": b["n"],
        "oldest_unsent_s": round(oldest, 1),
        # Sự kiện cũ nhất đã nằm chờ quá lâu -> relay đang không gửi được
        "sync_stuck": b["n"] > 0 and oldest >= STUCK_AFTER_S,
        # Relay ghi lại lần gửi cuối: failing_since khác None -> "Gửi lên Redpanda: lỗi từ HH:MM:SS"
        "relay": branch.relay_status(),
        "links": [
            {"name": l["name"], "ok": l["ok"], "rtt_ms": l["rtt_ms"],
             "seconds_since_ok": None if l["last_ok"] is None
             else round(time.time() - l["last_ok"], 1)}
            for l in links.values()
        ],
    }


def timed(fn, *args):
    """Chạy nghiệp vụ và ghi lại thời gian xử lý, để POS cho thấy bán tại chỗ nhanh cỡ nào."""
    t0 = time.perf_counter()
    result = fn(*args)
    result["elapsed_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    return result


@router.post("/api/sale")
def sale(req: StockChange):
    return timed(branch.change_stock, req.product_id, -req.qty, "SALE", req.version, req.request_id)


@router.post("/api/receipt")
def receipt(req: StockChange):
    return timed(branch.change_stock, req.product_id, +req.qty, "RECEIPT", req.version,
                 req.request_id)


@router.post("/api/sale/random")
def random_sales(count: int = 20):
    """Bán nhanh `count` đơn ngẫu nhiên, mỗi đơn 1–3 đơn vị. Dùng khi demo."""
    return branch.random_sales(count)
