# API và giao tiếp giữa các tiến trình

Các kênh giao tiếp:

| Kênh | Từ → tới | Kiểu |
|---|---|---|
| HTTP qua nginx | Trình duyệt → bản sao, chi nhánh | Đồng bộ, yêu cầu–phản hồi |
| Heartbeat HTTP | `branch_api` → `/api/heartbeat` của MỌI bản sao, mỗi 5 giây | Đồng bộ, không qua broker |
| Sự kiện Redpanda | `relay` → topic `inventory.movement` → mỗi `sink` | Bất đồng bộ, bền, at-least-once |
| Gossip HTTP | `replica_api` → `/api/digest`, `/api/snapshot` của các bản sao khác, mỗi 10 giây | Đồng bộ, chỉ kéo; timeout 2 giây |
| Đối soát HTTP | `replica_api` → `/api/snapshot` của chi nhánh còn sống, chỉ khi mất broker quá 15 giây | Đồng bộ, chỉ đọc (PT-07); timeout 2 giây |

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
| POST | `/api/sale` | Bán. Body: `{product_id, qty, version?, request_id?}` |
| POST | `/api/receipt` | Nhập, cùng body |
| POST | `/api/sale/random?count=20` | Bán nhanh `count` đơn ngẫu nhiên (dùng khi demo) |

`/api/sale`, `/api/receipt` trả `{movement_id, product_id, qty_on_hand, version, elapsed_ms}`; gửi lại cùng
`request_id` thì trả kết quả cũ kèm `replayed: true`.

`/api/status` có `relay: {last_ok_at, failing_since, last_error}` (bảng `relay_status`): `failing_since` khác NULL
thì POS hiện "Gửi lên Redpanda: lỗi từ HH:MM:SS".

| Mã lỗi | Khi nào |
|---|---|
| 404 `product_not_found` | Không có mã hàng |
| 409 `version_conflict` | Gửi `version` mà tồn đã bị sửa; kèm `current_version` |
| 422 `insufficient_stock` | Bán quá tồn; kèm `qty_on_hand` |

## 2. Bản sao trung tâm (`ROLE=replica`, cổng 8000)

Mọi phản hồi có header `X-Served-By: replica-<X>`.

| Phương thức | Đường dẫn | Việc làm |
|---|---|---|
| GET | `/` | Dashboard (`web/dashboard.html`) |
| GET | `/health` | Kiểm tra sống |
| POST | `/api/heartbeat` | Nhận heartbeat. Body: `{branch_id, branch_name, node_time_ms, outbox_backlog, rtt_ms, branch_url}` (`branch_url` phải bắt đầu bằng `http://` hoặc `https://`) |
| GET | `/api/overview` | Mọi thứ dashboard cần trong một lần gọi: `served_by`, `nodes`, `inventory`, `events`, `digest` |
| GET | `/api/digest` | Dấu vân tay, tổng tồn, `last_movement_by_branch`, bộ đếm và trạng thái broker của sink, `sync_peers` |
| GET | `/api/snapshot` | Mọi ô của bảng tổng hợp, để bản sao khác gossip: `{node, cells: [{branch_id, product_id, qty_on_hand, last_movement, node_time}]}` |
| GET | `/api/nodes`, `/api/inventory`, `/api/events?limit=30`, `/api/stats` | Từng phần của overview, để gọi bằng tay |

`/api/stats` (và `digest` trong `/api/digest`, `/api/overview`): `processed`, `duplicates`, `last_event_at`,
`broker_ok`, `broker_lost_at`, `lag`, `broker_checked_at` (cột `sink_stats`, `docs/db.md` mục 3). `broker_ok = false`
thì dashboard hiện "Đồng bộ dừng từ HH:MM:SS"; chi nhánh vẫn "còn sống" nếu heartbeat còn tới.

`sync_peers` (trong digest): các dòng `sync_peer` (`peer`, `channel`, `last_ok_at`, `failing_since`, `last_error`,
`cells_patched`), cho cột "Gossip" và dòng đồng bộ trên dashboard. `/api/inventory` (và `inventory` trong overview):
mỗi ô `by_branch[b]` có thêm `source` (`kafka`, `gossip`, `reconcile`); `reconcile` hiện nhãn "qua đối soát".

## 3. Sự kiện trên Redpanda

- Cụm 3 broker, mỗi node một broker (mã broker = `BRANCH_ID`), mọi client dùng cửa `:19092`
  (`KAFKA_BROKERS` liệt kê cả ba).
- Topic `inventory.movement`, 3 phân hoạch, RF = số broker trong `BROKER_SEEDS` (3; chỉ 1 khi 2 máy thật),
  `write.caching=false`. Chỉ service `topic-init` (node A) tạo topic; broker tắt tự tạo topic.
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
  `lag = Σ(high watermark − offset đã commit)`; hỏi lỗi hoặc quá hạn thì coi là mất broker.

## 4. Đường đi qua nginx (máy A, `infra/nginx/default.conf.template`)

| Đường dẫn | Tới | Ghi chú |
|---|---|---|
| `/` và mọi đường dẫn khác | upstream `replicas` (round-robin A, B, C) | Bản sao lỗi bị gạch 10 giây; GET tự thử bản kế tiếp, tối đa 3 lần |
| `/lb/replicas.json` | nginx trả thẳng | Danh sách tên bản sao cho bảng so sánh |
| `/replica/<X>/...` | đúng bản sao X | Để dashboard so dấu vân tay từng bản |
| `/cn1/`, `/cn2/`, `/cn3/` | POS của chi nhánh tương ứng | Chi nhánh mất liên lạc thì trả trang 503 báo rõ |
