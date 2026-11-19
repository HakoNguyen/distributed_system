# api/

Một image, bốn tiến trình (`infra/compose.yml`). Mục cần đọc: `docs/api.md`, `docs/db.md`.

- `main.py`: tạo app theo `ROLE`. `branch`: gắn `routers/branch.py`, tạo tồn ban đầu, chạy luồng heartbeat.
  `replica`: gắn `routers/replica.py` và header `X-Served-By`.
- `routers/<role>.py`: mỏng, gọi một hàm trong `services/<role>.py`.
- `services/branch.py`: tồn, sổ cái, outbox. `services/replica.py`: `apply_event`, heartbeat, truy vấn dashboard.
- `workers/relay.py` (`python -m workers.relay`), `workers/sink.py` (`python -m workers.sink`) chạy thành container
  riêng; `workers/heartbeat.py` là luồng nền trong `branch_api`.
- Trong container, `api/` nằm ở `/app`, cạnh `common/`, `web/`, `tre.sh`. Import theo dạng
  `from common.config import ...`, `from services import branch`.

Quy tắc chung xem CLAUDE.md ở gốc repo.
