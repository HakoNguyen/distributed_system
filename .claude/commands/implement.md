Viết code để các test vừa viết chuyển xanh, cho việc: $ARGUMENTS

- Làm đúng luồng dữ liệu đã duyệt ở `/plan-task`. Không thêm tính năng ngoài kế hoạch.
- Chỉ sửa các file đã liệt kê trong kế hoạch. Cần sửa file khác thì dừng và hỏi.
- Tuân thủ "Quy tắc phân tán không được vi phạm" và "Cách làm" trong CLAUDE.md (mã PT-xx ở `docs/spec.md` mục 8).
- Không sửa test để cho xanh. Nếu thấy test sai so với kế hoạch thì dừng và nêu rõ chỗ sai.
- Chạy `make check` tới khi xanh. Có thay đổi compose, nginx, giao diện thì dựng lên (`make up` hoặc `make local-up`
  khi đã có) và chạy tay kịch bản của vòng trong `docs/demo.md`.
- Báo kết quả thật: số test đạt, số test trượt, kịch bản nào đã chạy tay, phần nào chưa làm.
- Cập nhật tiến độ: `docs/plan.md` mục 1, cột "Trạng thái" trong `docs/tests.md`, và tài liệu của phần vừa làm
  (`docs/demo.md` cho kịch bản mới).
