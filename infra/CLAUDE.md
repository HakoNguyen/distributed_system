# infra/

- `compose.yml`: một file cho mọi máy. `COMPOSE_PROFILES=core` (chỉ máy A) bật thêm `redpanda`, `console`, `nginx`.
  Build context của image Python là gốc repo (`api/Dockerfile` cần `common/`, `web/`, `scripts/`).
  Cổng host đọc từ `BRANCH_PORT`, `REPLICA_PORT`, `NGINX_PORT` (mặc định 8001, 8000, 80).
- `env/may-a.env`, `may-b.env`, `may-c.env`: mẫu `.env` cho từng máy thật, chép thành `.env` ở gốc repo. Có dòng
  `COMPOSE_FILE=infra/compose.yml` nên `docker compose ...` gõ ở gốc repo chạy được không cần `-f`.
  Khối `IP_A`, `REPLICA_A/B/C`, `BRANCH_A/B/C` phải GIỐNG NHAU ở mọi file; `REPLICA_B` là địa chỉ máy B, không
  phải máy A. Compose kiểm `${VAR:?}` cả ở service thuộc profile đang tắt, nên máy B, C cũng phải có đủ khối này.
- `nginx/default.conf.template`: ảnh nginx tự thay `${REPLICA_A}`... `${BRANCH_C}` (địa chỉ `host:port`) lúc khởi
  động. Template luôn có 3 node; chỉ có 2 máy thật thì xem `docs/demo.md` mục 2. Nginx phân giải tên một lần lúc
  khởi động.
- `compose.local.yml` + `env/local-a.env`, `local-b.env`, `local-c.env`: 3 node trên MỘT máy (`make local-up`,
  logic ở `scripts/net.sh`). Mỗi node là project `minigo-<x>`; các node nối nhau qua docker network `minigo-wan`
  (subnet `10.210.0.0/24`) và gọi nhau bằng alias riêng `branch-<x>`, `replica-<x>`, `redpanda-a`, KHÔNG bằng tên
  service (trên `minigo-wan` tên service trỏ về cả ba node). `make cut/heal N=<x>` gỡ / nối lại node đó với
  `minigo-wan`, giữ đúng IP và alias. `make config` chạy `scripts/net.sh check` để kiểm cổng, alias, địa chỉ nginx.
- `compose.test.yml`: `test_db` (Postgres trên tmpfs) và `tests` (ảnh `test` của `api/Dockerfile`, mount repo vào
  `/repo`). Dùng qua `make test`.
- Không ghi IP thật hay mật khẩu vào file được commit; `.env` đã nằm trong `.gitignore`.

Quy tắc chung xem CLAUDE.md ở gốc repo.
