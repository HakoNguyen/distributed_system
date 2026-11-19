"""Heartbeat: chi nhánh báo "tôi còn sống" tới MỌI bản sao trung tâm, mỗi 5 giây.

Chạy thành luồng nền bên trong api của chi nhánh (api/main.py khởi động).
"""
import threading
import time

import httpx

from common.config import BRANCH_ID, BRANCH_NAME, HEARTBEAT_EVERY_S, REPLICAS
from services.branch import outbox_backlog

# Trạng thái đường nối tới từng bản sao, hiện lên màn hình POS (GET /api/status).
links = {name: {"name": name, "url": url, "ok": False, "rtt_ms": None,
                "last_ok": None, "error": "chưa gửi heartbeat nào"}
         for name, url in REPLICAS}


def heartbeat_loop(name: str, url: str) -> None:
    # Dùng lại một client: tạo client mới mỗi lần tốn vài chục ms, làm sai số đo RTT.
    client = httpx.Client(timeout=2.0)
    link = links[name]
    while True:
        try:
            backlog = outbox_backlog()["n"]
            t0 = time.perf_counter()
            client.post(
                f"{url}/api/heartbeat",
                json={
                    "branch_id": BRANCH_ID,
                    "branch_name": BRANCH_NAME,
                    "node_time_ms": int(time.time() * 1000),  # giờ máy chi nhánh
                    "outbox_backlog": backlog,
                    # RTT đo được ở lần trước, gửi kèm để trung tâm hiển thị
                    "rtt_ms": link["rtt_ms"],
                },
            ).raise_for_status()
            # RTT = thời gian một vòng đi và về của heartbeat. Bật Clumsy / tc
            # để thêm độ trễ là con số này tăng theo ngay.
            link.update(ok=True, last_ok=time.time(), error=None,
                        rtt_ms=round((time.perf_counter() - t0) * 1000))
        except Exception as e:  # mất mạng, bản sao tắt... chỉ ghi nhận rồi thử lại
            link.update(ok=False, error=type(e).__name__)
        time.sleep(HEARTBEAT_EVERY_S)


def start() -> None:
    """Mỗi bản sao một luồng riêng, để một bản sao mất mạng không làm chậm các bản khác."""
    for name, url in REPLICAS:
        threading.Thread(target=heartbeat_loop, args=(name, url), daemon=True).start()
