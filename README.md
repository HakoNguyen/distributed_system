# MiniGo: hệ thống kho phân tán trên 2–3 máy thật

Demo cho môn Các hệ thống phân tán. Một chuỗi cửa hàng tiện lợi có nhiều chi nhánh; mỗi chi nhánh bán hàng
trên CSDL của chính nó, trụ sở xem tồn kho toàn chuỗi qua nhiều bản sao trung tâm.
Đặc tả và kiến trúc: [docs/spec.md](docs/spec.md). Kịch bản demo: [docs/demo.md](docs/demo.md).
Tiến độ và thứ tự làm: [docs/plan.md](docs/plan.md).

| Tính chất | Cơ chế | Kịch bản |
|---|---|---|
| Trong suốt vị trí | Nginx là cổng vào duy nhất, chia yêu cầu cho các bản sao | K2 |
| Chịu lỗi, failover | Mỗi máy một bản sao trung tâm; nginx bỏ qua bản sao chết | K3 |
| Tự phục hồi | Outbox giữ sự kiện, Redpanda giữ vị trí đọc, nginx tự thử lại | K4 |
| Chịu lỗi broker | Cụm 3 broker Raft, RF=3; mất đa số thì POS, dashboard báo "đồng bộ dừng", quầy vẫn bán | K7a–K7c |
| Bản sao tự vá lẫn nhau | Gossip: so dấu vân tay mỗi 10 giây, kéo snapshot, merge từng ô theo `movement_id` | K8 |
| Phục hồi từ nguồn sự thật | Mất broker quá 15 giây thì bản sao đối soát thẳng với chi nhánh qua API | K9 |
| Đồng bộ dữ liệu | Sự kiện đi qua Redpanda tới mọi bản sao; so bằng dấu vân tay | K1, K4 |
| Chịu được độ trễ mạng | Bán tại chỗ, đồng bộ bất đồng bộ; đo RTT trực tiếp | K5 |

## Kiến trúc

Mọi máy chạy cùng một file compose; máy nào chạy gì do file `.env` quyết định.

| Container | Cổng | Máy | Vai trò |
|---|---|---|---|
| `branch_db` | | mọi máy | PostgreSQL của chi nhánh: tồn, sổ cái, outbox |
| `branch_api` | 8001 | mọi máy | FastAPI `ROLE=branch`: màn hình POS, bán, nhập; gửi heartbeat |
| `relay` | | mọi máy | Đẩy outbox lên cụm Redpanda, ghi trạng thái gửi cho POS |
| `replica_db` | | mọi máy | PostgreSQL của bản sao: bảng tồn toàn chuỗi dựng từ sự kiện |
| `replica_api` | 8000 | mọi máy | FastAPI `ROLE=replica`: dashboard, nhận heartbeat; gossip với bản sao khác, đối soát với chi nhánh khi mất broker |
| `sink` | | mọi máy | Đọc Redpanda, áp sự kiện vào `replica_db`; kiểm broker mỗi 5 giây cho dashboard |
| `redpanda` | 19092, 33145 | mọi máy | Một broker (tương thích Kafka); ba máy thành cụm 3 broker, topic RF=3 |
| `topic-init` | | máy A | Tạo topic một lần khi cụm đủ broker, rồi thoát |
| `console` | 8080 | máy A | Redpanda Console: xem topic, từng sự kiện |
| `nginx` | 80 | máy A | Cổng vào duy nhất, chia tải các bản sao |

```
docs/      đặc tả, CSDL, API, kịch bản demo, kế hoạch (nguồn sự thật)
db/        SQL khởi tạo: product.sql (dùng chung), branch.sql, replica.sql
common/    cấu hình, pool CSDL, model
api/       main.py, routers/ (mỏng), services/ (SQL và quy tắc), workers/ (relay, sink, heartbeat, gossip)
web/       pos.html, dashboard.html (HTML + JS thuần, không build)
infra/     compose.yml, compose.local.yml (3 node một máy), compose.test.yml, nginx/, env/ (máy thật, local)
tests/     pytest trên PostgreSQL thật, chạy trong container
scripts/   tre.sh: giả lập độ trễ mạng trong container; net.sh: 3 node một máy, cut/heal
```

## Chạy

Cần Docker Desktop và một mạng overlay (Tailscale hoặc ZeroTier) nối các máy; chi tiết ở
[docs/demo.md](docs/demo.md) mục 1.

1. Trên mỗi máy, chép file env của máy đó thành `.env` ở gốc repo, rồi điền IP overlay thật:
   `cp infra/env/may-a.env .env` (máy B: `may-b.env`, máy C: `may-c.env`).
2. Trên cả ba máy: `make up` (cụm broker lập khi đủ ba máy). Đã chạy bản một broker trước đó thì `make reset`.
3. Trên máy A mở http://localhost/ (dashboard qua nginx), http://localhost:8001 (POS CN1).

| Lệnh | Việc làm |
|---|---|
| `make up` | Build và chạy mọi container của máy này |
| `make down` | Dừng, giữ dữ liệu |
| `make reset` | Xóa dữ liệu và dựng lại từ đầu |
| `make ps`, `make logs S=relay` | Trạng thái, log |

**Chỉ có một máy:** `make local-up` dựng 3 node (A, B, C) trên cùng máy, nối nhau qua docker network `minigo-wan`
thay cho mạng overlay; không cần `.env`. Mở http://localhost/ (nginx), POS CN1/CN2/CN3 ở cổng 8001/8011/8021,
dashboard bản sao A/B/C ở 8000/8010/8020. `make cut N=b` rút mạng node B, `make heal N=b` cắm lại;
`make local-down`, `make local-reset` (bắt buộc một lần khi lên từ bản một broker). Dừng một broker cho K7:
`docker stop minigo-b-redpanda-1`. Chi tiết: [docs/demo.md](docs/demo.md) mục 3, phần "Chạy trên một máy".

Không có `make` thì dùng thẳng `docker compose up -d --build`: file `.env` đã chỉ tới `infra/compose.yml`
qua biến `COMPOSE_FILE`, nên mọi lệnh `docker compose ...` gõ từ gốc repo đều chạy được.
Tài liệu API tự sinh: http://localhost:8001/docs (chi nhánh), http://localhost:8000/docs (bản sao).

## Phát triển

Mỗi vòng trong [docs/plan.md](docs/plan.md) đi bốn bước bằng lệnh dự án của Claude Code:
`/plan-task` → `/test-first` → `/implement` → `/self-review`.

| Lệnh | Việc làm |
|---|---|
| `make test` | pytest trong container, trên CSDL test riêng; chỉ cần Docker. Một thư mục: `make test T=tests/replica` |
| `make config` | Kiểm tra file compose hợp lệ với env mẫu; với 3 node một máy: cổng không trùng, đủ alias, nginx đủ địa chỉ; cụm 3 broker ở mọi file env; `REPLICA_URLS`, `BRANCH_URL` cho gossip và đối soát |
| `make check` | `config` + `test`; chạy trước khi báo xong một vòng |

Quy ước code và làm việc với AI: [CLAUDE.md](CLAUDE.md). Quy ước kiểm thử: [docs/tests.md](docs/tests.md).
