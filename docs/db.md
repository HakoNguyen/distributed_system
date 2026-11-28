# Thiết kế CSDL

Hai loại CSDL PostgreSQL 16 (`postgres:16.16-alpine`), cùng tên `kho`, người dùng `app` (mật khẩu `DB_PASSWORD`,
vòng 7). Mỗi máy có một CSDL chi nhánh (kèm standby, vòng 7) và một CSDL bản sao.
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
| `handoff_rejected` | Lượt ghi hộ chi nhánh đã từ chối lúc áp lại (vòng 6, PT-14) | `request_id` khoá chính; `product_id`, `qty`, `reason` (`insufficient_stock`, `product_not_found`), `qty_on_hand` (tồn lúc từ chối), `rejected_at`. Quyết định đã chốt: kéo lại lượt đó thì vẫn REJECTED, kể cả khi tồn đã tăng |

Quy tắc ghi (`api/services/branch.py`):
- Sửa `inventory`, thêm `stock_movement`, thêm `outbox` luôn trong **một** transaction.
- Trừ tồn bằng một câu `UPDATE ... WHERE qty_on_hand + delta >= 0`: Postgres khoá dòng, hai quầy cùng bán một mã
  hàng xếp hàng lần lượt, không bán lố.
- Gửi lại cùng `request_id` thì trả kết quả cũ, không trừ lần hai.
- Lần chạy đầu, mỗi mã hàng có một biến động `INIT` đi qua outbox như mọi lượt bán, nên trung tâm nhận tồn ban đầu
  qua đúng con đường sự kiện.

Quy tắc áp ghi hộ (vòng 6, PT-14; `recovery_once` trong `api/services/branch.py`, `workers/recovery.py` truyền vào
hàm kéo `pull` và hàm báo `ack` như `relay_batch(send)`):
- Kéo `GET /api/handoff?branch_id=<mình>` của mọi bản sao **ngoài transaction**; dữ liệu nhận được kiểm bằng model
  `HandoffItem`, sai thì coi như không gọi được bản sao đó.
- `collect_handoffs`: gộp các lượt PENDING, xếp theo (thứ tự bản sao trong `REPLICA_URLS`, `handoff_id`), mỗi
  `request_id` một lượt (lượt nằm ở hai bản sao vì POS chuyển bản sao giữa chừng thì áp một lần, báo cả hai).
- `apply_handoffs`: theo đúng thứ tự, mỗi lượt: đã có trong `handoff_rejected` → REJECTED như cũ; không thì
  `change_stock(-qty, 'SALE', request_id)` (MỘT transaction: tồn, sổ cái, outbox, PT-02; `request_id` đã có thì trả
  kết quả cũ, PT-08) → APPLIED; 422/404 → ghi `handoff_rejected` (transaction riêng) → REJECTED. Lỗi khác (mất CSDL)
  thì dừng, không áp các lượt sau, để giữ thứ tự.
- Chỉ sau khi các lượt đã commit mới gọi `ack` cho từng bản sao giữ lượt đó. Ack mất thì lần kéo sau lượt đó còn
  PENDING, áp lại không trừ thêm, rồi báo lại.
- Trạng thái ONLINE / RECOVERING nằm trong bộ nhớ `branch_api` (`recovery`), tính bằng hàm thuần `next_recovery_state`
  (`docs/spec.md` mục 4). Mọi lỗi trong một lần chạy bị bắt, ghi vào `last_error`; luồng không dừng.

Quy tắc của relay (`relay_batch`, `record_relay_result`):
- Đọc lô `outbox` chưa gửi, gửi lên Redpanda **ngoài transaction**, chỉ khi cả lô được xác nhận mới
  `UPDATE outbox SET sent_at = now()` cho đúng các `event_id` của lô (PT-03). Sự kiện ghi trong lúc gửi vẫn chưa gửi.
- Gửi được: `last_ok_at = now()`, `failing_since = NULL`. Lỗi: `last_error` = lỗi mới, `failing_since` giữ mốc lỗi
  đầu tiên của đợt lỗi hiện tại. Outbox trống thì không ghi gì.

Standby CSDL chi nhánh (vòng 7, PT-12):
- Mỗi node có hai Postgres chi nhánh: `branch_db` (lần đầu là primary, `initdb` chạy `db/*.sql`) và
  `branch_db_standby` (lần đầu `pg_basebackup -R` từ `PG_PRIMARY_HOST`, streaming replication có sẵn của Postgres).
  **Tên service không còn là vai trò**: sau `make promote`, `branch_db_standby` là primary; sau `make rejoin`,
  `branch_db` là standby. Vai trò thật xem `make db-status` hoặc `/api/status` trường `db`.
- `db/replication.sh` (chạy một lần lúc `initdb` của primary): role `replicator` (`REPLICATION`, mật khẩu
  `REPLICATION_PASSWORD`), dòng `host replication replicator all scram-sha-256` trong `pg_hba.conf`. Standby chép cả
  hai qua `pg_basebackup`, nên đổi vai trò không phải cấu hình lại.
- `db/pg-start.sh` (lệnh khởi động của cả hai): có file `minigo.fenced` trong thư mục dữ liệu thì thoát, không chạy
  Postgres (fencing, K10c); thư mục trống và có `PG_PRIMARY_HOST` thì `pg_basebackup`; rồi chạy Postgres với
  `wal_keep_size=256MB` (không dùng replication slot: standby chết lâu không làm đầy đĩa primary).
- Chế độ: `synchronous_standby_names` = `''` (bất đồng bộ, mặc định) hoặc `'*'` (đồng bộ, `synchronous_commit=on`);
  đặt bằng `ALTER SYSTEM` + `pg_reload_conf()` trên primary hiện tại (`make sync-mode`). Giá trị nằm trong
  `postgresql.auto.conf` của từng Postgres, không nhân bản.
- `make promote`: fence primary cũ (`docker update --restart=no`, `docker kill`, ghi `minigo.fenced`) TRƯỚC, rồi
  `pg_promote()` standby, `setval` sequence `stock_movement_movement_id_seq` thêm 1000 (không cấp lại `movement_id` mà
  primary cũ có thể đã dùng và relay đã gửi), đặt bất đồng bộ (primary mới chưa có standby). `make rejoin`: xoá dữ
  liệu node đã bị fence, `pg_basebackup -R` từ primary mới, bỏ fence, bật lại làm standby.
- Không có bảng mới. Đổi xong phải `make local-reset` (role `replicator`, mật khẩu mới).

## 3. CSDL bản sao trung tâm (`db/replica.sql`)

Không giữ bản chính của tồn kho; chỉ giữ bảng tổng hợp dựng lại từ sự kiện.

| Bảng | Vai trò | Ràng buộc quan trọng |
|---|---|---|
| `node_status` | Trạng thái từng chi nhánh, cập nhật mỗi heartbeat | `last_seen` theo giờ trung tâm; `node_time` theo giờ chi nhánh |
| `inventory_snapshot` | Tồn toàn chuỗi, một dòng một (chi nhánh, mã hàng) | `last_movement` = `movement_id` mới nhất đã áp vào dòng |
| `event_log` | Mọi sự kiện đã nhận | Khoá chính `(branch_id, movement_id)` = cơ chế chống trùng |
| `sink_stats` | Bộ đếm của sink: đã áp, bản trùng đã bỏ qua; trạng thái đường đọc Redpanda | Đúng một dòng (`id = 1`) |
| `sync_peer` | Lần trao đổi trực tiếp cuối với từng nơi: bản sao khác (gossip) hoặc chi nhánh (đối soát) | Một dòng một nơi, tạo ở lần trao đổi đầu |
| `peer_view` | Góc nhìn của bản sao KHÁC về từng chi nhánh (vòng 5, PT-13), kéo qua `GET /api/views` | Khoá chính `(peer, branch_id)`; `state` ∈ ONLINE, SUSPECT, OFFLINE; góc nhìn của chính bản sao này không lưu, tính từ `node_status` |
| `handoff` | Lượt bán ghi hộ cho chi nhánh đang OFFLINE (vòng 6, PT-14), chờ chi nhánh tự kéo về áp | `handoff_id` BIGSERIAL (thứ tự nhận ở bản sao này); UNIQUE `(branch_id, request_id)`; `status` ∈ PENDING, APPLIED, REJECTED |

Cột từng bảng:

| Bảng | Cột |
|---|---|
| `node_status` | `branch_id` (khoá chính), `branch_name`, `last_seen` (giờ trung tâm lúc nhận), `node_time` (giờ chi nhánh), `outbox_backlog`, `rtt_ms`, `branch_url` (địa chỉ POS chi nhánh tự báo trong heartbeat, dùng để đối soát), `recovering` (chi nhánh tự báo đang RECOVERING, vòng 6; không đổi `state`, `verdict`) |
| `handoff` | `handoff_id`, `branch_id`, `request_id`, `product_id`, `qty` (1–1000), `status`, `movement_id` (APPLIED: biến động chi nhánh tạo ra), `reason` (REJECTED: `insufficient_stock`, `product_not_found`), `created_at` (giờ bản sao nhận, chỉ để hiển thị), `decided_at` (lúc nhận ack) |
| `inventory_snapshot` | `branch_id`, `product_id` (khoá chính kép), `qty_on_hand`, `last_movement`, `node_time` (giờ chi nhánh của biến động đó), `updated_at` (giờ trung tâm cập nhật), `source` (kênh đã ghi giá trị hiện tại: `kafka`, `gossip`, `reconcile`; không nằm trong dấu vân tay) |
| `sync_peer` | `peer` (khoá chính: tên bản sao `A`, hoặc `CN2` cho chi nhánh), `channel` (`gossip` hoặc `reconcile`), `last_ok_at` (lần cuối gọi được và merge xong), `failing_since` (lỗi đầu tiên của đợt lỗi hiện tại; NULL = đang gọi được), `last_error`, `cells_patched` (tổng số ô đã vá nhờ nơi này) |
| `peer_view` | `peer` (tên bản sao khác `A`), `branch_id` (khoá chính kép), `state` (`ONLINE`, `SUSPECT`, `OFFLINE`, theo đánh giá của `peer`), `seconds_since_seen` (tuổi heartbeat theo đồng hồ của `peer`, chỉ để hiển thị), `received_at` (giờ bản sao NÀY nhận góc nhìn; cũ quá 15 giây thì bỏ) |
| `event_log` | `branch_id`, `movement_id` (khoá chính kép), `product_id`, `move_type`, `qty_delta`, `qty_after`, `node_time` (giờ chi nhánh tạo sự kiện), `received_at` (giờ trung tâm nhận), `kafka_partition`, `kafka_offset` (vị trí trên Redpanda, để truy vết), `kafka_ts` (timestamp Kafka của thông điệp: topic đặt `LogAppendTime` nên là giờ broker leader ghi; NULL nếu không có) |
| `sink_stats` | `id` (luôn 1), `processed`, `duplicates`, `last_event_at`, `broker_ok` (NULL = chưa kiểm), `broker_lost_at` (mốc mất broker đầu tiên của đợt hiện tại; NULL = đang đọc được), `lag` (số sự kiện trên Redpanda chưa áp, đo lần được gần nhất), `broker_checked_at` (lần kiểm gần nhất; cũ quá nghĩa là sink đã dừng), `brokers_up` (`INT[]`, mã broker sink thấy còn sống ở lần kiểm gần nhất, theo metadata; NULL = không hỏi được) |

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

**Bộ phát hiện lỗi** (vòng 5, PT-13; ngưỡng ở `docs/spec.md` mục 4):
- `branch_state(age_s)`: hàm thuần, tuổi heartbeat → `ONLINE` / `SUSPECT` / `OFFLINE`. Tuổi tính bằng `now()` của
  `replica_db` trừ `node_status.last_seen` (cùng một đồng hồ; đo thời gian chờ, không so thứ tự sự kiện, PT-05).
- `query_views(conn)`: góc nhìn của chính bản sao này, mỗi chi nhánh trong `node_status` một dòng; chỉ đọc.
- `record_peer_view(peer, payload)`: `workers/gossip.py: view_loop` gọi `GET /api/views` của bản sao `peer` xong rồi
  mới gọi hàm này. Kiểm từng dòng bằng model `BranchView` trước khi ghi (sai thì không ghi gì), rồi upsert mọi dòng của
  `peer` trong MỘT transaction, `received_at = now()`. Gọi lỗi thì không ghi gì: góc nhìn tự cũ đi.
- `majority_state(states, total)`: hàm thuần. `states` = góc nhìn của mọi bản sao (của mình và các `peer_view` còn mới,
  `None` = thiếu hoặc cũ), `total` = số bản sao cấu hình (`REPLICA_URLS`). Đủ `total // 2 + 1` góc nhìn `OFFLINE` thì
  `OFFLINE`, đủ chừng đó `ONLINE` thì `ONLINE`, còn lại `SUSPECT`.
- `query_nodes`: thêm `state` (góc nhìn của mình), `views` (`{tên bản sao: state hoặc null}`, đủ mọi bản sao cấu hình),
  `verdict` (kết luận đa số). `alive` giữ nguyên nghĩa: góc nhìn của mình không phải `OFFLINE`.

**Ghi hộ** (vòng 6, PT-14; ngữ cảnh ở `docs/spec.md` mục 4):
- `store_handoff(req)`: MỘT transaction. Khoá ô `inventory_snapshot (branch_id, product_id)` bằng `FOR UPDATE` (hai
  lượt ghi hộ cùng mã xếp hàng lần lượt, như PT-09), kiểm kết luận đa số của chính bản sao này về chi nhánh là
  OFFLINE (không thì 409 `branch_not_offline`), tồn tạm tính = `qty_on_hand` của ô trừ Σ `qty` các lượt PENDING cùng
  ô ở bản sao này; không đủ thì 422 `insufficient_stock`; không có ô thì 404 `product_not_found`. Rồi `INSERT ... ON
  CONFLICT (branch_id, request_id) DO NOTHING`: gửi lại cùng `request_id` trả lượt cũ kèm `replayed`.
- `query_handoff(conn, branch_id)`: chỉ đọc. `accepting` = kết luận đa số của bản sao này về chi nhánh là OFFLINE;
  `pending` xếp theo `handoff_id`; `stock` = tồn tạm tính từng mã.
- `record_handoff_ack(ack)`: MỘT câu `UPDATE handoff SET status, movement_id, reason, decided_at = now() WHERE
  branch_id = ... AND handoff_id = ... AND status = 'PENDING'`: ack trùng hay ack muộn không đổi lượt đã chốt.
- Bản sao không ghi gì vào CSDL chi nhánh (PT-07): chỉ đổi bảng của chính nó khi chi nhánh báo.
- Ghi hộ không đổi `inventory_snapshot` và dấu vân tay: số tồn chỉ đổi khi chi nhánh áp xong và sự kiện đi qua
  Redpanda như mọi lượt bán.

**Ô được vá không có dòng `event_log`**: gossip và đối soát chỉ mang số tồn mới nhất của ô, không mang các lượt
bán ở giữa, nên không bịa dòng nhật ký. Hệ quả: `query_events` (danh sách sự kiện trên dashboard) thiếu các lượt đó
cho tới khi sink nhận được; `processed` chỉ đếm sự kiện sink áp, nên bản sao đã lỡ sự kiện có `processed` thấp hơn
bản sao khác mãi mãi (K8: B thấp hơn A đúng số sự kiện bị bỏ qua) dù dấu vân tay khớp; `duplicates` không đổi.

**Truy vết** (`query_trace(conn, branch_id, movement_id, product_id)`, vòng 4): chỉ đọc dòng `event_log` của sự kiện
và ô `inventory_snapshot` tương ứng, rồi suy ra `via` (`docs/api.md` mục 2). Ô vá bằng gossip hoặc đối soát không có
dòng nhật ký, nên `via` dựa vào `last_movement` và `source` của ô. `apply_event(e, partition, offset, kafka_ts)` ghi
`kafka_ts` cùng câu `INSERT` với `kafka_partition`, `kafka_offset`; sự kiện trùng giữ vị trí và timestamp lần đầu.

Kiểm broker (`record_broker_check(ok, lag, brokers_up)`, sink gọi mỗi 5 giây sau khi đã hỏi Redpanda xong): một câu
`UPDATE sink_stats`. `broker_checked_at = now()`; được thì `broker_ok = true`, `broker_lost_at = NULL`, `lag` = số mới;
lỗi thì `broker_ok = false`, `broker_lost_at` giữ mốc lỗi đầu tiên, `lag` giữ số cũ. `brokers_up` luôn ghi đúng số
vừa hỏi được, kể cả khi `ok = false` (hỏi được metadata nhưng hỏi watermark lỗi, ví dụ lúc bầu leader mới); NULL nếu
không hỏi được metadata; không giữ số cũ để sơ đồ không tô xanh broker đã chết. Đo ngày 22/11/2026 (Redpanda
v24.2.8, 3 node một máy): metadata bỏ broker đã dừng ngay lần hỏi sau (ISR thì vẫn giữ cả 3 nên không dùng được),
bật lại thì có lại sau ~6 giây; mất đa số (dừng 2/3) thì sau ~2 giây không hỏi được metadata nữa, `brokers_up` = NULL.

**Dấu vân tay** (`query_digest`): `md5` của chuỗi `branch_id:product_id:qty_on_hand` của mọi dòng snapshot, sắp
theo khoá. Hai bản sao cùng dấu vân tay nghĩa là giữ đúng cùng một số liệu đến từng ô. `source` không nằm trong dấu
vân tay: cùng số mà khác nguồn vẫn là khớp.

**Snapshot chi nhánh** (`services/branch.py: snapshot`, cho đối soát): MỘT câu `SELECT` trên `inventory` JOIN LATERAL
dòng `stock_movement` mới nhất của từng mã, nên tồn và `movement_id` đọc cùng một thời điểm; PT-02 bảo đảm
`qty_on_hand` bằng `qty_after` của biến động đó. Chỉ đọc (PT-07).
