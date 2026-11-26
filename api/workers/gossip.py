"""Kênh trực tiếp giữa các bản sao (gossip) và đối soát với chi nhánh khi mất broker (vòng 3); kéo góc nhìn của
bản sao khác về các chi nhánh cho bộ phát hiện lỗi (vòng 5, view_loop).

Chạy thành luồng nền trong replica_api (api/main.py khởi động): mỗi bản sao khác một luồng gossip, để một
bản sao chết không làm chậm các bản khác, thêm một luồng đối soát. Mọi lời gọi mạng nằm ở đây và xong TRƯỚC
khi services/replica.py mở transaction để ghi. Luật merge chung với sink: merge_cells (PT-10).
"""
import threading
import time

import httpx

from common.config import GOSSIP_EVERY_S, NODE_NAME, PEER_TIMEOUT_S, PEERS, RECONCILE_EVERY_S, VIEWS_EVERY_S
from common.db import pool
from services import replica

TAG = f"[gossip {NODE_NAME}]"


def _error(peer: str, channel: str, e: Exception) -> None:
    try:
        replica.record_peer_error(peer, channel, f"{type(e).__name__}: {e}"[:200])
    except Exception as db_error:  # CSDL của chính mình lỗi: chỉ ghi log, vòng sau thử lại
        print(f"{TAG} Không ghi được lỗi gọi {peer} ({db_error})")


def gossip_loop(name: str, url: str) -> None:
    """Mỗi GOSSIP_EVERY_S giây: so dấu vân tay với bản sao `name`; lệch thì kéo cả snapshot (60 ô) và
    chỉ vá ô vẫn thiếu sau 2 lần kiểm liên tiếp (pick_stale), để sink (kênh chính) có thời gian làm việc."""
    client = httpx.Client(timeout=PEER_TIMEOUT_S)
    pending: dict[tuple[int, int], int] = {}  # ô bản sao kia đi trước ở lần kiểm trước -> movement_id lúc đó
    while True:
        try:
            r = client.get(f"{url}/api/digest")
            r.raise_for_status()
            with pool.connection() as conn:
                same = r.json()["fingerprint"] == replica.query_digest(conn)["fingerprint"]
            patch = []
            if same:
                pending = {}
            else:
                r = client.get(f"{url}/api/snapshot")
                r.raise_for_status()
                with pool.connection() as conn:
                    local = replica.query_snapshot(conn)
                patch, pending = replica.pick_stale(r.json()["cells"], local, pending)
            # Mạng xong rồi mới mở transaction ghi
            n = replica.merge_replica_snapshot(name, patch)
            if n:
                print(f"{TAG} Vá {n} ô nhờ bản sao {name}")
        except Exception as e:  # bản sao kia chết, mất mạng, trả dữ liệu hỏng...
            pending = {}  # "2 lần kiểm liên tiếp" tính lại từ đầu
            _error(name, "gossip", e)
        time.sleep(GOSSIP_EVERY_S)


def reconcile_loop() -> None:
    """Mỗi RECONCILE_EVERY_S giây: mất broker quá 15 giây thì kéo snapshot thẳng từ chi nhánh còn sống
    (nguồn sự thật). Chỉ đọc chi nhánh qua HTTP, không ghi về (PT-07)."""
    client = httpx.Client(timeout=PEER_TIMEOUT_S)
    while True:
        try:
            with pool.connection() as conn:
                targets = replica.reconcile_targets(conn)
        except Exception as e:
            print(f"{TAG} Không đọc được trạng thái để đối soát ({e})")
            targets = []
        for t in targets:
            peer = f"CN{t['branch_id']}"
            try:
                r = client.get(f"{t['branch_url']}/api/snapshot")
                r.raise_for_status()
                n = replica.merge_branch_snapshot(t["branch_id"], r.json())
                if n:
                    print(f"{TAG} Đối soát {peer}: vá {n} ô")
            except Exception as e:
                _error(peer, "reconcile", e)
        time.sleep(RECONCILE_EVERY_S)


def view_loop(name: str, url: str) -> None:
    """Mỗi VIEWS_EVERY_S giây: kéo góc nhìn của bản sao `name` về các chi nhánh (vòng 5, PT-13). Gọi lỗi thì không
    ghi gì: góc nhìn cũ tự hết hạn sau VIEW_STALE_S giây và không còn được tính vào đa số."""
    client = httpx.Client(timeout=PEER_TIMEOUT_S)
    while True:
        try:
            r = client.get(f"{url}/api/views")
            r.raise_for_status()
            replica.record_peer_view(name, r.json())  # mạng xong rồi mới mở transaction ghi
        except ValueError as e:  # dữ liệu hỏng (JSON lỗi, sai model, sai tên bản sao): ghi log; lỗi mạng thì im lặng
            print(f"{TAG} Bỏ góc nhìn hỏng từ {name} ({e})"[:300])
        except Exception:
            pass  # bản sao kia chết hoặc mất mạng: đã thấy ở cột gossip (sync_peer)
        time.sleep(VIEWS_EVERY_S)


def start() -> None:
    for name, url in PEERS:
        threading.Thread(target=gossip_loop, args=(name, url), daemon=True).start()
        threading.Thread(target=view_loop, args=(name, url), daemon=True).start()
    threading.Thread(target=reconcile_loop, daemon=True).start()
    print(f"{TAG} Gossip với {[n for n, _ in PEERS]} mỗi {GOSSIP_EVERY_S} giây, góc nhìn mỗi {VIEWS_EVERY_S} giây;"
          " đối soát khi mất broker")
