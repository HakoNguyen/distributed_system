# infra/

- `compose.yml`: một file cho mọi máy. `COMPOSE_PROFILES=core` (chỉ máy A) bật thêm `redpanda`, `console`, `nginx`.
  Build context của image Python là gốc repo (`api/Dockerfile` cần `common/`, `web/`, `scripts/`).
- `env/may-a.env`, `may-b.env`, `may-c.env`: mẫu `.env` cho từng máy, chép thành `.env` ở gốc repo. Có dòng
  `COMPOSE_FILE=infra/compose.yml` nên `docker compose ...` gõ ở gốc repo chạy được không cần `-f`.
  IP các máy (`IP_A`, `IP_B`, `IP_C`) phải GIỐNG NHAU ở mọi file; `IP_B` là IP của máy B, không phải máy A.
- `nginx/default.conf.template`: ảnh nginx tự thay `${IP_B}`, `${IP_C}` lúc khởi động. Thêm máy C thì bỏ `#` ở các
  dòng `[MÁY C]`.
- `compose.test.yml`: `test_db` (Postgres trên tmpfs) và `tests` (ảnh `test` của `api/Dockerfile`, mount repo vào
  `/repo`). Dùng qua `make test`.
- Không ghi IP thật hay mật khẩu vào file được commit; `.env` đã nằm trong `.gitignore`.

Quy tắc chung xem CLAUDE.md ở gốc repo.
