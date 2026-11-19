# tests/

pytest trên PostgreSQL thật, chạy trong container. Mục cần đọc: `docs/tests.md`.

- Chạy: `make test` (một thư mục: `make test T=tests/replica`). Không cần cài Python trên máy.
- Mỗi module một thư mục `tests/<module>/`, tên trùng file trong `api/services/`: `branch`, `replica`.
- `conftest.py`: `database` (dựng schema từ `db/*.sql` mỗi phiên), `db` (mỗi test bắt đầu trống, còn `product` và dòng
  `sink_stats`), `branch_client`, `replica_client` (gọi thẳng router, không chạy lifespan nên không có heartbeat).
  Bảng mới cần dòng dữ liệu sẵn có (như `sink_stats`) thì thêm vào fixture `db`.
- `fixtures.py`: hàm dựng dữ liệu và đọc trạng thái. Không chép SQL dựng dữ liệu sang từng file test.
- Docstring của mỗi test ghi mã quy tắc PT-xx (`docs/spec.md` mục 8).
- Không `sleep`, không gọi mạng thật. Phần gọi node khác tách thành hàm nhận dữ liệu đã lấy về, test gọi thẳng hàm đó.
- Test đỏ thì sửa code, không nới lỏng assert.

Quy tắc chung xem CLAUDE.md ở gốc repo.
