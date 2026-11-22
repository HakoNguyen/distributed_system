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
| `sync_peer` | Lần trao đổi trực tiếp cuối với từng nơi: bản sao khác (gossip) hoặc chi nhánh (đối soát) | Một dòng một nơi, tạo ở lần trao đổi đầu |

Cột từng bảng:

| Bảng | Cột |
|---|---|
| `node_status` | `branch_id` (khoá chính), `branch_name`, `last_seen` (giờ trung tâm lúc nhận), `node_time` (giờ chi nhánh), `outbox_backlog`, `rtt_ms`, `branch_url` (địa chỉ POS chi nhánh tự báo trong heartbeat, dùng để đối soát) |
| `inventory_snapshot` | `branch_id`, `product_id` (khoá chính kép), `qty_on_hand`, `last_movement`, `node_time` (giờ chi nhánh của biến động đó), `updated_at` (giờ trung tâm cập nhật), `source` (kênh đã ghi giá trị hiện tại: `kafka`, `gossip`, `reconcile`; không nằm trong dấu vân tay) |
| `sync_peer` | `peer` (khoá chính: tên bản sao `A`, hoặc `CN2` cho chi nhánh), `channel` (`gossip` hoặc `reconcile`), `last_ok_at` (lần cuối gọi được và merge xong), `failing_since` (lỗi đầu tiên của đợt lỗi hiện tại; NULL = đang gọi được), `last_error`, `cells_patched` (tổng số ô đã vá nhờ nơi này) |
| `event_log` | `branch_id`, `movement_id` (khoá chính kép), `product_id`, `move_type`, `qty_delta`, `qty_after`, `node_time` (giờ chi nhánh tạo sự kiện), `received_at` (giờ trung tâm nhận), `kafka_partition`, `kafka_offset` (vị trí trên Redpanda, để truy vết) |
| `sink_stats` | `id` (luôn 1), `processed`, `duplicates`, `last_event_at`, `broker_ok` (NULL = chưa kiểm), `broker_lost_at` (mốc mất broker đầu tiên của đợt hiện tại; NULL = đang đọc được), `lag` (số sự kiện trên Redpanda chưa áp, đo lần được gần nhất), `broker_checked_at` (lần kiểm gần nhất; cũ quá nghĩa là sink đã dừng) |

**Luật merge chung** (`merge_cells(conn, rows, source)`, PT-10): mọi kênh ghi `inventory_snapshot` đều qua một câu
upsert `... ON CONFLICT DO UPDATE ... WHERE inventory_snapshot.last_movement < EXCLUDED.last_movement`. Ô chỉ bị ghi
đè khi `movement_id` mới hơn (cùng `movement_id` thì giữ bản đang có); khi ghi đè thì `source` = kênh vừa ghi. Hàm
trả số ô thực sự được ghi. Giao hoán, lũy đẳng: nhận theo thứ tự nào, từ kênh nào cũng ra cùng bảng.

Quy tắc ghi của sink (`apply_event`), trong một transaction:
1. `INSERT INTO event_log ... ON CONFLICT DO NOTHING`. Không chèn được = sự kiện trùng, chỉ tăng `duplicates`.
2. `merge_cells(..., 'kafka')`: sự kiện cũ đến sau không ghi đè số mới. Sự kiện tới sau khi ô đã được vá bằng gossip
   hoặc đối soát vẫn vào `event_log` và tính `processed` ("mới"), nhưng không đổi ô (cùng `movement_id`).

Quy tắc ghi của kênh trực tiếp (vòng 3; `workers/gossip.py` gọi mạng xong rồi mới gọi các hàm này):
- Gossip (`merge_replica_snapshot(peer, rows)`): `merge_cells(..., 'gossip')` và upsert `sync_peer` (`last_ok_at`,
  `cells_patched += n`, xoá `failing_since`) trong một transaction. `rows` do `pick_stale` chọn: chỉ ô bản sao kia đi
  trước ở **cả hai** lần kiểm liên tiếp, nên `cells_patched` chỉ tăng khi thật sự thiếu ô (không tăng ở K1).
- Đối soát (`merge_branch_snapshot(branch_id, payload)`): từ chối nếu `payload.branch_id` khác chi nhánh đã gọi;
  `merge_cells(..., 'reconcile')`, `sync_peer` với `peer = 'CN<id>'`. Chi nhánh cần đối soát do `reconcile_targets`
  chọn bằng một câu SQL trên `sink_stats`, `node_status`, mọi mốc so bằng `now()` của `replica_db`:
  `broker_ok = false`, `broker_lost_at` cũ hơn 15 giây, `broker_checked_at` mới hơn 15 giây (sink còn chạy),
  `last_seen` mới hơn 15 giây, có `branch_url`.
- Gọi lỗi (`record_peer_error`): `failing_since` giữ mốc lỗi đầu tiên, `last_error` lỗi mới, `last_ok_at` giữ nguyên.
- Dữ liệu nhận từ node khác được kiểm bằng model `SnapshotCell` trước khi ghi; sai thì không ghi gì.

**Ô được vá không có dòng `event_log`**: gossip và đối soát chỉ mang số tồn mới nhất của ô, không mang các lượt
bán ở giữa, nên không bịa dòng nhật ký. Hệ quả: `query_events` (danh sách sự kiện trên dashboard) thiếu các lượt đó
cho tới khi sink nhận được; `processed` chỉ đếm sự kiện sink áp, nên bản sao đã lỡ sự kiện có `processed` thấp hơn
bản sao khác mãi mãi (K8: B thấp hơn A đúng số sự kiện bị bỏ qua) dù dấu vân tay khớp; `duplicates` không đổi.

Kiểm broker (`record_broker_check(ok, lag)`, sink gọi mỗi 5 giây sau khi đã hỏi Redpanda xong): một câu `UPDATE
sink_stats`. `broker_checked_at = now()`; được thì `broker_ok = true`, `broker_lost_at = NULL`, `lag` = số mới; lỗi
thì `broker_ok = false`, `broker_lost_at` giữ mốc lỗi đầu tiên, `lag` giữ số cũ.

**Dấu vân tay** (`query_digest`): `md5` của chuỗi `branch_id:product_id:qty_on_hand` của mọi dòng snapshot, sắp
theo khoá. Hai bản sao cùng dấu vân tay nghĩa là giữ đúng cùng một số liệu đến từng ô. `source` không nằm trong dấu
vân tay: cùng số mà khác nguồn vẫn là khớp.

**Snapshot chi nhánh** (`services/branch.py: snapshot`, cho đối soát): MỘT câu `SELECT` trên `inventory` JOIN LATERAL
dòng `stock_movement` mới nhất của từng mã, nên tồn và `movement_id` đọc cùng một thời điểm; PT-02 bảo đảm
`qty_on_hand` bằng `qty_after` của biến động đó. Chỉ đọc (PT-07).
