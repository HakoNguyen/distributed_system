# infra/

- `compose.yml`: một file cho mọi máy. Profile `broker` (mọi máy) bật `redpanda`: mỗi máy một broker, mã broker =
  `BRANCH_ID`, ba broker thành một cụm (`--seeds` = `BROKER_SEEDS`, cụm chỉ lập khi đủ mọi seed). Profile `core` (chỉ
  máy A) bật `topic-init` (tạo topic một lần, RF = số seed, `write.caching=false`; topic đã có thì kết thúc ngay),
  `console`. `nginx` không thuộc profile nào: chạy ở MỌI máy (vòng 5, cổng vào), image ghim `nginx:1.27.5-alpine`
  (cần ≥ 1.27.3 cho `resolve`). Broker không
  dùng `--mode=dev-container` (bỏ fsync, bật write caching); `--memory=512M` chạy được nhờ `developer_mode` có sẵn trong
  image. Healthcheck chỉ hỏi broker đó (`/v1/status/ready`), không hỏi cả cụm.
  Build context của image Python là gốc repo (`api/Dockerfile` cần `common/`, `web/`, `scripts/`).
  Cổng host đọc từ `BRANCH_PORT`, `REPLICA_PORT`, `NGINX_PORT` (mặc định 8001, 8000, 80).
- `env/may-a.env`, `may-b.env`, `may-c.env`: mẫu `.env` cho từng máy thật, chép thành `.env` ở gốc repo. Có dòng
  `COMPOSE_FILE=infra/compose.yml` nên `docker compose ...` gõ ở gốc repo chạy được không cần `-f`.
  Khối `BROKER_SEEDS`, `KAFKA_BROKERS`, `REPLICA_A/B/C`, `BRANCH_A/B/C`, `GATEWAYS` phải GIỐNG NHAU ở mọi file;
  `REPLICA_*`, `BRANCH_*` dùng IP overlay cho cả ba máy (nginx chạy ở mọi máy, không dùng tên service); `BROKER_HOST` là
  địa chỉ của CHÍNH máy đó; `REPLICA_B` là địa chỉ máy B, không phải máy A. `BRANCH_URL` (vòng 3) cũng riêng từng
  máy: `http://<IP overlay chính máy đó>:8001`, chi nhánh gửi kèm heartbeat để bản sao đối soát. `REPLICA_URLS` cấp
  cho cả `branch_api` (heartbeat) lẫn `replica_api` (gossip, bỏ dòng trùng `NODE_NAME`). Compose kiểm `${VAR:?}` cả ở service thuộc profile đang tắt, nên máy B, C cũng phải có đủ khối này.
- `nginx/default.conf.template`: ảnh nginx tự thay `${REPLICA_A}`... `${BRANCH_C}` (địa chỉ `host:port`),
  `${GATEWAYS}` lúc khởi động. Template luôn có 3 node; chỉ có 2 máy thật thì xem `docs/demo.md` mục 2. Mọi
  `proxy_pass` trỏ vào upstream có `zone` và `server ... resolve` (`resolver 127.0.0.11 valid=5s`): tên phân giải
  động, nginx khởi động được khi node khác chưa chạy (tên chưa có thì đường đó 502). CORS (`*`, `OPTIONS` trả 204) đặt
  ở mức `server`: location nào tự đặt `add_header` thì mất các header đó. `/lb/gateways.json` trả `GATEWAYS`.
- `compose.local.yml` + `env/local-a.env`, `local-b.env`, `local-c.env`: 3 node trên MỘT máy (`make local-up`,
  logic ở `scripts/net.sh`). Mỗi node là project `minigo-<x>`; các node nối nhau qua docker network `minigo-wan`
  (subnet `10.210.0.0/24`) và gọi nhau bằng alias riêng `branch-<x>`, `replica-<x>`, `redpanda-<x>`, KHÔNG bằng tên
  service (trên `minigo-wan` tên service trỏ về cả ba node). Mọi container nối `minigo-wan` có IP cố định
  `${WAN_IP_PREFIX}<n>` (A `10.210.0.1x`, B `.2x`, C `.3x`; n: 1 branch_api, 2 replica_api, 3 relay, 4 sink,
  5 redpanda, 6 nginx, 7 topic-init, 8 console); IP động của mạng chỉ cấp trong `10.210.0.128/25` (`net.sh up`), nên
  không container nào lấy mất IP cố định. `make cut/heal N=<x>` gỡ / nối lại node đó với `minigo-wan`, giữ đúng IP
  và alias (broker giữ kết nối RPC gắn với IP cũ). Cổng vào một máy: A `80`, B `8012`, C `8022`. Broker không publish cổng
  (`ports: !reset []`); relay, sink, `replica_api` có `dns_opt` để tên của container đã tắt hoặc node bị cut báo lỗi
  sau ~1–2 giây thay vì ~8 giây (`replica_api`: luồng gossip). `BRANCH_URL` một máy là `http://branch-<x>:8000`.
  `make config` chạy `scripts/net.sh check` để kiểm cổng, alias, địa chỉ nginx, cụm broker, nginx ở mọi node,
  `GATEWAYS`, IP cố định trên `minigo-wan` ở cả 6 file env. `make pause|unpause|kill|start N=<x> S=<service>`: K13, K14.
- `compose.test.yml`: `test_db` (Postgres trên tmpfs) và `tests` (ảnh `test` của `api/Dockerfile`, mount repo vào
  `/repo`). Dùng qua `make test`.
- Không ghi IP thật hay mật khẩu vào file được commit; `.env` đã nằm trong `.gitignore`.

Quy tắc chung xem CLAUDE.md ở gốc repo.
