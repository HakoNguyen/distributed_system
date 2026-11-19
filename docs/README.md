# docs/ – Nguồn sự thật của dự án

Khi tài liệu và code lệch nhau thì dừng và báo.

| File | Nội dung |
|---|---|
| [spec.md](spec.md) | Bài toán, tính chất phân tán cần chứng minh, kiến trúc, luồng một lượt bán, mức nhất quán, giới hạn, đối chiếu Chương 2 |
| [db.md](db.md) | Bảng của CSDL chi nhánh và CSDL bản sao, khoá chống trùng, quy tắc ghi |
| [api.md](api.md) | Endpoint của chi nhánh và bản sao, định dạng sự kiện trên Redpanda, đường đi qua nginx |
| [demo.md](demo.md) | Dựng trên nhiều máy (overlay, firewall, env), giả lập trễ, kịch bản K1–K7, câu hỏi thường gặp, lỗi hay gặp |
| [tests.md](tests.md) | Quy ước kiểm thử, quy tắc PT-xx và test chứng minh, trạng thái kịch bản K1–K9 |
| [plan.md](plan.md) | Tiến độ theo vòng, quy trình 4 bước, trả lời câu hỏi của thầy, chi tiết từng vòng |

Thứ tự ưu tiên khi mâu thuẫn: `spec.md` > `db.md` > `api.md`.
