# API và giao tiếp giữa các tiến trình

Ba kênh giao tiếp:

| Kênh | Từ → tới | Kiểu |
|---|---|---|
| HTTP qua nginx | Trình duyệt → bản sao, chi nhánh | Đồng bộ, yêu cầu–phản hồi |
| Heartbeat HTTP | `branch_api` → `/api/heartbeat` của MỌI bản sao, mỗi 5 giây | Đồng bộ, không qua broker |
| Sự kiện Redpanda | `relay` → topic `inventory.movement` → mỗi `sink` | Bất đồng bộ, bền, at-least-once |

Tài liệu tự sinh: `http://localhost:8001/docs` (chi nhánh), `http://localhost:8000/docs` (bản sao).

## 1. Chi nhánh (`ROLE=branch`, cổng 8001)

| Phương thức | Đường dẫn | Việc làm |
|---|---|---|
| GET | `/` | Màn hình POS (`web/pos.html`) |
| GET | `/health` | Kiểm tra sống, có chạm CSDL |
| GET | `/api/info` | `branch_id`, `branch_name`, tên các bản sao |
| GET | `/api/inventory` | Tồn của chi nhánh, kèm `version` |
| GET | `/api/status` | Số sự kiện chờ trong outbox, `sync_stuck`, RTT và tình trạng tới từng bản sao |
| POST | `/api/sale` | Bán. Body: `{product_id, qty, version?, request_id?}` |
| POST | `/api/receipt` | Nhập, cùng body |
| POST | `/api/sale/random?count=20` | Bán nhanh `count` đơn ngẫu nhiên (dùng khi demo) |

`/api/sale`, `/api/receipt` trả `{movement_id, product_id, qty_on_hand, version, elapsed_ms}`; gửi lại cùng
`request_id` thì trả kết quả cũ kèm `replayed: true`.

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
| POST | `/api/heartbeat` | Nhận heartbeat. Body: `{branch_id, branch_name, node_time_ms, outbox_backlog, rtt_ms}` |
| GET | `/api/overview` | Mọi thứ dashboard cần trong một lần gọi: `served_by`, `nodes`, `inventory`, `events`, `digest` |
| GET | `/api/digest` | Dấu vân tay, tổng tồn, `last_movement_by_branch`, bộ đếm sink |
| GET | `/api/nodes`, `/api/inventory`, `/api/events?limit=30`, `/api/stats` | Từng phần của overview, để gọi bằng tay |

## 3. Sự kiện trên Redpanda

- Topic `inventory.movement`, 3 phân hoạch, `replication_factor=1`.
- Khoá thông điệp `"<branch_id>:<product_id>"`: mọi sự kiện của cùng một dòng tồn vào cùng một phân hoạch.
- Giá trị (JSON, chính là `outbox.payload`):

```json
{"branch_id": 2, "movement_id": 57, "product_id": 3, "move_type": "SALE",
 "qty_delta": -1, "qty_after": 148, "node_time": "2026-11-19T08:25:39.033693+00:00"}
```

- Producer: `acks=all`, `message.timeout.ms=8000`. Consumer: mỗi bản sao group `replica-<NODE_NAME>`,
  `auto.offset.reset=earliest`, tự commit offset sau khi ghi CSDL.

## 4. Đường đi qua nginx (máy A, `infra/nginx/default.conf.template`)

| Đường dẫn | Tới | Ghi chú |
|---|---|---|
| `/` và mọi đường dẫn khác | upstream `replicas` (round-robin A, B, C) | Bản sao lỗi bị gạch 10 giây; GET tự thử bản kế tiếp, tối đa 3 lần |
| `/lb/replicas.json` | nginx trả thẳng | Danh sách tên bản sao cho bảng so sánh |
| `/replica/<X>/...` | đúng bản sao X | Để dashboard so dấu vân tay từng bản |
| `/cn1/`, `/cn2/`, `/cn3/` | POS của chi nhánh tương ứng | Chi nhánh mất liên lạc thì trả trang 503 báo rõ |
