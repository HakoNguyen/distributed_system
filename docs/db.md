# Thiết kế CSDL

Hai loại CSDL PostgreSQL 16, cùng tên `kho`, người dùng `app`. Mỗi máy có một CSDL chi nhánh và một CSDL bản sao.
File khởi tạo ở `db/`; chỉ chạy khi volume trống.

## 1. Dùng chung: `product` (`db/product.sql`)

Danh mục 20 sản phẩm, **giống hệt nhau** ở mọi CSDL. Ở bản demo, mọi CSDL nạp cùng một file lúc khởi tạo; trong đề
tài đầy đủ, bảng này được nhân bản từ trung tâm xuống.

| Cột | Ý nghĩa |
|---|---|
| `product_id` | Khoá chính |
| `name`, `unit` | Tên, đơn vị tính |
| `reorder_point` | Dưới mức này thì cần đặt thêm hàng (dashboard tô màu) |

## 2. CSDL chi nhánh (`db/branch.sql`)

Chỉ chứa tồn kho của chính chi nhánh đó, không biết gì về chi nhánh khác.

| Bảng | Vai trò | Ràng buộc quan trọng |
|---|---|---|
| `inventory` | Tồn hiện tại, một dòng một mã hàng | `qty_on_hand >= 0`; `version` tăng mỗi lần sửa (khoá lạc quan) |
| `stock_movement` | Sổ cái biến động, **chỉ ghi thêm** | `movement_id` BIGSERIAL tăng dần trong chi nhánh; `move_type` ∈ INIT, SALE, RECEIPT; `request_id` UNIQUE |
| `outbox` | Hộp thư đi: sự kiện chờ relay gửi | `event_id` = `movement_id`; `sent_at IS NULL` = chưa gửi; chỉ mục riêng cho dòng chưa gửi |
| `relay_status` | Trạng thái gửi của relay, hiện lên POS | Đúng một dòng (`id = 1`); `last_ok_at`, `failing_since` (NULL = đang gửi được), `last_error` |

Quy tắc ghi (`api/services/branch.py`):
- Sửa `inventory`, thêm `stock_movement`, thêm `outbox` luôn trong **một** transaction.
- Trừ tồn bằng một câu `UPDATE ... WHERE qty_on_hand + delta >= 0`: Postgres khoá dòng, hai quầy cùng bán một mã
  hàng xếp hàng lần lượt, không bán lố.
- Gửi lại cùng `request_id` thì trả kết quả cũ, không trừ lần hai.
- Lần chạy đầu, mỗi mã hàng có một biến động `INIT` đi qua outbox như mọi lượt bán, nên trung tâm nhận tồn ban đầu
  qua đúng con đường sự kiện.

Quy tắc của relay (`relay_batch`, `record_relay_result`):
- Đọc lô `outbox` chưa gửi, gửi lên Redpanda **ngoài transaction**, chỉ khi cả lô được xác nhận mới
  `UPDATE outbox SET sent_at = now()` cho đúng các `event_id` của lô (PT-03). Sự kiện ghi trong lúc gửi vẫn chưa gửi.
- Gửi được: `last_ok_at = now()`, `failing_since = NULL`. Lỗi: `last_error` = lỗi mới, `failing_since` giữ mốc lỗi
  đầu tiên của đợt lỗi hiện tại. Outbox trống thì không ghi gì.

## 3. CSDL bản sao trung tâm (`db/replica.sql`)

Không giữ bản chính của tồn kho; chỉ giữ bảng tổng hợp dựng lại từ sự kiện.

| Bảng | Vai trò | Ràng buộc quan trọng |
|---|---|---|
| `node_status` | Trạng thái từng chi nhánh, cập nhật mỗi heartbeat | `last_seen` theo giờ trung tâm; `node_time` theo giờ chi nhánh |
| `inventory_snapshot` | Tồn toàn chuỗi, một dòng một (chi nhánh, mã hàng) | `last_movement` = `movement_id` mới nhất đã áp vào dòng |
| `event_log` | Mọi sự kiện đã nhận | Khoá chính `(branch_id, movement_id)` = cơ chế chống trùng |
| `sink_stats` | Bộ đếm của sink: đã áp, bản trùng đã bỏ qua; trạng thái đường đọc Redpanda | Đúng một dòng (`id = 1`) |

Cột từng bảng:

| Bảng | Cột |
|---|---|
| `node_status` | `branch_id` (khoá chính), `branch_name`, `last_seen` (giờ trung tâm lúc nhận), `node_time` (giờ chi nhánh), `outbox_backlog`, `rtt_ms` |
| `inventory_snapshot` | `branch_id`, `product_id` (khoá chính kép), `qty_on_hand`, `last_movement`, `node_time` (giờ chi nhánh của biến động đó), `updated_at` (giờ trung tâm cập nhật) |
| `event_log` | `branch_id`, `movement_id` (khoá chính kép), `product_id`, `move_type`, `qty_delta`, `qty_after`, `node_time` (giờ chi nhánh tạo sự kiện), `received_at` (giờ trung tâm nhận), `kafka_partition`, `kafka_offset` (vị trí trên Redpanda, để truy vết) |
| `sink_stats` | `id` (luôn 1), `processed`, `duplicates`, `last_event_at`, `broker_ok` (NULL = chưa kiểm), `broker_lost_at` (mốc mất broker đầu tiên của đợt hiện tại; NULL = đang đọc được), `lag` (số sự kiện trên Redpanda chưa áp, đo lần được gần nhất), `broker_checked_at` (lần kiểm gần nhất; cũ quá nghĩa là sink đã dừng) |

Quy tắc ghi (`api/services/replica.py: apply_event`), trong một transaction:
1. `INSERT INTO event_log ... ON CONFLICT DO NOTHING`. Không chèn được = sự kiện trùng, chỉ tăng `duplicates`.
2. Upsert `inventory_snapshot` với điều kiện `WHERE inventory_snapshot.last_movement < EXCLUDED.last_movement`:
   sự kiện cũ đến sau không ghi đè số mới.

Kiểm broker (`record_broker_check(ok, lag)`, sink gọi mỗi 5 giây sau khi đã hỏi Redpanda xong): một câu `UPDATE
sink_stats`. `broker_checked_at = now()`; được thì `broker_ok = true`, `broker_lost_at = NULL`, `lag` = số mới; lỗi
thì `broker_ok = false`, `broker_lost_at` giữ mốc lỗi đầu tiên, `lag` giữ số cũ.

**Dấu vân tay** (`query_digest`): `md5` của chuỗi `branch_id:product_id:qty_on_hand` của mọi dòng snapshot, sắp
theo khoá. Hai bản sao cùng dấu vân tay nghĩa là giữ đúng cùng một số liệu đến từng ô.
