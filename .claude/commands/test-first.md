Theo kế hoạch đã duyệt, viết test trước cho: $ARGUMENTS

- Trước hết tạo nhánh của vòng (tên ở `docs/plan.md` mục 1, cách tách ở CLAUDE.md mục Git): `git switch -c <nhánh>`.
- Ghi các tên đã duyệt vào `docs/` (api.md, db.md, spec.md) và thêm model tương ứng vào `common/models.py`; bảng mới
  thêm vào `db/*.sql`. Chưa có code xử lý.
- Đặt test trong `tests/<module>/` theo quy ước ở `docs/tests.md` mục 1. Mỗi quy tắc PT-xx của vòng ít nhất một test
  cho trường hợp đúng và một test cho từng cách vi phạm có thể xảy ra (trùng, lệch thứ tự, mất kết nối giữa chừng).
- Dùng hàm dựng dữ liệu trong `tests/fixtures.py`; cần dữ liệu mới thì thêm hàm vào đó.
- Không `sleep`, không gọi mạng thật trong pytest: phần gọi HTTP sang node khác tách thành hàm nhận dữ liệu đã lấy về,
  test gọi thẳng hàm đó.
- Phần hạ tầng: viết lệnh kiểm tra vào `make check` (ví dụ `docker compose ... config -q`) hoặc script trong `scripts/`.
- Chạy `make test` và xác nhận test đang đỏ vì thiếu chức năng (404, thiếu hàm, thiếu bảng), không phải vì lỗi cú pháp,
  lỗi import hay lỗi dựng dữ liệu. Báo số test và lý do đỏ.
