Tự duyệt thay đổi hiện tại (`git status`, `git diff`, `git diff --staged`) trước khi commit.

1. Đối chiếu với từng ý trong checklist ở `.github/pull_request_template.md`.
   Với mỗi ý: ĐẠT / KHÔNG ĐẠT / KHÔNG ÁP DỤNG, kèm file và dòng code làm bằng chứng.
2. Kiểm tra mọi tên bảng, cột, endpoint, trường sự kiện, biến môi trường, lệnh make trong thay đổi đều có trong
   `docs/`. Liệt kê tên nào không tìm thấy.
3. Đối chiếu từng quy tắc của vòng này (cột "Quy tắc" ở `docs/plan.md` mục 1) với code: quy tắc được ép ở đâu
   (file:dòng) và test nào chứng minh. Liệt kê quy tắc chưa có test.
4. Tìm: lời gọi mạng trên đường bán hàng (PT-01); lời gọi HTTP hoặc Redpanda bên trong transaction CSDL (trừ
   `workers/relay.py` có chủ đích); so thứ tự bằng `node_time` hay giờ hệ thống thay vì `movement_id` (PT-05);
   lệnh ghi từ bản sao về CSDL chi nhánh (PT-07); SQL ghép chuỗi giá trị.
5. Chạy `make check` và ghi kết quả thật.
6. Viết mô tả thay đổi theo mẫu `.github/pull_request_template.md` để tôi dùng làm nội dung pull request.
Không tự sửa code ở bước này; chỉ báo cáo. Ý nào KHÔNG ĐẠT thì đề xuất cách sửa và dừng lại.
Mọi ý đều ĐẠT thì làm theo CLAUDE.md mục Git, KHÔNG tự commit, KHÔNG push:
1. Đang ở nhánh của vòng chưa (`git branch --show-current`)? Chưa thì `git switch -c <nhánh>`.
2. `git add` đúng các file của vòng (không add `.env`), chạy `git status` để tôi thấy danh sách đã stage.
3. Viết commit message tiếng Anh theo CLAUDE.md, và lệnh để tôi tự chạy:
   `git commit -m "<dòng đầu>" -m "<thân>"` rồi `git push -u origin <nhánh>`.
