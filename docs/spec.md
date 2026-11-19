# Đặc tả hệ thống MiniGo

## 1. Bài toán

Một chuỗi cửa hàng tiện lợi có nhiều chi nhánh ở nhiều thành phố. Yêu cầu:

- Quầy ở mỗi chi nhánh bán và nhập hàng nhanh, **kể cả khi mất mạng tới trụ sở**.
- Trụ sở xem được tồn kho toàn chuỗi, trễ vài giây là chấp nhận được.
- Trụ sở chỉ cần nhớ **một địa chỉ**; một máy trung tâm hỏng thì dashboard vẫn mở được.
- Mất mạng rồi có mạng lại thì số liệu tự khớp, không cần ai làm tay.

## 2. Tính chất cần chứng minh

| Tính chất | Cơ chế trong hệ thống | Kịch bản (`demo.md`) |
|---|---|---|
| Trong suốt vị trí (location transparency) | Nginx là cổng vào duy nhất, chia yêu cầu cho các bản sao | K2 |
| Chịu lỗi, chuyển đổi khi lỗi (fault tolerance, failover) | Mỗi máy một bản sao trung tâm; nginx bỏ qua bản sao chết | K3 |
| Tự phục hồi (self-healing) | Outbox giữ sự kiện, Redpanda giữ vị trí đọc, nginx tự thử lại | K4 |
| Đồng bộ dữ liệu (data consistency) | Sự kiện đi qua Redpanda tới mọi bản sao; so bằng dấu vân tay | K1, K4 |
| Chịu được độ trễ mạng | Bán tại chỗ, đồng bộ bất đồng bộ; đo RTT trực tiếp | K5 |
| Chống trùng (idempotency) | Khoá `(branch_id, movement_id)` ở bản sao | K6 |
| Chịu lỗi của broker | Cụm 3 broker Redpanda (Raft, RF=3, `acks=all` có fsync); đồng bộ dừng thì POS và dashboard báo rõ, quầy vẫn bán | K7a, K7b, K7c |

## 3. Kiến trúc

```
                           Người dùng chỉ biết MỘT địa chỉ: http://<IP máy A>/
                                              │
 ┌──────────────────────── MÁY A ─────────────┼───────────────────────────────┐
 │                                            ▼                               │
 │  POS CN1 ─▶ branch_api ─▶ branch_db ─▶ relay ─┐   nginx (cổng vào duy nhất,│
 │                                               │   chia tải các bản sao)    │
 │  dashboard ◀ replica_api ◀ replica_db ◀ sink ◀┤                            │
 │                                         ┌─────┴──────┐                     │
 │                                         │ broker 1   │  console, topic-init│
 └─────────────────────────────────────────┼────────────┼─────────────────────┘
     ══════════ mạng overlay (Tailscale / ZeroTier) ═══ │ cụm Redpanda (Raft) ══
 ┌──────────────────── MÁY B ──────────────┼────────────┼─────────────────────┐
 │                                         │ broker 2   │                     │
 │  POS CN2 ─▶ branch_api ─▶ branch_db ─▶ relay ─┤  topic inventory.movement  │
 │  dashboard ◀ replica_api ◀ replica_db ◀ sink ◀┘  3 phân hoạch, RF=3        │
 └────────────────────────────────────────────────────────────────────────────┘
   MÁY C giống máy B (broker 3, CN3, bản sao C). Relay, sink mỗi máy nói chuyện với CẢ cụm.
```

Mọi máy chạy **giống hệt nhau**: một chi nhánh (`branch_db`, `branch_api`, `relay`), một bản sao trung tâm
(`replica_db`, `replica_api`, `sink`) và một broker Redpanda (profile **broker**). Ba broker thành **một cụm**: mỗi
phân hoạch có 3 bản (RF=3), một leader, ghi xong khi đa số (2/3) đã ghi đĩa. Mất 1 broker thì cụm tự bầu leader mới;
mất 2 broker thì không ghi được nữa, quầy vẫn bán và POS, dashboard báo "đồng bộ dừng" (PT-11). Riêng máy A chạy thêm
nhóm **core**: `nginx`, `console`, `topic-init` (tạo topic một lần khi cụm đã đủ broker).

| | Máy A | Máy B | Máy C (tuỳ chọn) |
|---|---|---|---|
| Chi nhánh | CN1 Cầu Giấy | CN2 Hà Đông | CN3 Đà Nẵng |
| Bản sao trung tâm | Bản sao A | Bản sao B | Bản sao C |
| Broker | broker 1 | broker 2 | broker 3 |
| Core | nginx, console, topic-init | — | — |
| File env | `infra/env/may-a.env` | `infra/env/may-b.env` | `infra/env/may-c.env` |

**Tại sao mỗi máy một bản sao trung tâm?** Nếu chỉ có một dashboard ở máy A, thì "chịu lỗi" chỉ là lời nói. Có
nhiều bản sao, mỗi bản tự dựng bảng tồn toàn chuỗi từ cùng một luồng sự kiện, thì nginx có chỗ để chuyển sang khi
một máy chết, và ta có thứ để so xem dữ liệu giữa các máy có thật sự khớp không.

**Hai bản sao trao đổi với nhau thế nào?** Hiện tại **gián tiếp**, qua log chung trên Redpanda: mỗi bản sao một
consumer group riêng (`replica-A`, `replica-B`), cùng đọc một log có thứ tự trong từng phân hoạch, áp bằng một hàm
tất định và lũy đẳng, nên ra cùng một trạng thái (nhân bản máy trạng thái). Hai bản sao không gọi nhau trực tiếp;
việc so dấu vân tay do trình duyệt làm qua nginx. Kênh trực tiếp giữa các bản sao là vòng 3 trong `plan.md`.

### Biến môi trường

Đặt trong `.env` ở gốc repo (chép từ `infra/env/may-<x>.env`). `infra/compose.yml` đưa vào container; code đọc ở
`common/config.py`. Chạy 3 node trên một máy thì mỗi node đọc `infra/env/local-<x>.env` (`make local-up`).

| Biến | Đặt ở | Ai đọc | Ý nghĩa, ví dụ |
|---|---|---|---|
| `COMPOSE_FILE` | `.env` | docker compose | `infra/compose.yml`, để gõ `docker compose ...` từ gốc repo |
| `COMPOSE_PROFILES` | `.env` | docker compose | `broker` (mọi máy): bật `redpanda`; `core` (chỉ máy A): bật `console`, `nginx`, `topic-init`. Máy A `core,broker`, máy B, C `broker` |
| `BROKER_HOST` | `.env`, riêng từng máy | compose (redpanda) | Địa chỉ broker của máy này tự giới thiệu cho client (`:19092`) và broker khác (`:33145`). Máy thật: IP overlay của chính máy đó `100.64.0.2`; một máy: alias `redpanda-b` |
| `BROKER_SEEDS` | `.env`, giống nhau ở mọi file | compose (redpanda, topic-init) | Các broker lập cụm, cổng RPC `33145`: `100.64.0.1:33145,100.64.0.2:33145,100.64.0.3:33145`; một máy: `redpanda-a:33145,redpanda-b:33145,redpanda-c:33145`. Cụm chỉ lập khi đủ mọi seed; RF của topic = số seed |
| `REPLICA_A`, `REPLICA_B`, `REPLICA_C` | `.env`, giống nhau ở mọi file | nginx | `host:port` của bản sao từng node. Máy thật: `replica_api:8000` (A, cùng máy), `100.64.0.2:8000`; một máy: `replica-b:8000` |
| `BRANCH_A`, `BRANCH_B`, `BRANCH_C` | `.env`, giống nhau ở mọi file | nginx | `host:port` của POS chi nhánh trên từng node. Máy thật: `branch_api:8000` (A), `100.64.0.2:8001`; một máy: `branch-b:8000` |
| `NGINX_PORT` | `.env` (tuỳ chọn) | compose | Cổng host của nginx, mặc định `80` |
| `BRANCH_PORT`, `REPLICA_PORT` | `.env` (tuỳ chọn) | compose | Cổng host của POS và dashboard, mặc định `8001`, `8000`. Một máy: node B `8011`, `8010`; node C `8021`, `8020` |
| `NODE_NAME` | `.env` | `replica_api`, `sink` | Tên bản sao `A`, `B`, `C`; consumer group là `replica-<NODE_NAME>` |
| `BRANCH_ID` | `.env` | `branch_api`, `relay` | Số chi nhánh `1`, `2`, `3` |
| `BRANCH_NAME` | `.env` (tuỳ chọn) | `branch_api` | Tên hiển thị, mặc định `Chi nhánh <BRANCH_ID>` |
| `KAFKA_BROKERS` | `.env`, giống nhau ở mọi file | `relay`, `sink`, `console`, `topic-init` | Cả ba broker, cổng `19092`, cùng host và thứ tự với `BROKER_SEEDS`: `100.64.0.1:19092,100.64.0.2:19092,100.64.0.3:19092`; một máy: `redpanda-a:19092,redpanda-b:19092,redpanda-c:19092` |
| `REPLICA_URLS` | `.env` | `branch_api` | Bản sao nhận heartbeat: `A=http://replica_api:8000,B=http://100.64.0.2:8000,C=...`; một máy: `A=http://replica-a:8000,...` |

| `ROLE` | `infra/compose.yml` | mọi tiến trình Python | `branch` hoặc `replica` |
| `DATABASE_URL` | `infra/compose.yml` | mọi tiến trình Python | CSDL của chính tiến trình: `postgresql://app:app@branch_db:5432/kho` hoặc `@replica_db` |
| `TEST_DB_URL` | `infra/compose.test.yml` | `tests/conftest.py` | CSDL test, tên phải kết thúc bằng `_test`: `postgresql://app:app@test_db:5432/kho_test` |

**Chạy 3 node trên một máy** (`infra/compose.local.yml`): mỗi node là một compose project `minigo-a`, `minigo-b`,
`minigo-c`; "mạng overlay" là docker network chung `minigo-wan`. Compose tự thêm tên service (`replica_api`) làm
alias trên mọi network, nên trên `minigo-wan` tên service trỏ về cả ba node: giữa các node chỉ gọi bằng alias riêng
`branch-<x>`, `replica-<x>`, `redpanda-<x>`. Lệnh: `make local-up`, `local-down`, `local-reset`, `make cut N=<x>`,
`make heal N=<x>` (`docs/demo.md` mục "Chạy trên một máy").

## 4. Một lượt bán đi qua những đâu

1. Thu ngân bấm **Bán 1** ở POS máy B.
2. `branch_api` mở **một transaction** trên CSDL của CN2: trừ tồn, ghi sổ cái `stock_movement`, ghi `outbox`.
   Commit. Xong trong vài mili giây, chưa có gì đi qua mạng.
3. `relay` ở máy B đọc outbox, gửi sự kiện tới broker đang làm leader của phân hoạch (có thể ở máy khác, qua mạng
   overlay), chờ cụm xác nhận đa số broker đã ghi đĩa rồi mới đánh dấu đã gửi, và ghi kết quả vào `relay_status`.
4. `sink A` và `sink B` **mỗi cái đọc riêng** toàn bộ luồng sự kiện (hai consumer group khác nhau), mỗi cái cập nhật
   bảng tổng hợp của bản sao mình.
5. Dashboard, mở qua nginx, lần lượt được bản sao A và bản sao B trả lời. Cả hai hiện cùng một con số.

Song song, `branch_api` gửi heartbeat tới **mọi** bản sao mỗi 5 giây (HTTP thẳng, không qua Redpanda), kèm số sự
kiện còn trong outbox và RTT lần trước. Mỗi bản sao tự phán đoán chi nhánh nào còn sống. Vì heartbeat không qua
broker, "chi nhánh còn sống" và "đồng bộ đang chạy" là hai trạng thái khác nhau: sink mỗi bản sao tự kiểm đường đọc
Redpanda mỗi 5 giây (`sink_stats.broker_ok`, `lag`), dashboard hiện riêng "Đồng bộ dừng từ HH:MM:SS".

## 5. Mức nhất quán

- **Nhất quán cuối** (eventual consistency), không phải nhất quán mạnh. "Thời gian thực" nghĩa là trễ 1–2 giây, và
  con số trễ hiện ngay trên dashboard.
- Muốn nhất quán mạnh thì mỗi lượt bán phải chờ mọi máy xác nhận; mất mạng là ngừng bán. Hệ chọn **sẵn sàng hơn
  nhất quán** (đánh đổi CAP).
- Thứ tự sự kiện dựa vào `movement_id` do chi nhánh cấp tăng dần, **không** dựa vào đồng hồ (đồng hồ các máy lệch nhau).
- Không đảm bảo đọc đơn điệu (monotonic reads): trong lúc một bản sao còn đuổi theo, hai lần làm mới liên tiếp có
  thể thấy số khác nhau, thậm chí "lùi lại".

## 6. Giới hạn

- **Máy A là điểm chết duy nhất cho cổng vào** (nginx). Rút mạng máy A thì địa chỉ nginx không vào được, nhưng
  quầy ở mọi máy **vẫn bán**, và máy B, C vẫn đồng bộ với nhau qua 2 broker còn lại (K7c); xem thẳng dashboard
  `B:8000`, `C:8000`. Cắm lại thì tự phục hồi.
- **Cụm broker chịu được mất 1 trong 3 broker** (K7a). Mất đa số (2/3) thì đồng bộ dừng cho tới khi có lại đa số;
  quầy vẫn bán, outbox giữ sự kiện, POS và dashboard báo "đồng bộ dừng" (K7b). Trong lúc bầu leader mới (vài giây)
  dashboard có thể báo "đồng bộ dừng" ngắn rồi tự hết.
- **Chỉ có 2 máy thật thì broker vẫn là điểm chết**: Redpanda chỉ nhận RF lẻ và cụm 2 broker không chịu được lỗi
  nào, nên chỉ máy A chạy broker, RF=1 (`docs/demo.md` mục 2).
- **Mất dữ liệu broker** (xoá volume, hỏng đĩa trên đa số broker) thì sự kiện bản sao chưa kịp đọc mất hẳn khỏi
  Redpanda; chưa có đường dựng lại từ sổ cái chi nhánh (vòng 3).
- **Dữ liệu mỗi chi nhánh chỉ có một bản chính**, ở chính máy chi nhánh. Bản sao trung tâm chỉ là bản tổng hợp để
  đọc. Máy B hỏng ổ cứng thì mất các lượt bán chưa kịp gửi đi.
- **Bản sao bỏ lỡ sự kiện thì không có cơ chế tự vá**: nếu dữ liệu Redpanda mất trước khi một bản sao kịp đọc, dấu
  vân tay lệch mãi.
- **Nginx chỉ tự thử lại yêu cầu idempotent (GET).** Lệnh bán (POST) qua nginx mà thất bại thì không được thử lại
  tự động. POS tự bảo vệ bằng `request_id`.

## 7. Đối chiếu với Chương 2

| Slide | Chỗ thể hiện trong demo |
|---|---|
| Kiến trúc phần mềm và kiến trúc hệ thống | Cùng một bộ code và một file compose; đặt lên 1, 2 hay 3 máy chỉ khác file `.env` |
| Layered, RESTful | POS → `branch_api` → Postgres; các tài nguyên `/api/inventory`, `/api/sale` |
| Microservices, publish–subscribe | api, relay, sink, nginx là các tiến trình độc lập; relay phát vào topic, các sink đăng ký |
| Middleware: Broker | Redpanda: thêm máy C không phải sửa máy nào khác |
| Middleware: Interceptor | Nginx chen vào giữa trình duyệt và bản sao, tự chọn bản sao và tự thử lại mà client không hay biết |
| Thin/Fat client, 3-tier | Trình duyệt là thin client; chi nhánh "béo": xử lý tại chỗ, chạy offline tốt, đồng bộ khó |
| Overlay network | Tailscale / ZeroTier là một mạng phủ dựng trên Internet |
| Super-peer, BitTorrent tracker | Máy chủ điều phối của Tailscale giúp các máy tìm thấy nhau, rồi dữ liệu đi thẳng giữa các máy |
| Edge & Fog | Chi nhánh là edge: xử lý tại chỗ, độ trễ thấp (K5) |
| Phổ kiến trúc | Phi tập trung ở phần bán hàng và broker (cụm 3 máy), tập trung ở cổng vào (nginx máy A) |

## 8. Quy tắc bất biến

Mã PT-xx dùng trong `docs/plan.md` (cột "Quy tắc"), docstring test và checklist tự duyệt. Thêm quy tắc mới thì thêm
dòng ở đây trước khi code.

| Mã | Quy tắc | Ép ở đâu |
|---|---|---|
| PT-01 | Chi nhánh chỉ nói chuyện với CSDL của chính nó; đường bán hàng không có lời gọi mạng | `api/services/branch.py` |
| PT-02 | Sửa tồn, ghi `stock_movement`, ghi `outbox` trong MỘT transaction | `record_movement`, `_change_stock` |
| PT-03 | Relay chỉ đánh dấu `sent_at` sau khi Redpanda xác nhận mọi thông điệp của lô (at-least-once) | `relay_batch` (`api/services/branch.py`), gọi từ `api/workers/relay.py` |
| PT-04 | Áp sự kiện lũy đẳng: khoá `(branch_id, movement_id)` | `apply_event` |
| PT-05 | Chịu lệch thứ tự: snapshot chỉ ghi đè khi `movement_id` lớn hơn; không so thứ tự bằng đồng hồ | `apply_event` |
| PT-06 | Sink ghi CSDL xong rồi mới commit offset | `api/workers/sink.py` |
| PT-07 | Bản sao chỉ đọc: không ghi về chi nhánh, không gọi thẳng CSDL chi nhánh | `api/services/replica.py` |
| PT-08 | Nginx chỉ tự thử lại yêu cầu idempotent; lệnh bán chống trừ hai lần bằng `request_id` | nginx, `_change_stock` |
| PT-09 | Không bán lố tồn: trừ bằng một câu `UPDATE` có điều kiện `qty_on_hand + delta >= 0` | `_change_stock` |
| PT-10 | Mọi kênh cập nhật snapshot (sink, gossip, đối soát) dùng chung một luật merge giao hoán, lũy đẳng theo từng ô | vòng 3 |
| PT-11 | Mất đa số broker không làm dừng bán; trạng thái "đồng bộ dừng" phải hiện trên POS và dashboard | `record_relay_result` (`relay_status`), `record_broker_check` (`sink_stats`), `web/pos.html`, `web/dashboard.html` |
