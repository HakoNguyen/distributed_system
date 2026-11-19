# web/

HTML + JS thuần, mỗi màn hình một file, không framework, không bước build. FastAPI phục vụ trực tiếp.

- `pos.html`: màn hình quầy, do `branch_api` phục vụ. Gọi API bằng đường dẫn TƯƠNG ĐỐI (`api/inventory`, không có
  `/` đầu), vì nginx mở trang này dưới tiền tố `/cn2/`.
- `dashboard.html`: dashboard toàn chuỗi, do `replica_api` phục vụ. Mỗi lần làm mới gọi một `api/overview` để số
  không bị trộn giữa hai bản sao; bảng so bản sao gọi `/lb/replicas.json` và `/replica/<X>/api/digest` (chỉ có khi
  mở qua nginx).
- Màu và font đặt bằng biến CSS ở `:root`.

Quy tắc chung xem CLAUDE.md ở gốc repo.
