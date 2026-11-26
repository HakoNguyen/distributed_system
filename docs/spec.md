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
| Bản sao tự vá lẫn nhau (anti-entropy) | Gossip: các bản sao so dấu vân tay, kéo snapshot, merge theo từng ô | K8 |
| Phục hồi từ nguồn sự thật | Mất broker quá 15 giây thì bản sao đối soát thẳng với chi nhánh qua API | K9 |
| Đọc đơn điệu (monotonic reads) | Dashboard nhớ phiên bản (`last_movement`) từng ô đã hiện; bản sao trả lời cũ hơn thì giữ số cũ và gắn nhãn "bản sao B trễ N sự kiện" | K11 |
| Quan sát được đường đi của dữ liệu | Sơ đồ topology sống; truy vết một sự kiện qua chi nhánh, broker (timestamp Kafka), từng bản sao | K12, K1–K9 trên giao diện |

## 3. Kiến trúc

```
        Người dùng mở MỘT địa chỉ bất kỳ: http://<IP máy A|B|C>/ (cổng chết thì trang tự chuyển cổng)
                                              │
 ┌──────────────────────── MÁY A ─────────────┼───────────────────────────────┐
 │                                            ▼                               │
 │  POS CN1 ─▶ branch_api ─▶ branch_db ─▶ relay ─┐   nginx (cổng vào, mỗi máy │
 │                                               │   một cái; chia tải bản sao)│
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
   MÁY C giống máy B (broker 3, nginx, CN3, bản sao C). Relay, sink mỗi máy nói chuyện với CẢ cụm.
```

Mọi máy chạy **giống hệt nhau**: một chi nhánh (`branch_db`, `branch_api`, `relay`), một bản sao trung tâm
(`replica_db`, `replica_api`, `sink`), một **nginx** (cổng vào, vòng 5) và một broker Redpanda (profile **broker**).
Ba broker thành **một cụm**: mỗi phân hoạch có 3 bản (RF=3), một leader, ghi xong khi đa số (2/3) đã ghi đĩa. Mất 1
broker thì cụm tự bầu leader mới; mất 2 broker thì không ghi được nữa, quầy vẫn bán và POS, dashboard báo "đồng bộ
dừng" (PT-11). Riêng máy A chạy thêm nhóm **core**: `console`, `topic-init` (tạo topic một lần khi cụm đã đủ broker).

**Cổng vào không còn điểm chết duy nhất** (vòng 5, K13). Ba nginx cấu hình giống hệt nhau: vào cổng nào cũng tới được
mọi bản sao (chia lần lượt) và mọi chi nhánh (`/cnX/`). Tên phân giải động (`resolve`), nên nginx khởi động được cả khi
node khác chưa chạy hay đang mất mạng. Dashboard và POS đang mở đọc danh sách cổng vào (`GATEWAYS`, qua
`/lb/gateways.json`) một lần lúc mở trang; cổng đang dùng không trả lời (lỗi mạng, quá 4 giây; dashboard thêm 502–504)
thì gọi ngay cổng kế tiếp, khác origin nên nginx bật CORS. Giống `bootstrap.servers` của Kafka: client biết nhiều địa
chỉ, tự thử lần lượt. POS chuyển cổng giữa chừng một lượt bán thì dòng đó giữ `request_id`, gửi lại qua cổng mới không
trừ hai lần (PT-08). Không tự quay về cổng cũ khi nó sống lại.

| | Máy A | Máy B | Máy C (tuỳ chọn) |
|---|---|---|---|
| Chi nhánh | CN1 Cầu Giấy | CN2 Hà Đông | CN3 Đà Nẵng |
| Bản sao trung tâm | Bản sao A | Bản sao B | Bản sao C |
| Broker | broker 1 | broker 2 | broker 3 |
| Cổng vào (nginx) | `:80` (một máy `localhost/`) | `:80` (một máy `localhost:8012`) | `:80` (một máy `localhost:8022`) |
| Core | console, topic-init | — | — |
| File env | `infra/env/may-a.env` | `infra/env/may-b.env` | `infra/env/may-c.env` |

**Tại sao mỗi máy một bản sao trung tâm?** Nếu chỉ có một dashboard ở máy A, thì "chịu lỗi" chỉ là lời nói. Có
nhiều bản sao, mỗi bản tự dựng bảng tồn toàn chuỗi từ cùng một luồng sự kiện, thì nginx có chỗ để chuyển sang khi
một máy chết, và ta có thứ để so xem dữ liệu giữa các máy có thật sự khớp không.

**Hai bản sao trao đổi với nhau thế nào?** Qua **ba kênh**, cùng một luật merge (PT-10):

```
 Kênh 1 (chính):    Chi nhánh ─outbox/relay─▶ Redpanda ─┬▶ sink A ▶ Bản sao A
                                                         └▶ sink B ▶ Bản sao B
 Kênh 2 (gossip):   Bản sao A ◀── HTTP: so dấu vân tay, kéo snapshot ──▶ Bản sao B   (mỗi 10 giây)
 Kênh 3 (đối soát): Bản sao X ── HTTP GET /api/snapshot ──▶ Chi nhánh               (chỉ khi mất broker > 15 giây)
```

1. **Gián tiếp, qua log chung trên Redpanda** (đường chính): mỗi bản sao một consumer group riêng (`replica-A`,
   `replica-B`), cùng đọc một log có thứ tự trong từng phân hoạch, áp bằng một hàm tất định và lũy đẳng, nên ra cùng
   một trạng thái (nhân bản máy trạng thái).
2. **Trực tiếp, gossip (anti-entropy kiểu kéo)**: mỗi bản sao có một luồng nền cho từng bản sao khác (`REPLICA_URLS`,
   bỏ dòng của chính mình). Mỗi 10 giây gọi `GET /api/digest` của bên kia; dấu vân tay khác thì kéo cả snapshot
   (`GET /api/snapshot`, 60 ô). Chỉ vá ô mà bản sao mình **vẫn thiếu sau 2 lần kiểm liên tiếp** (≥ 10 giây), để sink
   có thời gian làm việc: sink chậm vài giây (K1) không bao giờ bị vá. Bản sao lỡ sự kiện (sink dừng, offset bị nhảy,
   dữ liệu broker mất) được vá trong ≤ 20 giây (K8).
3. **Đối soát với chi nhánh** (nguồn sự thật): khi sink báo mất broker quá 15 giây, bản sao kéo
   `GET /api/snapshot` thẳng từ mọi chi nhánh còn heartbeat (địa chỉ `branch_url` chi nhánh tự báo trong heartbeat).
   Chỉ đọc qua API, không ghi về (PT-07) (K7b, K9).

Luật merge "`movement_id` lớn hơn thắng" áp cho **từng ô** (chi nhánh, mã hàng) là CRDT dạng trạng thái
(LWW-register với phiên bản do chính chi nhánh cấp): giao hoán, kết hợp, lũy đẳng, nên thứ tự nhận, nhận trùng, đến
từ kênh nào đều hội tụ. So theo từng ô chứ không theo từng chi nhánh, vì sự kiện của một chi nhánh nằm rải trên nhiều
phân hoạch và một chi nhánh có thể đã bán tiếp mã khác sau khi bản sao lỡ sự kiện. Lời gọi mạng luôn xong trước khi
mở transaction ghi.

### Biến môi trường

Đặt trong `.env` ở gốc repo (chép từ `infra/env/may-<x>.env`). `infra/compose.yml` đưa vào container; code đọc ở
`common/config.py`. Chạy 3 node trên một máy thì mỗi node đọc `infra/env/local-<x>.env` (`make local-up`).

| Biến | Đặt ở | Ai đọc | Ý nghĩa, ví dụ |
|---|---|---|---|
| `COMPOSE_FILE` | `.env` | docker compose | `infra/compose.yml`, để gõ `docker compose ...` từ gốc repo |
| `COMPOSE_PROFILES` | `.env` | docker compose | `broker` (mọi máy): bật `redpanda`; `core` (chỉ máy A): bật `console`, `topic-init`. Máy A `core,broker`, máy B, C `broker`. `nginx` không thuộc profile nào: chạy ở mọi máy (vòng 5) |
| `BROKER_HOST` | `.env`, riêng từng máy | compose (redpanda) | Địa chỉ broker của máy này tự giới thiệu cho client (`:19092`) và broker khác (`:33145`). Máy thật: IP overlay của chính máy đó `100.64.0.2`; một máy: alias `redpanda-b` |
| `BROKER_SEEDS` | `.env`, giống nhau ở mọi file | compose (redpanda, topic-init) | Các broker lập cụm, cổng RPC `33145`: `100.64.0.1:33145,100.64.0.2:33145,100.64.0.3:33145`; một máy: `redpanda-a:33145,redpanda-b:33145,redpanda-c:33145`. Cụm chỉ lập khi đủ mọi seed; RF của topic = số seed |
| `REPLICA_A`, `REPLICA_B`, `REPLICA_C` | `.env`, giống nhau ở mọi file | nginx (mọi máy) | `host:port` của bản sao từng node. Máy thật: IP overlay cho cả ba, kể cả máy của chính nginx (`100.64.0.1:8000`, `100.64.0.2:8000`), vì cùng một khối chạy ở mọi máy; một máy: `replica-b:8000` |
| `BRANCH_A`, `BRANCH_B`, `BRANCH_C` | `.env`, giống nhau ở mọi file | nginx (mọi máy) | `host:port` của POS chi nhánh trên từng node. Máy thật: `100.64.0.1:8001`, `100.64.0.2:8001`; một máy: `branch-b:8000` |
| `NGINX_PORT` | `.env` (tuỳ chọn) | compose | Cổng host của nginx (cổng vào) trên máy này, mặc định `80`. Một máy: node A `80`, B `8012`, C `8022` |
| `GATEWAYS` | `.env`, giống nhau ở mọi file của cùng chế độ | nginx (`/lb/gateways.json`) | Mọi cổng vào nhìn từ trình duyệt, phân cách bằng dấu phẩy; dashboard và POS tự chuyển sang cổng kế tiếp khi cổng đang dùng không trả lời (vòng 5). Máy thật: `http://100.64.0.1,http://100.64.0.2,http://100.64.0.3`; một máy: `http://localhost,http://localhost:8012,http://localhost:8022` |
| `WAN_IP_PREFIX` | `infra/env/local-<x>.env` (chỉ một máy) | compose (`infra/compose.local.yml`) | Tiền tố IP cố định của các container node này trên `minigo-wan`: A `10.210.0.1`, B `10.210.0.2`, C `10.210.0.3`; service thứ n có IP `<tiền tố><n>` (vd. `10.210.0.21`). Vùng IP động của mạng là `10.210.0.128/25`, không đụng IP cố định |
| `BRANCH_PORT`, `REPLICA_PORT` | `.env` (tuỳ chọn) | compose | Cổng host của POS và dashboard, mặc định `8001`, `8000`. Một máy: node B `8011`, `8010`; node C `8021`, `8020` |
| `NODE_NAME` | `.env` | `replica_api`, `sink` | Tên bản sao `A`, `B`, `C`; consumer group là `replica-<NODE_NAME>` |
| `BRANCH_ID` | `.env` | `branch_api`, `relay` | Số chi nhánh `1`, `2`, `3` |
| `BRANCH_NAME` | `.env` (tuỳ chọn) | `branch_api` | Tên hiển thị, mặc định `Chi nhánh <BRANCH_ID>` |
| `KAFKA_BROKERS` | `.env`, giống nhau ở mọi file | `relay`, `sink`, `console`, `topic-init` | Cả ba broker, cổng `19092`, cùng host và thứ tự với `BROKER_SEEDS`: `100.64.0.1:19092,100.64.0.2:19092,100.64.0.3:19092`; một máy: `redpanda-a:19092,redpanda-b:19092,redpanda-c:19092` |
| `REPLICA_URLS` | `.env` | `branch_api`, `replica_api` | Mọi bản sao: `A=http://replica_api:8000,B=http://100.64.0.2:8000,C=...`; một máy: `A=http://replica-a:8000,...`. Chi nhánh gửi heartbeat tới tất cả; bản sao gossip với các bản sao còn lại (bỏ dòng trùng `NODE_NAME`) |
| `BRANCH_URL` | `.env`, riêng từng máy | `branch_api` | Địa chỉ POS của chính chi nhánh này, nhìn từ máy khác; gửi kèm heartbeat để bản sao đối soát khi mất broker. Máy thật: `http://100.64.0.2:8001` (IP overlay của chính máy, cổng host); một máy: `http://branch-b:8000` |

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
Redpanda mỗi 5 giây (`sink_stats.broker_ok`, `lag`), dashboard hiện riêng "Đồng bộ dừng từ HH:MM:SS". Heartbeat mang
kèm `branch_url`: mất broker quá 15 giây thì bản sao dùng địa chỉ này để đối soát thẳng với chi nhánh.

**Bộ phát hiện lỗi** (vòng 5, PT-13). Mỗi bản sao tự đánh giá từng chi nhánh theo tuổi heartbeat của chính nó
(`now() - last_seen`, một đồng hồ): dưới 8 giây (`SUSPECT_AFTER_S`, tức đã lỡ ít nhất một nhịp 5 giây) là
**ONLINE**, từ 8 đến dưới 15 giây là **SUSPECT**, từ 15 giây (`NODE_TIMEOUT_S`) là **OFFLINE**. Góc nhìn này phục vụ ở
`GET /api/views`; mỗi bản sao kéo góc nhìn của các bản sao khác mỗi 5 giây (`view_loop`), lưu vào `peer_view`, bỏ
góc nhìn cũ quá 15 giây. **Kết luận theo đa số** trên tổng số bản sao cấu hình (3, cần 2): đủ 2 góc nhìn OFFLINE thì
OFFLINE, đủ 2 góc nhìn ONLINE thì ONLINE, còn lại SUSPECT ("nghi ngờ, chưa đủ đa số"); góc nhìn thiếu hoặc cũ không
tính là OFFLINE. Nhờ vậy bản sao bị cô lập (K3) không tự kết luận được chi nhánh khác đã chết. Timeout không phân biệt
được chậm với chết (K14). `RECOVERING` (chi nhánh tự báo đang phục hồi) dành cho vòng 6. Đối soát vẫn theo góc nhìn
của chính bản sao (chi nhánh không OFFLINE), không theo đa số.

## 5. Mức nhất quán

- **Nhất quán cuối** (eventual consistency), không phải nhất quán mạnh. "Thời gian thực" nghĩa là trễ 1–2 giây, và
  con số trễ hiện ngay trên dashboard.
- Muốn nhất quán mạnh thì mỗi lượt bán phải chờ mọi máy xác nhận; mất mạng là ngừng bán. Hệ chọn **sẵn sàng hơn
  nhất quán** (đánh đổi CAP).
- Thứ tự sự kiện dựa vào `movement_id` do chi nhánh cấp tăng dần, **không** dựa vào đồng hồ (đồng hồ các máy lệch nhau).
- **Đọc đơn điệu (monotonic reads) trên dashboard** (vòng 4, K11). Đây là mô hình nhất quán lấy client làm trung tâm
  (Tanenbaum 7.3): một tiến trình đã đọc giá trị của x thì các lần đọc x sau phải ra cùng giá trị hoặc mới hơn. Ở
  đây tiến trình là một tab dashboard, mục dữ liệu là ô (chi nhánh, mã hàng), phiên bản là `last_movement` do chính
  chi nhánh cấp (không dùng đồng hồ, PT-05). Tab nhớ phản hồi đang hiện (đóng vai "tập đã đọc" trong sách); phản
  hồi mới chỉ được nhận khi **mọi ô** có `last_movement` lớn hơn hoặc bằng ô đang hiện, không thì giữ nguyên màn hình
  cũ (cả một phản hồi, không trộn số của hai bản sao) và gắn nhãn "Bản sao B trễ N sự kiện ở CN2" (N = hiệu
  `movement_id` lớn nhất của chi nhánh đó; bằng nhau mà vẫn có ô cũ hơn thì ghi "trễ k ô"). So từng ô chứ không chỉ
  `movement_id` lớn nhất của chi nhánh, vì bản sao có thể lỡ #57 (mã 3) mà đã nhận #58 (mã 4) (K8).
- Phạm vi bảo đảm: một lần mở trang. Tải lại trang (F5) là phiên mới. Bộ đếm, danh sách sự kiện, dòng đồng bộ đi
  cùng phản hồi được nhận; vệt "bản sao nào trả lời" vẫn ghi mọi lần (ô vàng = trả lời trễ, giữ số cũ). Gọi thẳng
  API (`curl`) hay mở thẳng một bản sao thì không qua lớp này; một bản sao tự nó không bao giờ lùi số vì
  `merge_cells` chỉ ghi đè khi `movement_id` mới hơn.

## 6. Giới hạn

- **Cổng vào chỉ tự chuyển cho trang ĐANG MỞ** (vòng 5, K13). Mở trang mới khi cổng quen thuộc đã chết thì người
  dùng vẫn phải tự gõ địa chỉ cổng khác (`http://<IP máy B>/`). Bản production dùng một tên DNS trỏ nhiều địa chỉ
  (nhiều bản ghi A, hoặc VIP/anycast trước các nginx) để cả lần mở đầu cũng không phụ thuộc một máy; ghi vào "kiến
  trúc mục tiêu production" (vòng 7). CORS ở nginx cho mọi origin (`*`) vì không có cookie hay xác thực, chỉ hợp cho
  demo trong mạng riêng; production liệt kê đúng các origin. Chế độ một máy: cổng host không đi qua `minigo-wan`, nên
  `make cut N=a` KHÔNG làm trình duyệt mất cổng A (nginx A vẫn trả lời, chỉ thấy phía bị cô lập); K13 một máy dùng
  `make kill`/`make pause` nginx A. Trên máy thật, rút mạng máy A thì trình duyệt máy khác mất cổng A thật.
- **Bộ phát hiện lỗi chỉ dựa vào timeout** (vòng 5, K14): không phân biệt được chi nhánh chậm (`docker pause`) với
  chết; cả hai đi qua SUSPECT rồi OFFLINE. Kết luận đa số tính trên tổng số bản sao cấu hình: chết 2/3 bản sao thì
  bản sao còn lại không bao giờ kết luận OFFLINE được (chỉ "nghi ngờ"), đổi lại bản sao bị cô lập không tự kết luận
  sai. Kết luận chậm hơn góc nhìn riêng tới khoảng 5–10 giây (kéo góc nhìn mỗi 5 giây).
- **Cụm broker chịu được mất 1 trong 3 broker** (K7a). Mất đa số (2/3) thì đồng bộ dừng cho tới khi có lại đa số;
  quầy vẫn bán, outbox giữ sự kiện, POS và dashboard báo "đồng bộ dừng"; sau 15 giây bản sao đối soát thẳng với
  chi nhánh nên số tồn vẫn đúng, dashboard ghi "đang đối soát thẳng với chi nhánh" (K7b, K9). Trong lúc bầu leader mới (vài giây)
  dashboard có thể báo "đồng bộ dừng" ngắn rồi tự hết.
- **Chỉ có 2 máy thật thì broker vẫn là điểm chết**: Redpanda chỉ nhận RF lẻ và cụm 2 broker không chịu được lỗi
  nào, nên chỉ máy A chạy broker, RF=1 (`docs/demo.md` mục 2).
- **Mất dữ liệu broker** (xoá volume, hỏng đĩa trên đa số broker): sự kiện bản sao chưa kịp đọc mất hẳn khỏi
  Redpanda, nhưng **số tồn** vẫn được dựng lại: gossip lấy từ bản sao đã đọc kịp, đối soát lấy từ chi nhánh. Phần
  không dựng lại được là **nhật ký** (`event_log`) của các sự kiện đó.
- **Ô vá qua gossip hoặc đối soát không có dòng `event_log`**: ta chỉ biết số tồn mới nhất của ô, không biết các lượt
  bán ở giữa. Hệ quả: danh sách "Sự kiện vừa nhận" thiếu các lượt đó cho tới khi sink nhận được (nếu còn trên
  Redpanda); `processed` của bản sao đã lỡ sự kiện thấp hơn bản sao khác **mãi mãi** (K8), dù dấu vân tay khớp.
- **Gossip chỉ kéo, so dấu vân tay 8 ký tự hex, kéo cả snapshot** (60 ô, không Merkle tree): đủ cho demo; hàng nghìn
  mã hàng thì cần chia nhỏ theo chi nhánh hoặc cây băm. Một bản sao chết không làm treo gossip (mỗi bản sao khác một
  luồng, timeout 2 giây).
- **Đối soát chỉ bật khi mất broker quá 15 giây** và chỉ với chi nhánh còn heartbeat; chi nhánh mất liên lạc cả HTTP
  thì không đối soát được. Sink chết (không còn kiểm broker) thì không đối soát; gossip lo phần vá.
- **Dữ liệu mỗi chi nhánh chỉ có một bản chính**, ở chính máy chi nhánh. Bản sao trung tâm chỉ là bản tổng hợp để
  đọc. Máy B hỏng ổ cứng thì mất các lượt bán chưa kịp gửi đi.
- **Sơ đồ topology chỉ là góc nhìn ghép từ những gì hỏi được** (vòng 4): mở qua nginx thì ghép digest của mọi bản
  sao và `/cn<N>/api/status` của mọi chi nhánh; mở thẳng một bản sao thì chỉ có góc nhìn của bản sao đó, phần còn lại
  tô xám "không biết". Trạng thái từng broker lấy từ metadata mà sink thấy (`sink_stats.brokers_up`), chỉ tính sink
  đang đọc được cụm: node bị cô lập vẫn hỏi được broker thiểu số của nó nhưng nhận danh sách cũ (đo ở K3, K7c). Mất
  đa số thì không sink nào hỏi được metadata, sơ đồ ghi "cụm: không hỏi được" chứ không biết broker nào còn sống. Vài
  chục giây sau khi một broker dừng, các sink có thể thấy danh sách khác nhau (broker còn sống hiện vàng "k/3 sink
  thấy"); broker đã dừng thì luôn đỏ "0/n".
- **Mốc thời gian khi truy vết theo ba đồng hồ** (chi nhánh: `node_time`, `outbox.sent_at`; broker leader:
  `kafka_ts`, topic `LogAppendTime`; bản sao: `received_at`, `updated_at`): chỉ để hiển thị, không so thứ tự (PT-05).
  Trên máy thật các đồng hồ lệch nhau nên hiệu giữa hai mốc khác máy có thể âm. Ô vá bằng gossip hoặc đối soát không
  có dòng nhật ký, nên với bản sao đó chỉ biết "đã vá tới #N lúc nào", không biết mốc riêng của từng lượt bán.
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
| Phổ kiến trúc | Phi tập trung ở phần bán hàng, broker (cụm 3 máy), cổng vào (nginx mọi máy, client tự chuyển cổng) và phát hiện lỗi (kết luận theo đa số bản sao ngang hàng, không có HQ điều phối) |

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
| PT-07 | Bản sao chỉ đọc: không ghi về chi nhánh, không gọi thẳng CSDL chi nhánh | `api/services/replica.py`; đối soát chỉ `GET /api/snapshot` (`api/workers/gossip.py`), chi nhánh trả bằng một câu `SELECT` (`snapshot` trong `api/services/branch.py`) |
| PT-08 | Nginx chỉ tự thử lại yêu cầu idempotent; lệnh bán chống trừ hai lần bằng `request_id` | nginx, `_change_stock` |
| PT-09 | Không bán lố tồn: trừ bằng một câu `UPDATE` có điều kiện `qty_on_hand + delta >= 0` | `_change_stock` |
| PT-10 | Mọi kênh cập nhật snapshot (sink, gossip, đối soát) dùng chung một luật merge giao hoán, lũy đẳng theo từng ô | `merge_cells` (`api/services/replica.py`), gọi từ `apply_event`, `merge_replica_snapshot`, `merge_branch_snapshot` |
| PT-11 | Mất đa số broker không làm dừng bán; trạng thái "đồng bộ dừng" phải hiện trên POS và dashboard | `record_relay_result` (`relay_status`), `record_broker_check` (`sink_stats`), `web/pos.html`, `web/dashboard.html` |
| PT-13 | Một chi nhánh chỉ bị coi là OFFLINE khi đa số bản sao, tính trên **tổng số bản sao cấu hình** (2/3), cùng thấy OFFLINE; góc nhìn thiếu hoặc cũ quá 15 giây không tính là OFFLINE. Một bản sao mất liên lạc riêng lẻ chỉ đổi góc nhìn của chính nó | `branch_state`, `majority_state`, `query_nodes` (`api/services/replica.py`); góc nhìn bản sao khác kéo qua `GET /api/views` (`view_loop` trong `api/workers/gossip.py`), lưu ở `peer_view` |
