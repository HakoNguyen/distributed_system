# db/

SQL khởi tạo PostgreSQL 16. Mục cần đọc: `docs/db.md`.

- `product.sql`: danh mục sản phẩm, nạp vào CẢ hai loại CSDL (mount thành `01-product.sql`).
- `branch.sql`: `inventory`, `stock_movement`, `outbox`, `relay_status` (mount vào `branch_db` thành `02-schema.sql`).
- `replica.sql`: `node_status`, `inventory_snapshot`, `event_log`, `sink_stats`, `sync_peer`, `peer_view` (vòng 5)
  (mount vào `replica_db`).
- Postgres chỉ chạy các file này khi volume trống. Sửa xong phải `make reset` trên mọi máy.
- Không có migrate.py: demo dựng lại từ đầu được, không cần nâng cấp dữ liệu cũ.

Quy tắc chung xem CLAUDE.md ở gốc repo.
