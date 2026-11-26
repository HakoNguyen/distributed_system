# Kế hoạch triển khai

File này cho biết dự án đang ở đâu và việc tiếp theo là gì. Đọc mục 1 trước khi làm bất cứ việc gì.
Mục tiêu trước mắt: xử lý hai câu hỏi của thầy (mục 3), trên **một máy**.

## 1. Tiến độ

**Vòng tiếp theo: vòng 6.** Mỗi lần chỉ làm một vòng, đúng thứ tự: vòng sau dựa trên hạ tầng của vòng trước.

| Vòng | Phạm vi | Nhánh | Việc | Quy tắc | Kịch bản | Trạng thái |
|---|---|---|---|---|---|---|
| 0 | khung | `base/restructure-workflow` | Gộp về một bản theo cấu trúc mới; quy trình 4 bước; hạ tầng test, 5 test nền | PT-02, 04, 05, 08, 09 | K1, K6 trên 1 node | xong, đã merge (PR #1) |
| 1 | `infra` | `infra/local-multi-node` | Mô phỏng 3 máy trên một máy, `make cut/heal` | — | K1–K6 trên 3 node | xong, đã merge (PR #2) |
| 2 | `infra`, `branch`, `replica`, `web` | `broker/redpanda-cluster` | Cụm 3 broker; trạng thái đồng bộ trên POS và dashboard | PT-03, PT-06, PT-11 | K7a, K7b, K7c | xong, đã merge (PR #3); 16 test, K1–K7c đạt trên 3 node một máy |
| 3 | `replica`, `branch`, `web` | `replica/gossip-reconcile` | Gossip giữa bản sao; đối soát với chi nhánh | PT-04, PT-05, PT-07, PT-10 | K8, K9 | xong, đã merge (PR #4); 43 test, K1–K9 đạt trên 3 node một máy |
| 4 | `web`, `replica`, `branch` | `web/sync-dashboard` | Topology sống, đọc đơn điệu, truy vết sự kiện, POS | — | chạy tay K1–K9; K11, K12 | xong, đã merge (PR #5); 58 test, selftest dashboard 22/22, POS 5/5; K1–K9, K11, K12 đạt trên 3 node một máy |
| 4b | `web` | `web/ui-polish` | Chỉnh giao diện trước vòng 5: tràn ngang trên điện thoại, cột giờ tab Sự kiện, dải sự cố hệ thống ở Tổng quan, bớt nhiễu, ghi máy A/B/C trên sơ đồ, trang không bị cache | — | chạy tay trên 3 node | xong, đã merge (PR #7); selftest dashboard 24/24, POS 5/5; 58 test |
| 5 | `infra`, `replica`, `web` | `ha/entry-failure-detector` | HA cổng vào (nginx ở mọi node, client tự chuyển); bộ phát hiện lỗi có trạng thái, kết luận theo đa số bản sao | PT-13 | K13, K14 | đã code (27/11/2026), chờ commit; 83 test, selftest dashboard 33/33, POS 10/10; K1–K14 đạt trên 3 node một máy; sửa hai lỗi hạ tầng (IP gắn cứng sau `heal`, `topic-init` lặp) |
| 6 | `branch`, `replica`, `web` | `ha/hinted-handoff` | Chi nhánh sập vẫn bán: ghi hộ ở bản sao, chi nhánh phục hồi ở RECOVERING rồi kéo về áp theo thứ tự | PT-14 | K15 | chưa làm |
| 7 | `infra`, `docs` | `infra/production-local` | Standby đồng bộ cho CSDL chi nhánh; vệ sinh vận hành; giám sát (tuỳ chọn); kiến trúc mục tiêu production trên giấy | PT-12 | K10a, K10b | chưa làm |
| 8 | `replica`, `scripts`, `docs` | `chore/hardening` | `dead_letter`, `scripts/chaos-check.sh` có đo thời gian gián đoạn, chốt tài liệu | PT-06 | `chaos-check.sh` | chưa làm |

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

### Vòng 5 – HA cổng vào và bộ phát hiện lỗi (`ha/entry-failure-detector`)

Bỏ điểm chết duy nhất ở cổng vào và làm cho việc kết luận "chi nhánh chết" đáng tin hơn. Vòng 6 (ghi hộ) dựa vào
kết luận này. Tham khảo repo cùng môn `4ustintr/BTL_Distributed_Application` (Health Monitor, trạng thái
ONLINE/OFFLINE/RECOVERING, demo `docker pause` so với `docker kill`). MiniGo khác ở chỗ không có HQ điều phối, nên
kết luận được rút ra từ đa số bản sao ngang hàng.

| Việc | File |
|---|---|
| **A. Cổng vào không còn điểm chết:** nginx chạy ở cả 3 node, cấu hình giống nhau (upstream đủ 3 bản sao, `/cnX/` đủ 3 chi nhánh). Dashboard và POS biết danh sách cổng vào; một cổng không trả lời thì tự chuyển sang cổng kế tiếp (failover phía client, cùng ý với `bootstrap.servers` của Kafka) | `infra/compose.yml`, `infra/compose.local.yml`, `infra/env/*`, `infra/nginx/`, `web/*.html` |
| **C. Bộ phát hiện lỗi có trạng thái:** mỗi bản sao tự đánh giá từng chi nhánh theo tuổi heartbeat: ONLINE → SUSPECT → OFFLINE (hai ngưỡng); gửi đánh giá của mình qua gossip; chỉ kết luận OFFLINE khi **đa số bản sao** (2/3) cùng thấy OFFLINE. RECOVERING chỉ khai báo trong spec, làm hẳn ở vòng 6 | `api/services/replica.py`, `api/workers/gossip.py`, `db/replica.sql`, `common/models.py` |
| Dashboard: hiện trạng thái theo đa số và đánh giá riêng của từng bản sao (thấy rõ các bản sao có thể nhìn khác nhau); cổng vào đang dùng | `web/dashboard.html` |
| Lệnh demo: dừng hoặc tạm dừng (`docker pause`) một chi nhánh, một nginx | `Makefile`, `scripts/` |

Quy tắc mới, ghi vào `docs/spec.md` mục 8 ở `/test-first`: **PT-13** một chi nhánh chỉ bị coi là OFFLINE khi đa số
bản sao cùng thấy OFFLINE; một bản sao mất liên lạc riêng lẻ chỉ đổi góc nhìn của chính nó.

Test viết trước: hàm thuần tính trạng thái từ tuổi heartbeat (đúng hai ngưỡng); hàm kết luận theo đa số từ đánh giá
của các bản sao (2/3 OFFLINE thì OFFLINE, 1/3 thì không; thiếu đánh giá của bản sao đã chết thì tính thế nào); `make
config` kiểm nginx có ở mọi node và danh sách cổng vào giống nhau. Logic chọn cổng vào ở JS kiểm bằng selftest
trong trình duyệt như vòng 4.

Kịch bản mới:
- **K13** – mất cổng vào: dashboard đang mở qua nginx A; dừng nginx A (hoặc `make cut N=a`). Dashboard tự chuyển sang
  cổng của node khác, vẫn làm mới được; POS mở qua cổng vào cũng vậy.
- **K14** – chậm hay chết: `docker pause` chi nhánh B (chậm, vẫn sống) rồi `docker kill` (chết). Cả hai đều đi qua
  SUSPECT rồi OFFLINE: timeout không phân biệt được chậm với chết. Biến thể: chỉ cắt đường giữa chi nhánh B và một bản
  sao, bản sao đó thấy OFFLINE nhưng kết luận đa số vẫn là ONLINE.

Xong khi: K13, K14 đạt; K1–K12 vẫn đạt; `make check` xanh.

### Vòng 6 – Chi nhánh sập vẫn bán: ghi hộ (`ha/hinted-handoff`)

Hiện chi nhánh chỉ "cô lập lỗi": server chi nhánh chết thì quầy dừng. Vòng này cho quầy bán tiếp bằng **ghi hộ**
(hinted handoff, store-and-forward như Amazon Dynamo; tương tự `pending_txn` và Replay Worker của repo tham khảo).
Đổi lại phải chấp nhận khả năng bán quá tồn, phát hiện lúc áp lại (chọn A trong CAP).

| Việc | File |
|---|---|
| POS mở được khi server chi nhánh sập: trang POS do nginx (hoặc bản sao) phục vụ, không chỉ do `branch_api` | `infra/nginx/`, `web/pos.html` |
| POS gọi chi nhánh lỗi và kết luận đa số là OFFLINE (vòng 5) thì gửi lượt bán lên bản sao (ghi hộ), kèm `request_id`. Bản sao kiểm "tồn tạm tính" = snapshot trừ các lượt ghi hộ chưa áp, lưu vào bảng ghi hộ | `api/routers/replica.py`, `api/services/replica.py`, `db/replica.sql`, `web/pos.html` |
| Chi nhánh khởi động lại ở **RECOVERING**: chưa nhận bán mới; **tự kéo** ghi hộ từ các bản sao (PT-07 giữ nguyên: bản sao không ghi vào CSDL chi nhánh), áp theo thứ tự qua đúng đường bán hàng (`change_stock`, `request_id` chống trùng, PT-08); lượt không đủ tồn ghi REJECTED; xong thì báo bản sao đánh dấu đã áp, chuyển ONLINE | `api/services/branch.py`, `api/workers/` (mới), `db/branch.sql`, `api/main.py` |
| POS hiện rõ đang "ghi hộ qua trung tâm" hay "đang phục hồi"; dashboard hiện số lượt ghi hộ chờ áp, đã áp, bị từ chối | `web/pos.html`, `web/dashboard.html` |

Quy tắc mới, ghi vào `docs/spec.md` mục 8 ở `/test-first`: **PT-14** mỗi lượt ghi hộ được áp vào chi nhánh đúng một
lần, theo thứ tự ghi hộ, trước khi chi nhánh nhận lượt bán mới; lượt không áp được thì REJECTED và hiện ra, không mất
lặng lẽ.

Test viết trước: ghi hộ bị từ chối khi tồn tạm tính không đủ; ghi hộ trùng `request_id` chỉ lưu một lần; áp ghi hộ
hai lần chỉ trừ tồn một lần; áp đúng thứ tự; lượt vượt tồn thật thành REJECTED; ở RECOVERING lượt bán mới bị từ chối
với mã lỗi rõ ràng; gom ghi hộ từ nhiều bản sao không trùng không sót.

Kịch bản mới:
- **K15** – chi nhánh sập vẫn bán: dừng `branch_api` và `branch_db` của B; đa số bản sao kết luận OFFLINE; POS B chuyển
  sang ghi hộ, bán 5 đơn. Bật lại B: RECOVERING, áp đủ 5 lượt, gửi lại lần hai không trừ thêm, rồi ONLINE; 3 dấu vân
  tay khớp. Biến thể: một lượt ghi hộ vượt tồn thật thì REJECTED và hiện trên POS, dashboard.

Giới hạn phải ghi vào `docs/spec.md` mục 6: phân vùng mạng làm POS không gọi được chi nhánh trong khi chi nhánh vẫn
sống (và vẫn bán ở quầy khác) thì hai nơi cùng ghi; có thể bán quá tồn, chỉ phát hiện lúc áp lại. PT-13 làm giảm khả
năng này nhưng không loại bỏ. Cách triệt để (lease kèm fencing token) ghi vào "kiến trúc mục tiêu production".

Xong khi: K15 đạt cả biến thể REJECTED; K1–K14 vẫn đạt; `make check` xanh.

### Vòng 7 – Production local (`infra/production-local`)

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
| Nhặt từ vòng 5 vào "kiến trúc mục tiêu": cổng vào bằng một tên DNS trỏ nhiều địa chỉ (nhiều bản ghi A, hoặc VIP/anycast trước các nginx) để cả lần mở trang đầu cũng không phụ thuộc một máy; CORS liệt kê đúng origin thay cho `*` (`docs/spec.md` mục 6) | `docs/spec.md` (mục mới) |

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

### Vòng 8 – Dọn và chốt (`chore/hardening`)

- Sink: thông điệp hỏng (JSON lỗi, thiếu trường) hiện làm sink chết rồi khởi động lại mãi. Ghi vào bảng
  `dead_letter`, commit qua. Test: thông điệp hỏng vào `dead_letter`, sink không ném lỗi.
- `scripts/chaos-check.sh`: tự chạy cut/heal, K7b, K8, K10a, K13, K15 rồi so dấu vân tay 3 bản sao, in ĐẠT / KHÔNG ĐẠT.
  Đo và in thời gian gián đoạn (bao lâu không bán được, không xem được dashboard) và thời gian phục hồi (tới khi 3 dấu
  vân tay khớp) của từng kịch bản, để trả lời "có HA không" bằng số (học theo `scripts/measure` của repo tham khảo
  cùng môn `4ustintr/BTL_Distributed_Application`).
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
  phân hoạch. Chưa kiểm. Số tồn không bị ảnh hưởng nhờ đối soát; chỉ nhật ký sự kiện đến muộn hơn. Vòng 4 thấy được
  trên khung truy vết (K12 sau K7b): broker ghi lúc 13:54:05 (bật lại 13:53:56), các bản sao đọc lúc 13:54:50–57,
  tức chậm nằm ở phía consumer, không ở relay. Vẫn chưa sửa.
- ~~Vòng 4: timestamp Kafka là giờ broker~~ **Đã kiểm ở vòng 4: đúng khi topic đặt `message.timestamp.type=LogAppendTime`**
  (Redpanda v24.2.8 nhận lúc `rpk topic create -c`; producer gửi timestamp năm 2001, consumer nhận giờ broker kiểu
  `LogAppendTime`). Mặc định CreateTime là giờ relay gọi `produce()`.
- ~~Vòng 4: metadata Redpanda bỏ broker đã chết~~ **Đã kiểm ở vòng 4: đúng** (broker dừng biến khỏi `brokers` ngay
  lần hỏi sau, bật lại thì có lại sau ~6 giây); ISR thì giữ cả 3 suốt 45 giây nên không dùng. Ba điều phát hiện thêm:
  mất đa số thì sau ~2 giây không hỏi được metadata (sơ đồ ghi "không hỏi được", không biết broker nào còn); node bị
  cô lập (K3, K7c) vẫn hỏi được broker thiểu số của nó nhưng nhận danh sách cũ, nên dashboard bỏ `brokers_up` của sink
  có `broker_ok = false`; vài chục giây sau khi một broker dừng, các sink có thể thấy danh sách khác nhau.
- ~~Phát hiện lúc làm 4b: (1) `make heal` nối lại bằng `--ip`, container khác lấy mất IP, "Address already in use";
  (2) `topic-init` chạy lại khi topic đã có thì lặp mãi mỗi 3 giây~~ **Đã sửa ở vòng 5**: (1) mọi container trên
  `minigo-wan` có IP cố định (`WAN_IP_PREFIX`), IP động chỉ cấp trong `10.210.0.128/25`; đo: cut B, dựng lại hẳn node
  A, C, heal B, dừng broker B, dựng lại A, bật broker B đều được. (2) điều kiện dừng của `until` là `grep` (sau `;`),
  chạy lại thì in `TOPIC_ALREADY_EXISTS` và thoát 0 ngay.
- ~~Vòng 5: trang mở từ cổng vào A gọi cổng vào B là khác origin~~ **Đã làm ở vòng 5**: CORS ở nginx
  (`Access-Control-Allow-Origin: *`, `OPTIONS` 204, mức `server`); đo trên Edge: dashboard và POS (POST JSON) gọi được
  cổng khác. Cổng host một máy: A 80, B 8012, C 8022.
- ~~Vòng 5: ngưỡng SUSPECT, OFFLINE và cách tính đa số~~ **Chốt ở vòng 5**: SUSPECT từ 8 giây, OFFLINE từ 15 giây;
  đa số trên tổng số bản sao cấu hình (2/3); góc nhìn cũ quá 15 giây không tính. Đối soát vẫn theo góc nhìn riêng.
- ~~Vòng 5: nginx chết lúc khởi động khi node khác chưa chạy~~ **Đã kiểm ở vòng 5**: nginx 1.27.5 với `server ...
  resolve` trong upstream (có `zone`, `resolver 127.0.0.11`) khởi động được khi tên chưa phân giải được, đường đó trả
  502; tên có lại thì tự dùng. `resolve` đặt trên IP literal (máy thật) vẫn qua `nginx -t`.
- ~~Vòng 5: `docker kill` có bị `restart: unless-stopped` tự bật lại không~~ **Đã kiểm ở vòng 5: không** (Exited 137,
  RestartCount 0); K14 dùng kill cho ca "chết hẳn".
- Vòng 5, máy thật: nginx mọi máy gọi `REPLICA_*`, `BRANCH_*` bằng IP overlay, kể cả máy của chính nó (cùng giả định
  "container gọi được IP overlay của chính máy mình" ở trên); chưa kiểm vì chỉ có một máy.
- Vòng 6: ghi hộ rải trên nhiều bản sao (nginx chia lần lượt) hay dồn về một bản sao; chi nhánh gom từ mọi bản sao
  thế nào khi một bản sao đang chết. Chọn ở `/plan-task` vòng 6.
- Vòng 6: RECOVERING mà không gọi được bản sao nào thì làm gì (chờ, hay hết thời hạn thì tự ONLINE kèm cảnh báo như
  repo tham khảo).
- Vòng 7: chuỗi kết nối nhiều host của libpq (`target_session_attrs=read-write`) đủ để `psycopg_pool` tự nối sang
  primary mới sau promote mà không đổi code; kiểm ở `/plan-task` vòng 7.
- Vòng 7: promote bằng tay (`make promote`), không dùng Patroni hay repmgr. Tự động failover CSDL ghi vào "kiến trúc
  mục tiêu production".
- Vòng 7: chế độ mặc định của nhân bản (đồng bộ hay bất đồng bộ) chọn ở `/plan-task`. Mặc định đồng bộ thì mất
  standby là quầy treo, trái tinh thần PT-01 (quầy luôn bán được); mặc định bất đồng bộ thì giữ PT-01 nhưng RPO > 0.

## 7. Để sau, không làm

Để sau (khi xong mục 3):
- Chuyển kho giữa chi nhánh bằng Saga (`TRANSFER_OUT` → `TRANSFER_IN`, bù bằng `TRANSFER_CANCEL`).
- Danh mục sản phẩm phát từ trung tâm qua topic compacted `catalog`.
- Chạy lại toàn bộ trên 2–3 máy thật khi có máy: chỉ đổi file env, code giữ nguyên.

Không làm:
- keepalived/VIP cho nginx: không chạy qua Docker Desktop trên Windows. Vòng 5 bỏ điểm chết ở cổng vào bằng nginx ở
  mọi node và client tự chuyển cổng, thay cho VIP.
- Nút gây lỗi trên giao diện web: cần mount docker socket vào container, mở lỗ bảo mật. Dùng `make cut/heal`.
- Debezium, Kubernetes, Merkle tree, mTLS: nặng, không trả lời thêm câu hỏi nào; chỉ ghi vào "kiến trúc mục tiêu
  production" (vòng 7). Prometheus/Grafana chuyển thành phần tuỳ chọn của vòng 7.
