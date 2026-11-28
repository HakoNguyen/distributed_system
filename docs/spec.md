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
| Chi nhánh sập vẫn bán (hinted handoff, store-and-forward) | POS ghi hộ lượt bán lên một bản sao khi đa số kết luận chi nhánh OFFLINE; chi nhánh khởi động lại ở RECOVERING, tự kéo về áp đúng một lần theo thứ tự, lượt vượt tồn thật thành REJECTED và hiện ra (PT-14) | K15 |
| Nhân bản CSDL chi nhánh, chuyển primary (replication, failover, fencing) | Mỗi node một standby (streaming replication của Postgres). Mất primary: `make promote` fence primary cũ rồi nâng standby; chi nhánh tự nối sang qua chuỗi nhiều host. Đồng bộ (`synchronous_commit=on`): không mất lượt bán đã báo thành công (PT-12); mặc định bất đồng bộ (PACELC: chọn độ trễ thấp và quầy không treo, RPO > 0) | K10a, K10b, K10c |
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

Mọi máy chạy **giống hệt nhau**: một chi nhánh (`branch_db` kèm standby `branch_db_standby` từ vòng 7, `branch_api`,
`relay`), một bản sao trung tâm
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
| `DATABASE_URL` | `infra/compose.yml` | mọi tiến trình Python | CSDL của chính tiến trình. Chi nhánh (vòng 7): chuỗi nhiều host `postgresql://app:${DB_PASSWORD}@branch_db:5432,branch_db_standby:5432/kho?target_session_attrs=read-write&connect_timeout=3` (libpq thử lần lượt, chỉ nhận host đang là primary); bản sao: `postgresql://app:${DB_PASSWORD}@replica_db:5432/kho` |
| `DB_PASSWORD` | máy thật: `.env`; một máy: `infra/env/local-secrets.env` (không commit, `make local-up` tự sinh lần đầu) | compose (Postgres, `DATABASE_URL`) | Mật khẩu user `app` của mọi CSDL (vòng 7). Thiếu thì compose dừng với "Chưa đặt DB_PASSWORD". Mẫu: `infra/env/secrets.env.example` |
| `REPLICATION_PASSWORD` | như `DB_PASSWORD` | compose (`branch_db`, `branch_db_standby`) | Mật khẩu user `replicator` (streaming replication, vòng 7) |
| `PG_PRIMARY_HOST` | `infra/compose.yml` | `db/pg-start.sh` của `branch_db_standby` | Nguồn `pg_basebackup` lần đầu (thư mục dữ liệu trống): `branch_db` (vòng 7) |
| `TEST_DB_URL` | `infra/compose.test.yml` | `tests/conftest.py` | CSDL test, tên phải kết thúc bằng `_test`: `postgresql://app:app@test_db:5432/kho_test` (giữ mật khẩu cố định: tmpfs, không publish cổng) |

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
được chậm với chết (K14). Đối soát vẫn theo góc nhìn của chính bản sao (chi nhánh không OFFLINE), không theo đa số.

**Ghi hộ và RECOVERING** (vòng 6, PT-14, K15). Server chi nhánh sập thì quầy bán tiếp bằng **ghi hộ** (hinted
handoff): POS mở qua cổng vào (`/cnX/` lỗi thì nginx trả chính trang POS, `@pos_page`) thấy chi nhánh lỗi 2 lần liên
tiếp **và** kết luận đa số của bản sao sẽ ghi hộ (`/replica/<X>/api/nodes`) là OFFLINE thì gửi lượt bán (chỉ SALE)
lên MỘT bản sao (`/replica/<X>/api/handoff`, thứ tự A, B, C, chỉ chuyển bản sao khi lỗi mạng hoặc 5xx, giữ
`request_id`). Kết luận mới là SUSPECT thì POS chờ (khoá Thanh
toán), không ghi hộ. Bản sao tự kiểm lại: chỉ nhận khi kết luận của chính nó là OFFLINE (409 `branch_not_offline`), và
khi "tồn tạm tính" = snapshot trừ các lượt ghi hộ PENDING ở bản sao đó còn đủ.
Chi nhánh khởi động luôn ở **RECOVERING**: chưa nhận bán, nhập (503 `branch_recovering`); luồng `recovery_loop` mỗi
2 giây **tự kéo** ghi hộ từ mọi bản sao (`GET /api/handoff`, PT-07 giữ nguyên), áp theo thứ tự (thứ tự bản sao trong
`REPLICA_URLS`, rồi `handoff_id` do bản sao cấp; không dùng đồng hồ) qua đúng đường bán hàng (`change_stock`,
`request_id` chống trùng), lượt không đủ tồn thật thì REJECTED; commit xong mới báo bản sao (`POST /api/handoff/ack`).
Lên **ONLINE** khi mọi bản sao trả lời, không bản nào còn lượt PENDING và không bản nào còn nhận ghi hộ (`accepting`:
kết luận của bản sao đó vẫn là OFFLINE). Hết 60 giây mà vẫn có bản sao không gọi được thì tự ONLINE kèm cảnh báo
`incomplete`. Đang ONLINE mà một bản sao gọi được có PENDING hoặc còn `accepting` thì quay lại RECOVERING; lượt bán chỉ
được nhận khi luồng phục hồi đã chạy trong 10 giây gần nhất (chặn lượt bán chen vào ngay sau `docker unpause`).
RECOVERING là cờ chi nhánh tự báo trong heartbeat (`recovering`), tách khỏi ONLINE/SUSPECT/OFFLINE theo timeout:
kết luận đa số (PT-13) không đổi.

**Standby CSDL chi nhánh** (vòng 7, PT-12, K10a–K10c; chi tiết ở `docs/db.md` mục 2). Mỗi node có hai Postgres chi
nhánh nối nhau bằng streaming replication. `branch_api` và `relay` nối bằng chuỗi nhiều host
(`branch_db,branch_db_standby`, `target_session_attrs=read-write`): libpq bỏ qua host không phải primary. Mặc định bất
đồng bộ: COMMIT xong ở primary là trả lời, WAL sang standby sau vài mili giây. `make sync-mode MODE=sync` bật đồng bộ
(`synchronous_standby_names='*'`, `synchronous_commit=on`): COMMIT chỉ trả lời khi standby đã ghi WAL xuống đĩa, và lượt
bán chưa hiện ra cho phiên khác (kể cả relay) trước lúc đó. Mất primary thì người vận hành chạy `make promote`: **fence
trước** (primary cũ bị giết, không tự khởi động lại, file `minigo.fenced` trong volume làm nó thoát ngay nếu bị bật lại),
**promote sau**, nhảy sequence `movement_id` thêm 1000, đặt bất đồng bộ (primary mới chưa có standby). Pool kiểm kết nối
lúc lấy ra (`check`), nên lượt bán đầu tiên sau promote đã chạy trên primary mới. Lượt bán đứt giữa chừng trả 503
`db_unavailable`; POS giữ `request_id` với mọi lỗi 5xx và gửi lại thì nhận kết quả cũ (PT-08). Promote quá 15 giây thì
heartbeat (đọc outbox) dừng đủ lâu để đa số kết luận OFFLINE: POS chuyển sang ghi hộ, chi nhánh tự vào RECOVERING khi
có CSDL lại (vòng 6, không đổi code); ghi hộ là lớp bảo vệ thứ hai. `make rejoin` đưa primary cũ về làm standby
(`pg_basebackup`).

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
  đọc (ghi hộ, vòng 6, chỉ giữ tạm lượt bán khi chi nhánh chết, không phải bản sao của tồn). Máy B hỏng ổ cứng thì mất
  các lượt bán chưa kịp gửi đi.
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
- **Ghi hộ: hai nơi cùng ghi khi mạng bị chia cắt** (vòng 6, K15 biến thể). Phân vùng mạng làm POS (qua cổng vào)
  không gọi được chi nhánh trong khi chi nhánh vẫn sống và vẫn bán ở quầy mở thẳng: đa số bản sao kết luận OFFLINE,
  POS ghi hộ, hai nơi cùng ghi. Có thể bán quá tồn; chỉ phát hiện lúc chi nhánh áp lại (lượt thừa thành REJECTED, hiện
  trên POS và dashboard). PT-13 làm giảm khả năng này (một đường hỏng riêng lẻ không đủ) nhưng không loại bỏ: chi
  nhánh bị cô lập không biết đa số đã kết luận nó chết. Cách triệt để là **lease kèm fencing token** (chi nhánh chỉ
  được ghi khi còn lease do đa số cấp, mỗi lease một số tăng dần, lượt ghi kèm số cũ bị từ chối); ghi vào "kiến trúc
  mục tiêu production" (vòng 7). Đo ở K15 biến thể: sau `heal`, chi nhánh vào RECOVERING, lượt thừa thành REJECTED.
- **Tồn tạm tính chỉ tính ghi hộ ở chính bản sao đó**: POS dồn ghi hộ về một bản sao; chỉ khi bản sao đó lỗi giữa
  chừng thì ghi hộ rải sang bản sao khác, và bản sao sau không trừ các lượt PENDING ở bản sao trước, nên có thể nhận
  quá tồn. Tồn tạm tính còn dựa vào snapshot, mà snapshot thiếu các lượt bán chi nhánh chưa kịp gửi lên trước khi
  chết. Cả hai trường hợp đều chỉ lộ ra lúc áp lại: lượt thừa thành REJECTED. Dashboard cộng số ghi hộ qua digest các
  bản sao nên một lượt nằm ở hai bản sao bị đếm hai lần.
- **Ngoại lệ của PT-14: hết 60 giây phục hồi** (`RECOVERY_TIMEOUT_S`). Chi nhánh khởi động lại mà vẫn có bản sao không
  gọi được thì sau 60 giây tự ONLINE kèm cảnh báo `incomplete` (POS, dashboard), để một bản sao chết không làm quầy
  dừng mãi. Ghi hộ còn nằm ở bản sao đó (nếu có) được áp muộn khi gọi lại được, nghĩa là sau các lượt bán mới; có thể
  bị REJECTED. Chờ mãi thì đúng hơn nhưng quầy dừng theo bản sao.
- **Chỉ POS mở qua cổng vào mới ghi hộ được**: mở thẳng chi nhánh (`:8001`) thì chi nhánh chết là không mở được trang.
  Khởi động lại (cả `docker pause`/`unpause`, `make heal` sau khi đa số đã kết luận OFFLINE) thì chi nhánh ở
  RECOVERING vài giây tới khi mọi bản sao thôi kết luận OFFLINE, kể cả khi không có ghi hộ nào (đo ở `docs/demo.md`
  K4, K14). Trạng thái phục hồi nằm trong bộ nhớ `branch_api`: chỉ `branch_db` chết còn `branch_api` sống thì chi
  nhánh phát hiện ghi hộ trong lần kéo kế tiếp (≤ 2 giây), không có kịch bản riêng.
- **Cảnh báo và nhật ký sự cố tính ở trình duyệt** (vòng 6b, danh mục ở `docs/demo.md` mục 5, "Danh mục cảnh
  báo"). Mốc "từ" lấy từ server khi có, không thì là lúc trang thấy lần đầu (ghi "~"). Nhật ký lưu `localStorage`: mỗi
  trình duyệt một nhật ký, sự cố xảy ra khi không có trang nào mở thì không có trong nhật ký. Mở thẳng một bản sao thì
  chỉ có cảnh báo từ góc nhìn của bản sao đó (không phân biệt được "cụm mất đa số" với "bản sao này bị cô lập").
- **Một máy vẫn là một miền lỗi** (vòng 7). Primary và standby chạy trên cùng máy, cùng đĩa, cùng Docker: mất máy, hỏng
  đĩa, Docker Desktop chết là mất cả hai. Standby che được lỗi của một tiến trình hay một volume Postgres, không che
  được lỗi của máy. Vòng 7 cải thiện độ bền dữ liệu và cách vận hành, không biến một máy thành hệ sẵn sàng cao.
- **Mặc định bất đồng bộ: RPO > 0** (vòng 7, K10b). Lượt bán đã báo thành công mà chưa sang standby thì mất khi primary
  hỏng rồi promote (đo: cắt mạng standby, bán 7 lượt, mất primary, promote: thiếu đúng 7). Hệ quả thứ hai là **sự kiện
  "ma"**: relay đọc outbox trên primary, nên có thể đã gửi lên Redpanda các lượt đó; bản sao trung tâm giữ chúng còn chi
  nhánh thì không. Bước nhảy sequence lúc promote (+1000) chặn việc cấp lại `movement_id` cho lượt bán khác (nếu cấp lại
  thì bản sao bỏ lượt mới vì trùng khoá `(branch_id, movement_id)`). Ô của sự kiện ma đứng sai tới lượt bán kế tiếp của
  mã đó (lượt đó có `movement_id` lớn hơn nên ghi đè đúng); đối soát không vá được, vì `last_movement` của ma lớn hơn của
  chi nhánh mà luật merge chỉ ghi đè khi lớn hơn (PT-05, PT-10). Cách triệt để: CDC đọc WAL đã sang standby (mục 9). Ở
  chế độ đồng bộ không có sự kiện ma.
- **Chế độ đồng bộ: standby chết thì quầy treo** (K10b). Lượt bán chờ standby không giới hạn (Postgres không có timeout
  cho chờ đồng bộ); treo đủ lâu thì pool (5 kết nối) cạn, heartbeat dừng, đa số kết luận OFFLINE. Người vận hành chạy
  `make sync-mode MODE=async`: các lượt đang chờ xong ngay. Tự hạ cấp (như Patroni) ghi ở mục 9.
- **Chuyển primary bằng tay** (`make promote`). Từ lúc primary chết tới khi promote xong, lượt bán chờ pool rồi lỗi (POS
  báo "chưa rõ đã ghi chưa", giữ `request_id`). Đo ở K10a: 11 giây không bán được (3 giây gõ lệnh, 7 giây `make
  promote`, gồm các lệnh docker). Tự động failover cần đồng thuận để tránh hai primary (Patroni + etcd, mục 9).
- **Fencing dựa vào Docker trên cùng máy**: `docker kill` primary cũ và file `minigo.fenced` trong volume. Primary và
  standby ở hai máy khác nhau thì phải có STONITH thật (tắt nguồn, cắt mạng) hoặc lease kèm fencing token (mục 9). Khi
  `branch_db` đang bị fence, `make local-up` báo lỗi ở node đó (`branch_api` chờ `branch_db` healthy) và compose có thể
  tạo lại container `branch_db` (khởi động lại liên tục, mỗi lần đều thoát vì file fence): chạy `make rejoin` trước.
- **Mật khẩu qua biến môi trường** (vòng 7): không còn viết cứng, file bí mật không commit, nhưng vẫn lộ qua `docker
  inspect`; mật khẩu replication nằm trong `postgresql.auto.conf` của standby (`pg_basebackup -R`). CSDL test giữ
  `app/app` (tmpfs, không publish cổng). Docker secrets hay kho bí mật ở mục 9.
- **Healthcheck chỉ kiểm "tiến trình còn sống"** (vòng 7): `branch_api`, `replica_api` gọi trang tĩnh `/`, relay, sink
  kiểm file `/tmp/alive` mà vòng lặp chạm mỗi lượt; lỗi broker, CSDL, mạng không làm container unhealthy. Docker
  Compose không tự khởi động lại container unhealthy; healthcheck dùng cho `depends_on` và để người vận hành nhìn.
- **Sao lưu là `pg_dump` logic** (`make backup`), không khôi phục được tới một thời điểm bất kỳ (PITR cần lưu WAL, mục 9).
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
| PT-12 | Ở chế độ đồng bộ (`make sync-mode MODE=sync`: `synchronous_standby_names='*'`, `synchronous_commit=on`), lượt bán chỉ báo thành công khi standby đã nhận và ghi xuống đĩa WAL của nó; mất primary rồi promote standby thì không mất lượt bán nào đã báo thành công. Mặc định là bất đồng bộ (giữ PT-01: standby chết quầy vẫn bán), khi đó RPO > 0 (mục 6) | cấu hình Postgres (`scripts/db.sh sync-mode`); chứng minh bằng `scripts/k10.sh verify` (K10a); lượt bán lỗi giữa chừng trả 503 `db_unavailable` và POS giữ `request_id` (PT-08) |
| PT-13 | Một chi nhánh chỉ bị coi là OFFLINE khi đa số bản sao, tính trên **tổng số bản sao cấu hình** (2/3), cùng thấy OFFLINE; góc nhìn thiếu hoặc cũ quá 15 giây không tính là OFFLINE. Một bản sao mất liên lạc riêng lẻ chỉ đổi góc nhìn của chính nó | `branch_state`, `majority_state`, `query_nodes` (`api/services/replica.py`); góc nhìn bản sao khác kéo qua `GET /api/views` (`view_loop` trong `api/workers/gossip.py`), lưu ở `peer_view` |
| PT-14 | Mỗi lượt ghi hộ được áp vào chi nhánh **đúng một lần**, theo thứ tự ghi hộ (thứ tự bản sao trong `REPLICA_URLS`, rồi `handoff_id`), **trước khi** chi nhánh nhận lượt bán mới; lượt không áp được thì REJECTED và hiện ra (POS, dashboard), không mất lặng lẽ. Ngoại lệ duy nhất: hết 60 giây (`RECOVERY_TIMEOUT_S`) mà vẫn có bản sao không gọi được thì chi nhánh lên ONLINE kèm cảnh báo `incomplete`; ghi hộ còn ở bản sao đó được áp muộn khi gọi lại được, theo cùng luật (mục 6) | `require_online`, `next_recovery_state`, `collect_handoffs`, `apply_handoffs`, `recovery_once` (`api/services/branch.py`), gọi từ `api/workers/recovery.py`; `store_handoff`, `record_handoff_ack` (`api/services/replica.py`) |

## 9. Kiến trúc mục tiêu production (trên giấy)

MiniGo chạy mọi thứ trên 1–3 máy bằng Docker Compose để chứng minh các tính chất ở mục 2. Bản production cho một chuỗi
cửa hàng thật sẽ khác ở các chỗ dưới đây. Không làm trong demo vì không trả lời thêm câu hỏi nào của môn, hoặc cần hạ
tầng không có trên một máy (vòng 7, `docs/plan.md`).

```
              Trình duyệt trụ sở, POS ── DNS nhiều bản ghi A / anycast ──┐
                                                                         ▼
 ┌──────── CORE (cloud / datacenter, nhiều vùng) ───────────────────────────────────────────────┐
 │  LB kép (VIP) ─▶ nginx/ingress ─▶ replica_api (Kubernetes, nhiều vùng)                        │
 │  Kafka/Redpanda nhiều vùng (Raft)   replica_db có HA (Patroni)   Prometheus, Grafana, Vault    │
 └──────────────────────────────▲──────────────────────────────────────────────────────────────┘
                                │ mTLS, TLS, khoá riêng từng chi nhánh
 ┌──────── EDGE (mỗi cửa hàng, K3s hoặc Compose, triển khai hàng loạt bằng Ansible) ────────────┐
 │  POS (hàng đợi tại máy, gửi lại bằng request_id) ─▶ branch_api ─▶ Postgres primary            │
 │                                                    Patroni + standby (đồng bộ, tự hạ cấp)     │
 │  CDC (Debezium đọc WAL đã sang standby) thay relay ─▶ Kafka core                              │
 └──────────────────────────────────────────────────────────────────────────────────────────────┘
```

| Ý | MiniGo hiện tại | Production | Đánh đổi, vì sao demo chưa làm |
|---|---|---|---|
| Tách edge/core | Mỗi máy chạy đủ chi nhánh, bản sao, broker, nginx | Cửa hàng chỉ chạy `branch_db`, `branch_api`, relay/CDC; bản sao, broker, nginx ở cloud hoặc datacenter rải nhiều vùng: một cửa hàng mất mạng không làm cụm mất quorum | Code đã tách theo `ROLE` và `.env`, chủ yếu đổi compose; demo cần mỗi máy đủ vai để cho thấy failover trên 3 máy |
| CDC thay relay | Relay đọc bảng outbox trên primary (at-least-once) | Debezium đọc WAL qua logical slot, chỉ phát phần đã sang standby (failover slot, PG 17) | Hết sự kiện "ma" sau promote (mục 6). Cần Kafka Connect, slot, thêm một hệ phải vận hành |
| Tự động failover CSDL | `make promote` bằng tay, fence bằng `docker kill` | Patroni + etcd/Consul: leader key có TTL (lease), watchdog tự tắt primary mất lease, tự promote, tự đưa primary cũ về bằng `pg_rewind` | Cần cụm đồng thuận riêng; demo muốn thấy rõ từng bước fence, promote |
| Đồng bộ có tự hạ cấp | Đồng bộ chặt hoặc bất đồng bộ, đổi bằng tay | `synchronous_mode` không chặt của Patroni (như semi-sync có timeout của MySQL): mất standby quá T giây thì tự chuyển bất đồng bộ, có lại thì bật đồng bộ | Quầy chỉ treo tối đa T giây; trong lúc hạ cấp RPO > 0 |
| Fencing chống hai nơi cùng ghi | File fence ở CSDL; ghi hộ dựa vào kết luận đa số (mục 6) | Lease do đa số cấp kèm fencing token tăng dần; lượt ghi mang token cũ bị từ chối (cả CSDL lẫn ghi hộ) | Cần dịch vụ cấp lease và kiểm token ở mọi đường ghi |
| Sao lưu | `pg_dump` vào `backups/` | Lưu WAL liên tục (pgBackRest, WAL-G) lên kho đối tượng ở vùng khác, khôi phục tới một thời điểm (PITR), diễn tập khôi phục | Cần kho lưu trữ ngoài máy |
| Kubernetes | Docker Compose, `restart: unless-stopped`, healthcheck chỉ để nhìn | Kubernetes ở core, K3s ở edge: liveness/readiness probe tự khởi động lại, rolling deploy, giới hạn tài nguyên theo pod | Nặng cho một máy; Compose đủ để cho thấy các tính chất |
| Cổng vào | 3 nginx, trang đang mở tự chuyển cổng (mục 3, mục 6) | Một tên DNS trỏ nhiều địa chỉ (nhiều bản ghi A) hoặc VIP/anycast trước LB kép, để cả lần mở trang đầu cũng không phụ thuộc một máy | keepalived/VIP không chạy qua Docker Desktop trên Windows |
| CORS | `*` (không cookie, không xác thực) | Liệt kê đúng origin của các cổng vào | Chỉ đúng khi đã có xác thực |
| Bảo mật đường truyền | HTTP và Postgres không mã hoá, không xác thực nội bộ | TLS cho API và PostgreSQL, mTLS giữa dịch vụ, khoá riêng từng chi nhánh (thu hồi được khi mất máy) | Cần CA, cấp và xoay vòng chứng chỉ |
| Bí mật | Biến môi trường từ file không commit | Docker secrets / Kubernetes Secrets, kho bí mật (Vault) cấp mật khẩu ngắn hạn | Thêm một dịch vụ phải luôn sống |
| Nhiều vùng | Mọi thứ ở 1–3 máy cùng mạng | Bản sao, broker, CSDL trung tâm rải nhiều vùng; một vùng mất vẫn còn đa số | Độ trễ giữa vùng làm chậm Raft, đồng bộ |
| Anti-entropy | Gossip so dấu vân tay toàn bộ, kéo cả snapshot (60 ô) | Merkle tree hoặc dấu vân tay theo từng chi nhánh, chỉ kéo phần lệch | Đủ cho 60 ô; cần khi có hàng nghìn mã |
| Hàng đợi ở máy POS | POS ghi hộ qua trung tâm khi server cửa hàng chết (vòng 6) | POS tự giữ hàng đợi cục bộ, gửi lại bằng `request_id` khi server cửa hàng sống lại | Cần ứng dụng POS có lưu trữ, không chỉ trang web |
| Triển khai hàng loạt, đồng hồ | Chép `.env` bằng tay; đồng hồ chỉ để hiển thị | Ansible / GitOps cho hàng trăm cửa hàng; NTP bắt buộc (đồng hồ vẫn không dùng để so thứ tự, PT-05) | Không cần cho 3 máy |
| Giám sát | Dashboard tự tính cảnh báo ở trình duyệt (vòng 6b) | Prometheus, Grafana, exporter của Postgres, Redpanda; cảnh báo phía server, gửi tới người trực | Cắt khỏi vòng 7 để tập trung vào standby |
| Phạm vi nghiệp vụ | Chỉ phần tồn kho của POS | Giá, thanh toán, hoá đơn, nhiều quầy, phân quyền | Ngoài phạm vi môn học |
