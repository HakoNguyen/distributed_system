## Vòng và việc đã làm
<!-- ví dụ: Vòng 2 – cụm 3 broker, trạng thái đồng bộ trên dashboard (PT-11) -->

## Test
<!-- file test và kết quả; kết quả make check; kịch bản đã chạy tay (K7a đạt, K7b đạt) -->

## File đã sửa
<!-- theo mẫu ở docs/plan.md mục 4; file nào ngoài mẫu thì ghi lý do -->

## Checklist
- [ ] Mọi tên bảng, cột, endpoint, trường sự kiện, biến môi trường, lệnh make mới đều có trong `docs/`
- [ ] PT-01: đường bán hàng không có lời gọi mạng nào
- [ ] PT-02: sửa tồn, sổ cái, outbox trong một transaction
- [ ] PT-03, PT-06: chỉ đánh dấu đã gửi / commit offset sau khi bên kia xác nhận, sau khi ghi CSDL xong
- [ ] PT-04, PT-05, PT-10: áp và merge lũy đẳng, so thứ tự bằng `movement_id`, không dùng đồng hồ
- [ ] PT-07: bản sao không ghi về chi nhánh
- [ ] Không gọi HTTP bên trong transaction CSDL (lấy dữ liệu về trước, ghi sau)
- [ ] SQL tham số hóa; không thêm thư viện ngoài danh sách ở CLAUDE.md
- [ ] Mỗi quy tắc của vòng có test; `make check` xanh
- [ ] Kịch bản demo của vòng đã chạy tay và đạt
- [ ] Đã cập nhật `docs/plan.md` mục 1 và `docs/tests.md`

## Giả định còn mở
