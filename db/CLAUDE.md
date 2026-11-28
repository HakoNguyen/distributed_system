# db/

SQL khởi tạo PostgreSQL 16. Mục cần đọc: `docs/db.md`.

- `product.sql`: danh mục sản phẩm, nạp vào CẢ hai loại CSDL (mount thành `01-product.sql`).
- `branch.sql`: `inventory`, `stock_movement`, `outbox`, `relay_status`, `handoff_rejected` (vòng 6) (mount vào
  `branch_db` thành `02-schema.sql`).
- `replica.sql`: `node_status` (cột `recovering`, vòng 6), `inventory_snapshot`, `event_log`, `sink_stats`, `sync_peer`,
  `peer_view` (vòng 5), `handoff` (vòng 6)
  (mount vào `replica_db`).
- Vòng 7: `replication.sh` (mount vào `branch_db` thành `03-replication.sh`: role `replicator`, dòng `pg_hba`
  replication), `pg-start.sh` (lệnh khởi động của `branch_db` và `branch_db_standby`: thoát nếu có `minigo.fenced`,
  `pg_basebackup -R` khi thư mục trống và có `PG_PRIMARY_HOST`, rồi `docker-entrypoint.sh postgres -c wal_keep_size=256MB`).
  Chế độ đồng bộ đặt bằng `ALTER SYSTEM` (`scripts/db.sh`), không nằm trong file nào ở đây. `docs/db.md` mục 2.
- Postgres chỉ chạy các file này khi volume trống. Sửa xong phải `make reset` trên mọi máy.
- Không có migrate.py: demo dựng lại từ đầu được, không cần nâng cấp dữ liệu cũ.

Quy tắc chung xem CLAUDE.md ở gốc repo.
