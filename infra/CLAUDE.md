# infra/

- `compose.yml`: một file cho mọi máy. Profile `broker` (mọi máy) bật `redpanda`: mỗi máy một broker, mã broker =
  `BRANCH_ID`, ba broker thành một cụm (`--seeds` = `BROKER_SEEDS`, cụm chỉ lập khi đủ mọi seed). Profile `core` (chỉ
  máy A) bật `topic-init` (tạo topic một lần, RF = số seed, `write.caching=false`), `console`, `nginx`. Broker không
  dùng `--mode=dev-container` (bỏ fsync, bật write caching); `--memory=512M` chạy được nhờ `developer_mode` có sẵn trong
  image. Healthcheck chỉ hỏi broker đó (`/v1/status/ready`), không hỏi cả cụm.
  Build context của image Python là gốc repo (`api/Dockerfile` cần `common/`, `web/`, `scripts/`).
  Cổng host đọc từ `BRANCH_PORT`, `REPLICA_PORT`, `NGINX_PORT` (mặc định 8001, 8000, 80).
- `env/may-a.env`, `may-b.env`, `may-c.env`: mẫu `.env` cho từng máy thật, chép thành `.env` ở gốc repo. Có dòng
  `COMPOSE_FILE=infra/compose.yml` nên `docker compose ...` gõ ở gốc repo chạy được không cần `-f`.
  Khối `BROKER_SEEDS`, `KAFKA_BROKERS`, `REPLICA_A/B/C`, `BRANCH_A/B/C` phải GIỐNG NHAU ở mọi file; `BROKER_HOST` là
  địa chỉ của CHÍNH máy đó; `REPLICA_B` là địa chỉ máy B, không phải máy A. `BRANCH_URL` (vòng 3) cũng riêng từng
  máy: `http://<IP overlay chính máy đó>:8001`, chi nhánh gửi kèm heartbeat để bản sao đối soát. `REPLICA_URLS` cấp
  cho cả `branch_api` (heartbeat) lẫn `replica_api` (gossip, bỏ dòng trùng `NODE_NAME`). Compose kiểm `${VAR:?}` cả ở service thuộc profile đang tắt, nên máy B, C cũng phải có đủ khối này.
- `nginx/default.conf.template`: ảnh nginx tự thay `${REPLICA_A}`... `${BRANCH_C}` (địa chỉ `host:port`) lúc khởi
  động. Template luôn có 3 node; chỉ có 2 máy thật thì xem `docs/demo.md` mục 2. Nginx phân giải tên một lần lúc
  khởi động.
- `compose.local.yml` + `env/local-a.env`, `local-b.env`, `local-c.env`: 3 node trên MỘT máy (`make local-up`,
  logic ở `scripts/net.sh`). Mỗi node là project `minigo-<x>`; các node nối nhau qua docker network `minigo-wan`
  (subnet `10.210.0.0/24`) và gọi nhau bằng alias riêng `branch-<x>`, `replica-<x>`, `redpanda-<x>`, KHÔNG bằng tên
  service (trên `minigo-wan` tên service trỏ về cả ba node). `make cut/heal N=<x>` gỡ / nối lại node đó với
  `minigo-wan`, giữ đúng IP và alias (nginx nhớ IP; broker giữ kết nối RPC gắn với IP cũ). Broker không publish cổng
  (`ports: !reset []`); relay, sink, `replica_api` có `dns_opt` để tên của container đã tắt hoặc node bị cut báo lỗi
  sau ~1–2 giây thay vì ~8 giây (`replica_api`: luồng gossip). `BRANCH_URL` một máy là `http://branch-<x>:8000`.
  `make config` chạy `scripts/net.sh check` để kiểm cổng, alias, địa chỉ nginx và cấu hình cụm broker ở cả 6 file env.
- `compose.test.yml`: `test_db` (Postgres trên tmpfs) và `tests` (ảnh `test` của `api/Dockerfile`, mount repo vào
  `/repo`). Dùng qua `make test`.
- Không ghi IP thật hay mật khẩu vào file được commit; `.env` đã nằm trong `.gitignore`.

Quy tắc chung xem CLAUDE.md ở gốc repo.
