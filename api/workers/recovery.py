"""Phục hồi (vòng 6, PT-14): chi nhánh tự kéo ghi hộ từ MỌI bản sao, áp theo thứ tự, báo kết quả, đổi ONLINE/RECOVERING.

Chạy thành luồng nền trong branch_api (api/main.py khởi động), mỗi RECOVERY_EVERY_S giây. Mọi lời gọi mạng nằm ở đây
và ngoài transaction; services/branch.py: recovery_once áp (mỗi lượt một transaction) rồi mới gọi `ack`.
Bản sao không ghi vào CSDL chi nhánh (PT-07): chi nhánh GET để kéo, POST ack để bản sao tự sửa bảng của nó.
"""
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import httpx

from common.config import BRANCH_ID, PEER_TIMEOUT_S, RECOVERY_EVERY_S, REPLICAS
from services import branch

TAG = f"[recovery cn{BRANCH_ID}]"


def recovery_loop() -> None:
    urls = dict(REPLICAS)
    client = httpx.Client(timeout=PEER_TIMEOUT_S)
    # Kéo các bản sao song song: một bản sao chết (timeout) không kéo dài cả vòng quá RECOVERY_STALE_S
    pool = ThreadPoolExecutor(max_workers=max(1, len(urls)))

    def fetch(name: str) -> dict | Exception:
        try:
            r = client.get(f"{urls[name]}/api/handoff", params={"branch_id": BRANCH_ID})
            r.raise_for_status()
            return r.json()
        except Exception as e:
            return e

    def ack(name: str, payload: dict) -> None:
        client.post(f"{urls[name]}/api/handoff/ack", json=payload).raise_for_status()

    last = None
    while True:
        try:
            got = dict(zip(urls, pool.map(fetch, urls)))

            def pull(name: str) -> dict:
                if isinstance(got[name], Exception):
                    raise got[name]
                return got[name]

            branch.recovery_once(pull, ack, list(urls))  # tự bắt mọi lỗi
            now = (branch.recovery["state"], branch.recovery["incomplete"])
            if now != last:
                print(f"{TAG} {now[0]}{' (chưa gom đủ: ' + ','.join(branch.recovery['unreachable']) + ')' if now[1] else ''}")
                last = now
        except Exception as e:  # lớp cuối: luồng không bao giờ dừng vì một lần lỗi
            print(f"{TAG} Lỗi vòng phục hồi ({type(e).__name__}: {e})"[:300])
        time.sleep(RECOVERY_EVERY_S)


def start() -> None:
    threading.Thread(target=recovery_loop, daemon=True).start()
    print(f"{TAG} Khởi động ở RECOVERING; kéo ghi hộ từ {[n for n, _ in REPLICAS]} mỗi {RECOVERY_EVERY_S} giây")
