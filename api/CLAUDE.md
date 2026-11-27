# api/

Một image, bốn tiến trình (`infra/compose.yml`). Mục cần đọc: `docs/api.md`, `docs/db.md`.

- `main.py`: tạo app theo `ROLE`. `branch`: gắn `routers/branch.py`, tạo tồn ban đầu, chạy luồng heartbeat và luồng
  phục hồi (`workers/recovery.py`, vòng 6).
  `replica`: gắn `routers/replica.py` và header `X-Served-By`.
- `routers/<role>.py`: mỏng, gọi một hàm trong `services/<role>.py`.
- `services/branch.py`: tồn, sổ cái, outbox; ghi hộ (vòng 6, PT-14): trạng thái `recovery` (ONLINE / RECOVERING, trong
  bộ nhớ), `require_online` (router gọi trước bán, nhập: 503 `branch_recovering`), `next_recovery_state` (hàm thuần),
  `collect_handoffs`, `apply_handoffs` (qua `change_stock`), `recovery_once(pull, ack, replicas)` (bắt mọi lỗi).
  `services/replica.py`: `apply_event`, heartbeat, truy vấn dashboard; ghi hộ `store_handoff`, `query_handoff`,
  `record_handoff_ack`.
- `workers/relay.py` (`python -m workers.relay`), `workers/sink.py` (`python -m workers.sink`) chạy thành container
  riêng; `workers/heartbeat.py` là luồng nền trong `branch_api`; `workers/gossip.py` (gossip với bản sao khác, đối
  soát với chi nhánh khi mất broker, `view_loop` kéo góc nhìn của bản sao khác cho bộ phát hiện lỗi) là luồng nền
  trong `replica_api`; `workers/recovery.py` (vòng 6) là luồng nền trong `branch_api`: mỗi 2 giây kéo
  `GET /api/handoff` của mọi bản sao song song, gọi `recovery_once`, ack sau khi đã commit. Luật merge snapshot duy
  nhất: `merge_cells`. Trạng thái chi nhánh: `branch_state`, `majority_state` (PT-13).
- Trong container, `api/` nằm ở `/app`, cạnh `common/`, `web/`, `tre.sh`. Import theo dạng
  `from common.config import ...`, `from services import branch`.

Quy tắc chung xem CLAUDE.md ở gốc repo.
