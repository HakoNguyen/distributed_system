# API và giao tiếp giữa các tiến trình

Các kênh giao tiếp:

| Kênh | Từ → tới | Kiểu |
|---|---|---|
| HTTP qua nginx | Trình duyệt → nginx của một node bất kỳ (cổng vào, vòng 5) → bản sao, chi nhánh | Đồng bộ, yêu cầu–phản hồi; cổng không trả lời thì trang tự gọi cổng kế tiếp (`GATEWAYS`) |
| Heartbeat HTTP | `branch_api` → `/api/heartbeat` của MỌI bản sao, mỗi 5 giây | Đồng bộ, không qua broker |
| Sự kiện Redpanda | `relay` → topic `inventory.movement` → mỗi `sink` | Bất đồng bộ, bền, at-least-once |
| Gossip HTTP | `replica_api` → `/api/digest`, `/api/snapshot` của các bản sao khác, mỗi 10 giây | Đồng bộ, chỉ kéo; timeout 2 giây |
| Đối soát HTTP | `replica_api` → `/api/snapshot` của chi nhánh còn sống, chỉ khi mất broker quá 15 giây | Đồng bộ, chỉ đọc (PT-07); timeout 2 giây |
| Góc nhìn HTTP | `replica_api` → `/api/views` của các bản sao khác, mỗi 5 giây (vòng 5, PT-13) | Đồng bộ, chỉ kéo; timeout 2 giây |
| Ghi hộ HTTP | POS → nginx → `/replica/<X>/api/handoff` khi chi nhánh OFFLINE (vòng 6, PT-14) | Đồng bộ; chống trùng bằng `request_id` |
| Phục hồi HTTP | `branch_api` (`recovery_loop`) → `GET /api/handoff`, `POST /api/handoff/ack` của MỌI bản sao, mỗi 2 giây | Đồng bộ, chi nhánh tự kéo (PT-07); timeout 2 giây; ack sau khi commit |

Tài liệu tự sinh: `http://localhost:8001/docs` (chi nhánh), `http://localhost:8000/docs` (bản sao).

## 1. Chi nhánh (`ROLE=branch`, cổng 8001)

| Phương thức | Đường dẫn | Việc làm |
|---|---|---|
| GET | `/` | Màn hình POS (`web/pos.html`) |
| GET | `/health` | Kiểm tra sống, có chạm CSDL |
| GET | `/api/info` | `branch_id`, `branch_name`, tên các bản sao |
| GET | `/api/inventory` | Tồn của chi nhánh, kèm `version` |
| GET | `/api/status` | Số sự kiện chờ trong outbox, `sync_stuck`, `relay`, RTT và tình trạng tới từng bản sao |
| GET | `/api/snapshot` | Tồn kèm biến động mới nhất từng mã, đọc trong một câu lệnh: `{branch_id, cells: [{product_id, qty_on_hand, last_movement, node_time}]}`. Bản sao gọi khi đối soát; chỉ đọc |
| GET | `/api/movement/{movement_id}` | Một dòng sổ cái kèm lúc relay gửi xong: `{branch_id, movement_id, product_id, move_type, qty_delta, qty_after, node_time, sent_at}` (`node_time` = giờ chi nhánh ghi biến động; `sent_at` = `outbox.sent_at`, NULL = chưa gửi). Dashboard gọi qua `/cn<N>/` để truy vết (vòng 4); chỉ đọc (PT-07) |
| POST | `/api/sale` | Bán. Body: `{product_id, qty, version?, request_id?}` |
| POST | `/api/receipt` | Nhập, cùng body |
| POST | `/api/sale/random?count=20` | Bán nhanh `count` đơn ngẫu nhiên (dùng khi demo) |

`/api/sale`, `/api/receipt` trả `{movement_id, product_id, qty_on_hand, version, elapsed_ms}`; gửi lại cùng
`request_id` thì trả kết quả cũ kèm `replayed: true`.

`/api/status` có `relay: {last_ok_at, failing_since, last_error}` (bảng `relay_status`): `failing_since` khác NULL
thì POS hiện "Gửi lên Redpanda: lỗi từ HH:MM:SS".

`/api/status` có `recovery` (vòng 6, PT-14): `{state, since, pending, applied, rejected, incomplete, unreachable,
last_run_at, last_error, rejected_items}`. `state` ∈ `ONLINE`, `RECOVERING`; `since` = lúc vào trạng thái đó;
`pending` = số lượt ghi hộ còn chờ ở lần kéo gần nhất; `applied`, `rejected` = số lượt đã áp, đã từ chối từ khi
`branch_api` khởi động; `incomplete` = đã tự ONLINE vì hết 60 giây mà còn bản sao không gọi được; `unreachable` = tên
các bản sao không gọi được ở lần kéo gần nhất; `last_run_at`, `last_error` = lần chạy gần nhất của `recovery_loop` và
lỗi của lần đó (NULL = chạy được); `rejected_items` = 20 dòng `handoff_rejected` mới nhất (`request_id`,
`product_id`, `qty`, `reason`, `qty_on_hand`, `rejected_at`).

`/api/status` có `db` (vòng 7, PT-12): CSDL mà `branch_api` đang nối (primary hiện tại, qua chuỗi nhiều host),
đọc bằng một câu `SELECT` (`pg_is_in_recovery()`, `synchronous_standby_names`, `pg_stat_replication`,
`pg_control_checkpoint()`): `{role, sync_mode, standby: {connected, state, lag_bytes}, timeline}`. `role` ∈ `primary`,
`standby`; `sync_mode` ∈ `sync` (`synchronous_standby_names` khác rỗng), `async`; `standby.connected` = có standby
đang `streaming`; `state` = trạng thái WAL sender (`streaming`, `catchup`, …; `null` = không có standby nào nối);
`lag_bytes` = WAL standby chưa áp (`null` khi không có); `timeline` tăng 1 sau mỗi lần promote. Không có standby
`streaming` thì POS (P-11) và dashboard (D-21) cảnh báo.

| Mã lỗi | Khi nào |
|---|---|
| 503 `db_unavailable` | Mọi endpoint của chi nhánh khi không nối được CSDL hoặc kết nối đứt giữa chừng (`psycopg.OperationalError`), ví dụ lúc primary chết, trước khi promote (vòng 7). Lượt bán đứt lúc COMMIT có thể đã ghi: chưa rõ, POS giữ `request_id` và gửi lại (PT-08) |
| 404 `product_not_found` | Không có mã hàng |
| 404 `movement_not_found` | `/api/movement/{movement_id}`: không có biến động đó ở chi nhánh này |
| 409 `version_conflict` | Gửi `version` mà tồn đã bị sửa; kèm `current_version` |
| 422 `insufficient_stock` | Bán quá tồn; kèm `qty_on_hand` |
| 503 `branch_recovering` | `/api/sale`, `/api/receipt`, `/api/sale/random` khi chi nhánh đang RECOVERING (vòng 6), hoặc `recovery_loop` chưa chạy trong 10 giây gần nhất (`stale: true`); kèm `stale`. Không ghi gì; lời gọi đọc vẫn được |

## 2. Bản sao trung tâm (`ROLE=replica`, cổng 8000)

Mọi phản hồi có header `X-Served-By: replica-<X>`.

| Phương thức | Đường dẫn | Việc làm |
|---|---|---|
| GET | `/` | Dashboard (`web/dashboard.html`) |
| GET | `/health` | Kiểm tra sống |
| POST | `/api/heartbeat` | Nhận heartbeat. Body: `{branch_id, branch_name, node_time_ms, outbox_backlog, rtt_ms, branch_url, recovering}` (`branch_url` phải bắt đầu bằng `http://` hoặc `https://`; `recovering` mặc định `false`, vòng 6) |
| POST | `/api/handoff` | Ghi hộ một lượt bán cho chi nhánh đang OFFLINE (vòng 6, PT-14). Body: `{branch_id, product_id, qty, request_id}` (`qty` 1–1000, `request_id` bắt buộc). Trả `{node, handoff_id, branch_id, product_id, qty, status, qty_on_hand}` (`qty_on_hand` = tồn tạm tính sau lượt này); gửi lại cùng `request_id` trả lượt cũ kèm `replayed: true` |
| GET | `/api/handoff?branch_id=2` | Ghi hộ của một chi nhánh ở bản sao này: `{node, branch_id, accepting, counts: {pending, applied, rejected}, pending: [{handoff_id, request_id, product_id, qty}], stock: [{product_id, name, unit, reorder_point, qty_on_hand, version}]}`. `accepting` = kết luận đa số của bản sao này là OFFLINE (còn nhận ghi hộ); `pending` xếp theo `handoff_id`; `stock` cùng dạng `/api/inventory` của chi nhánh, `qty_on_hand` = tồn tạm tính, `version` = null. Chi nhánh kéo khi phục hồi, POS đọc khi ghi hộ. Chỉ đọc |
| POST | `/api/handoff/ack` | Chi nhánh báo kết quả áp, sau khi đã commit. Body: `{branch_id, results: [{handoff_id, status, movement_id, reason}]}`, `status` ∈ `APPLIED`, `REJECTED`. Chỉ đổi lượt còn PENDING của đúng chi nhánh đó; trả `{node, updated}` |
| GET | `/api/overview` | Mọi thứ dashboard cần trong một lần gọi: `served_by`, `nodes`, `inventory`, `events`, `digest` |
| GET | `/api/digest` | Dấu vân tay, tổng tồn, `last_movement_by_branch`, bộ đếm và trạng thái broker của sink, `sync_peers` |
| GET | `/api/snapshot` | Mọi ô của bảng tổng hợp, để bản sao khác gossip: `{node, cells: [{branch_id, product_id, qty_on_hand, last_movement, node_time}]}` |
| GET | `/api/views` | Góc nhìn của bản sao này về từng chi nhánh, để bản sao khác kết luận theo đa số (vòng 5, PT-13): `{node, branches: [{branch_id, state, seconds_since_seen}]}`, `state` ∈ `ONLINE`, `SUSPECT`, `OFFLINE` (ngưỡng ở `docs/spec.md` mục 4). Chỉ đọc |
| GET | `/api/trace?branch_id=2&movement_id=57&product_id=3` | Bản sao này biết sự kiện đó thế nào, để truy vết (vòng 4); xem dưới |
| GET | `/api/nodes`, `/api/inventory`, `/api/events?limit=30`, `/api/stats` | Từng phần của overview, để gọi bằng tay |

`/api/stats` (và `digest` trong `/api/digest`, `/api/overview`): `processed`, `duplicates`, `last_event_at`,
`broker_ok`, `broker_lost_at`, `lag`, `broker_checked_at`, `brokers_up` (cột `sink_stats`, `docs/db.md` mục 3).
`broker_ok = false` thì dashboard hiện "Đồng bộ dừng từ HH:MM:SS"; chi nhánh vẫn "còn sống" nếu heartbeat còn tới.
`brokers_up` (mảng mã broker sink thấy còn sống, NULL = không hỏi được) cho sơ đồ topology tô từng broker; dashboard
chỉ tính `brokers_up` của sink còn chạy và đang đọc được cụm (`broker_ok = true`), vì node bị cô lập nhận danh sách cũ
từ broker thiểu số của nó (`docs/spec.md` mục 6).

`sync_peers` (trong digest): các dòng `sync_peer` (`peer`, `channel`, `last_ok_at`, `failing_since`, `last_error`,
`cells_patched`), cho cột "Gossip" và dòng đồng bộ trên dashboard. `/api/inventory` (và `inventory` trong overview):
mỗi ô `by_branch[b]` có thêm `source` (`kafka`, `gossip`, `reconcile`; `reconcile` hiện chấm cam, chú thích "số đọc thẳng từ chi nhánh (đối soát)") và
`last_movement` (phiên bản của ô, để dashboard đọc đơn điệu).

`/api/nodes` (và `nodes` trong overview): mỗi chi nhánh có `alive` (góc nhìn của bản sao này không phải OFFLINE, như
trước vòng 5), `state` (góc nhìn của bản sao này), `views` (`{"A": "ONLINE", "B": null, "C": "OFFLINE"}`: góc nhìn của
từng bản sao cấu hình; `null` = chưa có hoặc cũ quá 15 giây) và `verdict` (kết luận theo đa số, PT-13). Dashboard tô
trạng thái chi nhánh theo `verdict`. Vòng 6 thêm `recovering` (chi nhánh tự báo trong heartbeat gần nhất): dashboard
ghi "Đang phục hồi" khi `recovering` và `verdict` khác OFFLINE.

Mã lỗi `/api/handoff` (vòng 6):

| Mã lỗi | Khi nào |
|---|---|
| 404 `product_not_found` | Bản sao không có ô (chi nhánh, mã hàng) trong snapshot |
| 409 `branch_not_offline` | Kết luận đa số của bản sao này về chi nhánh không phải OFFLINE (PT-13): không ghi hộ |
| 422 `insufficient_stock` | Tồn tạm tính không đủ; kèm `qty_on_hand` (tồn tạm tính) |

`digest` (trong `/api/digest`, `/api/overview`) có thêm `handoff`: `{"2": {pending, applied, rejected}}`, số lượt ghi
hộ ở bản sao này theo chi nhánh (chỉ chi nhánh có ghi hộ). Mở qua nginx thì dashboard cộng qua digest của mọi bản sao.

`/api/trace` trả `{node, branch_id, movement_id, product_id, event, cell, via}`:
- `event`: dòng `event_log` của sự kiện (`move_type`, `qty_delta`, `qty_after`, `node_time`, `received_at`,
  `kafka_partition`, `kafka_offset`, `kafka_ts`), `null` nếu bản sao này không có dòng nhật ký.
- `cell`: ô (`branch_id`, `product_id`) hiện tại (`qty_on_hand`, `last_movement`, `source`, `updated_at`), `null` nếu chưa có.
- `via`: bản sao biết sự kiện bằng đường nào.

| `via` | Khi nào |
|---|---|
| `kafka` | Có dòng `event_log`: nhận qua Redpanda lúc `received_at`. Nếu `cell.source` khác `kafka` và `cell.last_movement` = `movement_id` thì ô đã được vá trước đó (lúc `cell.updated_at`) |
| `gossip`, `reconcile` | Không có dòng nhật ký; ô đã tới `movement_id` (hoặc mới hơn) và giá trị hiện tại do kênh đó ghi |
| `superseded` | Không có dòng nhật ký; ô đã có biến động mới hơn nhận qua Redpanda (sự kiện này bị bỏ qua, ví dụ sau `rpk group seek --to end`) |
| `missing` | Không có dòng nhật ký và ô chưa tới `movement_id`: bản sao này chưa biết sự kiện |

Dashboard truy vết một sự kiện bằng cách gọi `/cn<N>/api/movement/{movement_id}` (mốc chi nhánh, `sent_at`) và
`/replica/<X>/api/trace` cho từng bản sao (qua nginx); mở thẳng một bản sao thì chỉ gọi `api/trace` của nó. Ba loại
mốc (chi nhánh, broker, bản sao) theo ba đồng hồ khác nhau: chỉ để hiển thị, không so thứ tự (PT-05).

## 3. Sự kiện trên Redpanda

- Cụm 3 broker, mỗi node một broker (mã broker = `BRANCH_ID`), mọi client dùng cửa `:19092`
  (`KAFKA_BROKERS` liệt kê cả ba).
- Topic `inventory.movement`, 3 phân hoạch, RF = số broker trong `BROKER_SEEDS` (3; chỉ 1 khi 2 máy thật),
  `write.caching=false`, `message.timestamp.type=LogAppendTime` (timestamp của thông điệp là giờ broker leader ghi,
  không phải giờ relay gửi; sink lưu vào `event_log.kafka_ts` để truy vết). Chỉ service `topic-init` (node A) tạo
  topic; broker tắt tự tạo topic.
- Khoá thông điệp `"<branch_id>:<product_id>"`: mọi sự kiện của cùng một dòng tồn vào cùng một phân hoạch.
- Giá trị (JSON, chính là `outbox.payload`):

```json
{"branch_id": 2, "movement_id": 57, "product_id": 3, "move_type": "SALE",
 "qty_delta": -1, "qty_after": 148, "node_time": "2026-11-19T08:25:39.033693+00:00"}
```

- Producer: `acks=all`, `enable.idempotence=true` (gửi lại không trùng, không đảo thứ tự trong phân hoạch),
  `message.timeout.ms=8000`. Write caching tắt nên `acks=all` nghĩa là đa số broker đã ghi đĩa (fsync).
- Consumer: mỗi bản sao group `replica-<NODE_NAME>`, `auto.offset.reset=earliest`, tự commit offset sau khi ghi CSDL.
  Mỗi 5 giây sink hỏi metadata topic, offset đã commit và high watermark từng phân hoạch:
  `lag = Σ(high watermark − offset đã commit)`; hỏi lỗi hoặc quá hạn thì coi là mất broker. Cùng lần hỏi đó sink
  ghi các broker còn sống theo metadata vào `sink_stats.brokers_up` (vòng 4).

## 4. Đường đi qua nginx (mọi máy, `infra/nginx/default.conf.template`)

Từ vòng 5 mỗi máy chạy một nginx (cổng vào), cấu hình giống hệt nhau: vào cổng nào cũng tới được mọi bản sao và mọi
chi nhánh. Tên upstream được phân giải động (`resolve`, `resolver 127.0.0.11`, cần nginx ≥ 1.27.3), nên nginx khởi
động được cả khi node khác chưa chạy hoặc đang bị rút mạng (tên chưa có thì đường đó trả 502). Mọi phản hồi có
`Access-Control-Allow-Origin: *`; `OPTIONS` trả 204 (cho phép `GET`, `POST`, header `Content-Type`), để trang mở từ
cổng này gọi được cổng khác khi chuyển cổng. Không dùng cookie hay xác thực.

| Đường dẫn | Tới | Ghi chú |
|---|---|---|
| `/` và mọi đường dẫn khác | upstream `replicas` (round-robin A, B, C) | Bản sao lỗi bị gạch 10 giây; GET tự thử bản kế tiếp, tối đa 3 lần |
| `/lb/replicas.json` | nginx trả thẳng | Danh sách tên bản sao cho bảng so sánh |
| `/lb/gateways.json` | nginx trả thẳng | Một chuỗi JSON, các cổng vào trong `GATEWAYS` cách nhau dấu phẩy: `"http://localhost,http://localhost:8012,http://localhost:8022"`. Dashboard và POS đọc một lần lúc mở trang |
| `/replica/<X>/...` | đúng bản sao X | Để dashboard so dấu vân tay từng bản |
| `/cn1/`, `/cn2/`, `/cn3/` (đúng đường gốc) | POS của chi nhánh tương ứng | Chi nhánh không trả lời (502, 504) thì nginx trả chính trang POS từ file mount `/usr/share/nginx/pos.html` (`@pos_page`, vòng 6) để quầy ghi hộ được |
| `/cn1/...`, `/cn2/...`, `/cn3/...` (đường con, API) | Chi nhánh tương ứng | Chi nhánh mất liên lạc thì trả trang 503 báo rõ (`@branch_offline`) |
