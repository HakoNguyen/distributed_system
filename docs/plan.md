# Kế hoạch triển khai

File này cho biết dự án đang ở đâu và việc tiếp theo là gì. Đọc mục 1 trước khi làm bất cứ việc gì.
Mục tiêu trước mắt: xử lý hai câu hỏi của thầy (mục 3), trên **một máy**.

## 1. Tiến độ

**Vòng tiếp theo: vòng 4** (sau khi vòng 3 được merge). Mỗi lần chỉ làm một vòng, đúng thứ tự: vòng sau dựa trên hạ tầng của vòng trước.

| Vòng | Phạm vi | Nhánh | Việc | Quy tắc | Kịch bản | Trạng thái |
|---|---|---|---|---|---|---|
| 0 | khung | `base/restructure-workflow` | Gộp về một bản theo cấu trúc mới; quy trình 4 bước; hạ tầng test, 5 test nền | PT-02, 04, 05, 08, 09 | K1, K6 trên 1 node | xong, đã merge (PR #1) |
| 1 | `infra` | `infra/local-multi-node` | Mô phỏng 3 máy trên một máy, `make cut/heal` | — | K1–K6 trên 3 node | xong, đã merge (PR #2) |
| 2 | `infra`, `branch`, `replica`, `web` | `broker/redpanda-cluster` | Cụm 3 broker; trạng thái đồng bộ trên POS và dashboard | PT-03, PT-06, PT-11 | K7a, K7b, K7c | xong, đã merge (PR #3); 16 test, K1–K7c đạt trên 3 node một máy |
| 3 | `replica`, `branch`, `web` | `replica/gossip-reconcile` | Gossip giữa bản sao; đối soát với chi nhánh | PT-04, PT-05, PT-07, PT-10 | K8, K9 | đã code (22/11/2026); `make check` xanh (43 test); K1–K9 đạt trên 3 node một máy; chờ commit |
| 4 | `web` | `web/sync-dashboard` | Topology sống, đọc đơn điệu, truy vết sự kiện, POS | — | chạy tay K1–K9 | chưa làm |
| 5 | `infra`, `docs` | `infra/production-local` | Standby đồng bộ cho CSDL chi nhánh; vệ sinh vận hành; giám sát (tuỳ chọn); kiến trúc mục tiêu production trên giấy | PT-12 | K10a, K10b | chưa làm |
| 6 | `replica`, `scripts`, `docs` | `chore/hardening` | `dead_letter`, `scripts/chaos-check.sh`, chốt tài liệu | PT-06 | `chaos-check.sh` | chưa làm |

Xong một vòng thì sửa cột "Trạng thái" ở bảng này, dòng "Vòng tiếp theo" ở trên, và các bảng trạng thái trong
[tests.md](tests.md).

## 2. Cách làm việc

Mỗi vòng đi đủ bốn bước bằng lệnh của dự án (`.claude/commands/`):

1. `/plan-task <vòng>`: đọc tài liệu, lập kế hoạch chi tiết, đề xuất tên mới, liệt kê test và giả định,
   **dừng chờ duyệt**.
2. `/test-first <vòng>`: tạo nhánh, ghi tên đã duyệt vào `docs/`, viết test; chạy và xác nhận test đỏ vì thiếu
   chức năng.
3. `/implement <vòng>`: viết code tới khi `make check` xanh; dựng lên và chạy tay kịch bản của vòng.
4. `/self-review`: đối chiếu checklist `.github/pull_request_template.md`, báo cáo; không tự sửa ở bước này. Đạt
   hết thì `git add` các file của vòng và viết commit message; **người dùng tự commit và push** (CLAUDE.md mục Git).

Tài liệu đi trước code: tên mới (bảng, endpoint, trường sự kiện, biến môi trường) được duyệt ở `/plan-task` và ghi
vào `docs/` ở `/test-first`, trước khi viết code xử lý.

## 3. Hai câu hỏi của thầy

### 3.1. Redpanda gặp sự cố thì xử lý thế nào?

**Hiện trạng (sau vòng 2).** Cụm 3 broker, mỗi máy một broker, topic RF=3, write caching và bỏ-fsync đã tắt.

| Khi Redpanda chết | Đã có chưa |
|---|---|
| Quầy vẫn bán, outbox giữ sự kiện | Có |
| Bật lại: relay gửi bù, sink đọc tiếp từ offset; container tự khởi động lại | Có |
| Dashboard báo "đồng bộ dừng từ HH:MM:SS" tách khỏi "còn sống" (heartbeat HTTP thẳng); POS báo "Gửi lên Redpanda: lỗi từ HH:MM:SS" | Có (vòng 2, K7b) |
| Mất 1/3 broker: tự bầu leader mới, không mất sự kiện | Có (vòng 2, K7a) |
| Mất dữ liệu Redpanda: sự kiện bản sao chưa kịp đọc mất hẳn, dấu vân tay lệch mãi | Có (vòng 3): số tồn dựng lại bằng gossip (K8) hoặc đối soát (K9); chỉ mất nhật ký các sự kiện đó |
| `dev-container` bật write caching và bỏ fsync: `acks=all` chưa chắc đã ghi đĩa | Đã sửa (vòng 2): bỏ `--mode=dev-container`, `--unsafe-bypass-fsync=false`, `write_caching_default=false` |

**Trả lời theo ba tầng.**
1. **Phòng**: cụm 3 broker, mỗi node một broker, topic RF=3. Raft: mất 1/3 vẫn còn đa số, tự bầu leader mới,
   producer và consumer tự chuyển (vòng 2).
2. **Chống** (mất đa số broker): quầy bán bình thường; dashboard ghi rõ "Đồng bộ dừng từ HH:MM:SS"; bản sao đối
   soát thẳng với chi nhánh (vòng 3).
3. **Phục hồi**: tự động như K4. Mất dữ liệu broker thì bản sao dựng lại từ sổ cái chi nhánh hoặc từ bản sao khác.

> Câu chốt: "Redpanda là đường nhanh, không phải nguồn sự thật. Nguồn sự thật là sổ cái từng chi nhánh. Broker
> chết thì chỉ chậm, không mất; mất dữ liệu broker thì dựng lại từ sổ cái."

### 3.2. ReplicaA và ReplicaB trao đổi thông tin bằng cơ chế gì?

**Trước vòng 3: hai bản sao không gọi nhau trực tiếp.** Mỗi bản sao một consumer group (`replica-A`, `replica-B`),
cùng đọc một log có thứ tự trong từng phân hoạch, áp bằng hàm tất định, lũy đẳng → cùng trạng thái (nhân bản máy
trạng thái qua log chung; giao tiếp gián tiếp, bền, bất đồng bộ). Việc so dấu vân tay do trình duyệt làm.

**Sau vòng 3: ba kênh, cùng một luật merge (PT-10).**

```
 Kênh 1 (chính, giữ nguyên):  Chi nhánh ─outbox/relay─▶ Redpanda ─┬▶ sink A ▶ Replica A
                                                                  └▶ sink B ▶ Replica B
 Kênh 2 (gossip):             Replica A ◀── trao digest, merge snapshot ──▶ Replica B
 Kênh 3 (đối soát):           Replica X ── GET /api/snapshot ──▶ Chi nhánh (nguồn sự thật)
```

Luật "movement_id lớn hơn thắng" áp cho **từng ô** (chi nhánh, mã hàng): giao hoán, kết hợp, lũy đẳng (CRDT dạng
trạng thái, LWW-register với phiên bản do chính chi nhánh cấp). Thứ tự nhận, nhận trùng, đến từ kênh nào đều hội
tụ. So theo từng ô chứ không theo từng chi nhánh, vì sự kiện của một chi nhánh nằm rải trên nhiều phân hoạch và
`movement_id` có thể có lỗ.

## 4. Mẫu file cho một vòng

Mỗi vòng chỉ tạo hoặc sửa các chỗ sau; file nào ngoài mẫu thì nêu lý do ở `/plan-task`.

| Việc | Vị trí |
|---|---|
| Tên mới, quy tắc mới (PT-xx), kịch bản mới (Kxx) | `docs/spec.md`, `docs/db.md`, `docs/api.md`, `docs/demo.md` |
| Bảng, cột mới | `db/*.sql` (sửa xong `make reset`) |
| Model Pydantic | `common/models.py` |
| SQL và quy tắc | `api/services/<module>.py` |
| Endpoint mỏng | `api/routers/<module>.py` |
| Tiến trình, luồng nền | `api/workers/` |
| Container, mạng, nginx, env | `infra/` |
| Lệnh tiện dụng | `Makefile`, `scripts/` |
| Giao diện | `web/pos.html`, `web/dashboard.html` |
| Test, hàm dựng dữ liệu | `tests/<module>/`, `tests/fixtures.py` |
| Tiến độ | `docs/plan.md` mục 1, `docs/tests.md` |

## 5. Chi tiết từng vòng

Docker hiện có 10,7 GB, stack `market-*` đang chiếm ~6 GB. Ba node MiniGo (3 broker × ~1 GB, 6 Postgres,
12 tiến trình Python) cần ~4–5 GB: **tắt stack market-\* trước khi chạy 3 node**.
Đo ở vòng 1 (1 broker, 21 container): khoảng 1,1 GB. Đo ở vòng 2 (3 broker `--memory=512M`, 23 container): khoảng 1,23 GB,
mỗi broker ~130 MB.

### Vòng 1 – Mô phỏng 3 máy trên một máy (`infra/local-multi-node`)

Mỗi "máy" là một compose project (`minigo-a`, `minigo-b`, `minigo-c`) chạy cùng `infra/compose.yml`. "Mạng overlay"
là một docker network chung `minigo-wan`. "Rút mạng máy B" là tách mọi container của B khỏi `minigo-wan`: B vẫn chạy
bình thường bên trong, chỉ mất liên lạc với máy khác, đúng như rút dây mạng.

| Việc | File |
|---|---|
| Cổng host đọc từ env (`BRANCH_PORT`, `REPLICA_PORT`) để 3 node không đụng cổng | `infra/compose.yml` |
| File ghép thêm cho chế độ một máy: gắn các service liên máy vào `minigo-wan` với alias riêng từng node (`branch-b`, `replica-b`, `redpanda-b`). Chế độ nhiều máy thật không dùng file này | `infra/compose.local.yml` (mới) |
| Nginx đọc địa chỉ đầy đủ `host:port` (`REPLICA_A/B/C`, `BRANCH_A/B/C`) thay vì ghép `${IP_B}:8000`. Máy thật: `100.64.0.2:8000`; một máy: `replica-b:8000` | `infra/nginx/default.conf.template`, `infra/env/may-*.env` |
| Env cho 3 node trên một máy | `infra/env/local-a.env`, `local-b.env`, `local-c.env` (mới) |
| Lệnh: `make local-up`, `local-down`, `local-reset`, `make cut N=b`, `make heal N=b` | `Makefile`, `scripts/net.sh` (mới) |
| Mục "Chạy trên một máy"; K3/K4 dùng `make cut/heal` thay cho rút Wi-Fi | `docs/demo.md` |

Test viết trước: `make config` kiểm cả 3 env local (cổng không trùng, mỗi node đủ alias, nginx đủ địa chỉ).
Xong khi: K1–K6 chạy được với 3 node trên một máy; `make cut N=b` cho đúng hiện tượng K3, `make heal N=b` cho K4.

### Vòng 2 – Redpanda chịu lỗi (`broker/redpanda-cluster`)

| Việc | File |
|---|---|
| Mỗi node chạy một broker (A, B, C = broker 1, 2, 3 = `BRANCH_ID`; `--seeds` trỏ cả ba). `KAFKA_BROKERS` liệt kê cả ba | `infra/compose.yml`, `infra/env/*` |
| Topic RF=3, tạo ở một chỗ (service `topic-init` chạy `rpk topic create` một lần) thay vì `common/kafka.py`. Tắt write caching để `acks=all` nghĩa là đã ghi đĩa trên đa số | `infra/compose.yml`, xoá `common/kafka.py` |
| Relay ghi `relay_status` (lần gửi được cuối, lỗi cuối); POS hiện "Gửi lên Redpanda: lỗi từ HH:MM:SS" | `db/branch.sql`, `api/workers/relay.py`, `api/services/branch.py`, `api/routers/branch.py`, `web/pos.html` |
| Sink kiểm tra broker mỗi 5 giây, ghi `broker_ok`, `broker_lost_at`, `lag` vào `sink_stats`; dashboard tách "đồng bộ dừng" khỏi "chi nhánh còn sống" | `db/replica.sql`, `api/workers/sink.py`, `api/services/replica.py`, `web/dashboard.html` |
| Relay `enable.idempotence=True` để không đảo thứ tự khi gửi lại | `api/workers/relay.py` |

Test viết trước: tách phần ghi trạng thái của relay và sink thành hàm trong `services/`, test ghi đúng mốc mất / có
lại kết nối (PT-11); tách phần đánh dấu `sent_at` khỏi lời gọi Redpanda để test PT-03.

Kịch bản mới:
- **K7a** – dừng 1/3 broker: bán tiếp, dashboard vẫn cập nhật, Console thấy leader chuyển sang broker khác.
- **K7b** – dừng 2/3 broker (mất đa số): quầy vẫn bán, outbox tăng, dashboard báo "Đồng bộ dừng từ …"; bật lại thì
  tự đồng bộ bù.
- **K7c** – `make cut N=a`: mất nginx và broker A, nhưng B và C vẫn đồng bộ với nhau qua 2 broker còn lại (xem thẳng
  dashboard của B, C).

Xong khi: K7a không mất sự kiện nào; sau K7b và K7c, dấu vân tay 3 bản sao khớp mà không thao tác tay.

### Vòng 3 – Kênh trực tiếp giữa các bản sao (`replica/gossip-reconcile`)

| Việc | File |
|---|---|
| Tách câu upsert snapshot trong `apply_event` thành `merge_cells(conn, rows)`, dùng chung cho sink, gossip, đối soát | `api/services/replica.py` |
| Bản sao: `GET /api/snapshot` (các ô kèm `last_movement`) | `api/routers/replica.py` |
| Chi nhánh: `GET /api/snapshot` (tồn kèm `movement_id` mới nhất mỗi mã, trong một câu lệnh nên nhất quán) | `api/routers/branch.py`, `api/services/branch.py` |
| Gossip: luồng trong `replica_api`, mỗi 10 giây gọi digest của các bản sao khác (`REPLICA_URLS` bỏ chính mình); lệch thì kéo snapshot và merge. Ghi lần trao đổi cuối với từng bản sao, số ô đã vá | `api/workers/gossip.py` (mới), `db/replica.sql` |
| Đối soát: heartbeat gửi kèm `branch_url`; broker mất quá 15 giây thì bản sao kéo snapshot thẳng từ chi nhánh | `api/workers/gossip.py`, `common/models.py`, `api/workers/heartbeat.py` |
| Panel "Đồng bộ" trên dashboard thêm cột gossip | `web/dashboard.html` |

Test viết trước: `merge_cells` giao hoán (merge A rồi B bằng merge B rồi A), lũy đẳng (merge hai lần như một lần),
không ghi đè ô mới hơn (PT-10, PT-05); `apply_event` vẫn đạt các test cũ sau khi tách hàm; snapshot của chi nhánh
khớp `inventory` và `stock_movement` (PT-07: bản sao chỉ đọc qua API).

Kịch bản mới:
- **K8** – gossip tự vá: dừng sink B, bán vài đơn, `rpk group seek replica-B --to end` (B bỏ lỡ các sự kiện đó),
  bật sink B. Dấu vân tay B lệch, trong ≤ 10 giây gossip vá, "số ô đã vá" tăng.
- **K9** – đối soát: dừng cả 3 broker, bán ở CN2. Sau ~15 giây các bản sao kéo snapshot thẳng từ chi nhánh,
  dashboard cập nhật kèm nhãn "qua đối soát".

Xong khi: K8, K9 cho dấu vân tay khớp mà không thao tác tay.

### Vòng 4 – Giao diện (`web/sync-dashboard`)

HTML + JS thuần như hiện tại. Panel "Đồng bộ" đã có từ vòng 2–3; vòng này thêm:

1. **Sơ đồ topology sống (SVG)**: 3 node, mỗi node có chi nhánh, bản sao, broker; cạnh relay→broker, broker→sink,
   bản sao↔bản sao (gossip), bản sao→chi nhánh (đối soát). Cạnh đổi màu theo trạng thái, nhấp nháy khi có dữ liệu
   đi qua. Đây là chỗ trả lời câu 3.2 bằng hình.
2. **Thẻ chi nhánh tách hai trạng thái**: "còn sống" (heartbeat) và "đồng bộ" (outbox, broker).
3. **Đọc đơn điệu**: nhớ phiên bản cao nhất đã thấy; bản sao trễ trả lời thì gắn nhãn "bản sao B trễ N sự kiện"
   thay vì để số "lùi lại".
4. **Truy vết sự kiện**: bấm một sự kiện → mốc thời gian ở chi nhánh, ở broker (timestamp Kafka), ở từng bản sao
   (nhận qua Redpanda hay được vá bằng gossip).
5. **POS**: ô nhập số lượng tuỳ ý thay cho chỉ "Bán 1" và "Nhập 10".

Test viết trước: endpoint mới phục vụ truy vết (nếu có) theo quy ước pytest; phần hiển thị kiểm bằng chạy tay.
Xong khi: chạy tay K1–K9 nhìn đúng trên giao diện.

### Vòng 5 – Production local (`infra/production-local`)

Đưa các thực hành production vào chạy trên một máy, chỉ dùng phần mềm mã nguồn mở, không cloud, không dịch vụ trả
phí. Mỗi phần gắn với một ý lý thuyết. Giới hạn cần nói rõ: một máy vẫn là một miền lỗi. Vòng này cải thiện độ bền
dữ liệu và cách vận hành, không biến một máy thành hệ sẵn sàng cao thật.

| Việc | File |
|---|---|
| Mỗi node thêm standby cho CSDL chi nhánh (`branch_db_standby`), streaming replication có sẵn của Postgres, `synchronous_commit` với `synchronous_standby_names` trỏ standby: lượt bán chỉ báo thành công khi standby đã nhận WAL | `infra/compose.yml`, `infra/compose.local.yml`, `db/` (cấu hình, user replication) |
| `branch_api` và `relay` dùng chuỗi kết nối nhiều host (`host=branch_db,branch_db_standby target_session_attrs=read-write`) để tự nối sang primary mới sau khi promote; không đổi code nghiệp vụ | `infra/compose.yml`, `infra/env/*` |
| Lệnh `make promote N=<x>` (nâng standby thành primary), `make sync-mode N=<x> MODE=sync\|async` | `Makefile`, `scripts/` |
| Vệ sinh vận hành: mật khẩu CSDL ra `.env` (bỏ `app/app` viết cứng), healthcheck cho mọi service, giới hạn RAM/CPU, giới hạn kích thước log, `make backup N=<x>` (`pg_dump` vào `backups/`, thêm vào `.gitignore`) | `infra/compose.yml`, `infra/env/*`, `Makefile`, `.gitignore` |
| Giám sát (tuỳ chọn, cắt được nếu thiếu thời gian): profile `observability` gồm Prometheus và Grafana, đọc metrics của Redpanda và Postgres (exporter); một dashboard Grafana dựng sẵn: consumer lag từng bản sao, leader từng phân hoạch | `infra/compose.yml`, `infra/observability/` (mới) |
| "Kiến trúc mục tiêu production" trên giấy: sơ đồ và bảng đánh đổi (CDC thay relay, Kubernetes, LB kép, mTLS, nhiều vùng, Merkle tree) | `docs/spec.md` (mục mới) |

Quy tắc mới, ghi vào `docs/spec.md` mục 8 ở `/test-first`: **PT-12** ở chế độ đồng bộ, lượt bán chỉ báo thành công
khi standby đã nhận WAL; mất primary không mất lượt bán nào đã báo thành công.

Test viết trước: `make config` kiểm mỗi node có standby và chuỗi kết nối nhiều host, mọi service có healthcheck và
giới hạn tài nguyên, compose không còn mật khẩu viết cứng. pytest giữ xanh (CSDL test không cần standby).

Kịch bản mới:
- **K10a** – mất primary chi nhánh: bán liên tục ở CN2, dừng primary, `make promote N=b`. Mọi lượt bán POS đã báo
  thành công vẫn còn (đối chiếu `stock_movement` với kết quả POS); relay đọc outbox từ primary mới và gửi tiếp; dấu
  vân tay 3 bản sao khớp.
- **K10b** – đánh đổi đồng bộ / bất đồng bộ (PACELC): đo `elapsed_ms` của lượt bán ở hai chế độ. Chế độ đồng bộ mà
  dừng standby thì lượt bán treo (chọn nhất quán); chuyển `MODE=async` thì bán lại được, nhưng chấp nhận mất các
  lượt chưa kịp sang standby nếu primary hỏng (RPO > 0).
- (tuỳ chọn) chạy K7a khi bật `observability`, xem leader chuyển và lag tăng giảm trên Grafana.

Xong khi: K10a không mất lượt bán nào đã báo thành công; K10b đo được và ghi số độ trễ hai chế độ vào
`docs/demo.md`; K1–K9 vẫn đạt; `make check` xanh.

### Vòng 6 – Dọn và chốt (`chore/hardening`)

- Sink: thông điệp hỏng (JSON lỗi, thiếu trường) hiện làm sink chết rồi khởi động lại mãi. Ghi vào bảng
  `dead_letter`, commit qua. Test: thông điệp hỏng vào `dead_letter`, sink không ném lỗi.
- `scripts/chaos-check.sh`: tự chạy cut/heal, K7b, K8, K10a rồi so dấu vân tay 3 bản sao, in ĐẠT / KHÔNG ĐẠT.
- Cập nhật `docs/spec.md` (ba kênh, cụm broker, giới hạn mới), `db.md`, `api.md`, `demo.md`.

## 6. Giả định còn mở

- ~~Redpanda chạy được với `--memory=512M`~~ **Đã kiểm ở vòng 2: được** (log cảnh báo "below recommended" nhưng chạy;
  ~130 MB mỗi broker). Phải giữ `developer_mode` của image: tắt nó thì broker đòi tối thiểu 1 GB.
- ~~Cờ tắt write caching đặt được lúc khởi tạo cụm~~ **Đã kiểm ở vòng 2: được**, bằng `--set
  redpanda.write_caching_default=false` (nhập vào cấu hình cụm lúc lập cụm) và `-c write.caching=false` khi tạo topic.
  Phát hiện thêm: image để `developer_mode` nên rpk tự thêm `--unsafe-bypass-fsync=true` (không fsync gì cả), kể cả khi
  bỏ `--mode=dev-container`; phải ghi rõ `--unsafe-bypass-fsync=false`.
- Máy thật: container gọi được IP overlay của chính máy mình (`KAFKA_BROKERS` có cả địa chỉ máy A cho relay máy A;
  từ vòng 3 thêm `BRANCH_URL=http://<IP overlay máy A>:8001` để bản sao A đối soát CN1 cùng máy); chưa kiểm vì chỉ có
  một máy.
- ~~Compose tự thêm tên service làm alias trên mọi network~~ **Đã kiểm ở vòng 1: đúng.** Trên `minigo-wan`,
  `replica_api` trỏ về cả ba node; các node gọi nhau bằng alias riêng (`replica-b`), gắn trên cả mạng riêng của
  node lẫn `minigo-wan` (`infra/compose.local.yml`).
- ~~Đối soát với chi nhánh chỉ bật khi broker mất quá 15 giây~~ **Đã làm ở vòng 3**: mốc tính bằng `now()` của
  `replica_db`; không bật khi sink đã chết (lần kiểm broker cũ hơn 15 giây); chỉ chi nhánh có heartbeat trong 15 giây.
- Vòng 3: sau K7b, K9 (bật lại broker sau khi mất đa số), sink đọc tiếp sau ~55 giây, chậm hơn ~15 giây đo ở vòng 2.
  Vòng 3 không sửa sink; nghi do consumer group chờ hết phiên (`session.timeout.ms` mặc định 45 giây) rồi mới chia lại
  phân hoạch. Chưa kiểm. Số tồn không bị ảnh hưởng nhờ đối soát; chỉ nhật ký sự kiện đến muộn hơn.
- Vòng 5: chuỗi kết nối nhiều host của libpq (`target_session_attrs=read-write`) đủ để `psycopg_pool` tự nối sang
  primary mới sau promote mà không đổi code; kiểm ở `/plan-task` vòng 5.
- Vòng 5: promote bằng tay (`make promote`), không dùng Patroni hay repmgr. Tự động failover CSDL ghi vào "kiến trúc
  mục tiêu production".
- Vòng 5: chế độ mặc định của nhân bản (đồng bộ hay bất đồng bộ) chọn ở `/plan-task`. Mặc định đồng bộ thì mất
  standby là quầy treo, trái tinh thần PT-01 (quầy luôn bán được); mặc định bất đồng bộ thì giữ PT-01 nhưng RPO > 0.

## 7. Để sau, không làm

Để sau (khi xong mục 3):
- Chuyển kho giữa chi nhánh bằng Saga (`TRANSFER_OUT` → `TRANSFER_IN`, bù bằng `TRANSFER_CANCEL`).
- Danh mục sản phẩm phát từ trung tâm qua topic compacted `catalog`.
- Chạy lại toàn bộ trên 2–3 máy thật khi có máy: chỉ đổi file env, code giữ nguyên.

Không làm:
- Nginx vẫn là điểm chết duy nhất của cổng vào; keepalived/VIP không chạy qua Docker Desktop trên Windows. Nói rõ
  khi bảo vệ.
- Nút gây lỗi trên giao diện web: cần mount docker socket vào container, mở lỗ bảo mật. Dùng `make cut/heal`.
- Debezium, Kubernetes, Merkle tree, mTLS: nặng, không trả lời thêm câu hỏi nào; chỉ ghi vào "kiến trúc mục tiêu
  production" (vòng 5). Prometheus/Grafana chuyển thành phần tuỳ chọn của vòng 5.
