Bạn bắt đầu một vòng trong repo MiniGo. Việc: $ARGUMENTS

CHƯA viết code, chưa sửa file nào ngoài `docs/api.md` ở bước 4. Hãy:
1. Đọc CLAUDE.md ở gốc, CLAUDE.md của các thư mục liên quan, `docs/plan.md` (mục 1, chi tiết vòng này ở mục 5,
   mục 6), và đúng các mục của `docs/spec.md`, `docs/db.md`, `docs/api.md`, `docs/tests.md` mà vòng này dựa vào.
   Ghi rõ đã đọc mục nào (ví dụ: spec mục 8 PT-04, db.md mục 3, kịch bản K7b).
2. Tóm tắt từng việc theo luồng dữ liệu: ai gửi gì cho ai, qua kênh nào (HTTP, Redpanda, CSDL), bảng đọc, bảng ghi.
   Nêu rõ thao tác nào phải nằm trong cùng một transaction và thao tác mạng nào phải nằm NGOÀI transaction.
3. Liệt kê file sẽ tạo hoặc sửa, theo mẫu ở `docs/plan.md` mục 4. Không có file nào ngoài mẫu đó, trừ khi nêu lý do.
4. Đề xuất tên mới (bảng, cột, endpoint, trường request/response, trường sự kiện, biến môi trường, lệnh make) dạng
   bảng để tôi duyệt; sau khi tôi duyệt mới ghi vào `docs/`.
5. Liệt kê test sẽ viết: tên file, từng test, điều kiện assert, mã quy tắc PT-xx nó chứng minh. Phần hạ tầng
   (compose, nginx, script) không test được bằng pytest thì ghi lệnh kiểm tra và kết quả phải thấy.
   Kịch bản demo của vòng (Kxx ở `docs/demo.md`) ghi rõ các bước chạy tay và chỗ nhìn.
6. Liệt kê giả định và chỗ chưa rõ, kể cả giả định liên quan ở `docs/plan.md` mục 6. Không tự quyết.
Dừng lại chờ tôi duyệt.
