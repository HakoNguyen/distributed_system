# web/

HTML + JS thuần, mỗi màn hình một file, không framework, không bước build. FastAPI phục vụ trực tiếp (file nằm
trong image: sửa xong phải build lại, `make local-up` hoặc `make up`).

- `pos.html`: màn hình quầy, do `branch_api` phục vụ. Gọi API bằng đường dẫn TƯƠNG ĐỐI (`api/inventory`, không có
  `/` đầu), vì nginx mở trang này dưới tiền tố `/cn2/`. Một ô "Số lượng" chung (1–1000, đúng giới hạn `StockChange`),
  kiểm ngay trên trình duyệt trước khi gửi.
- `dashboard.html`: dashboard toàn chuỗi, do `replica_api` phục vụ. Bố cục: thanh bên (menu tab, bản sao đang trả
  lời, đồng bộ, cảnh báo đọc đơn điệu, selftest) và bốn tab `#tong-quan`, `#ton-kho`, `#su-kien`, `#ban-sao` (tab
  đang mở nằm trong `location.hash`, `docs/demo.md` mục 5 dùng các tên này). Mọi tab vẫn được vẽ mỗi lần làm mới, tab
  ẩn chỉ có thuộc tính `hidden`. Mỗi lần làm mới gọi một `api/overview` để số
  không bị trộn giữa hai bản sao. Đọc đơn điệu (`docs/spec.md` mục 5): chỉ nhận phản hồi mà mọi ô có
  `last_movement` không cũ hơn số đang hiện (`compareViews`), không thì giữ nguyên phản hồi cũ và gắn nhãn bản sao
  trễ. Phần chỉ có khi mở qua nginx: bảng so bản sao và sơ đồ topology gọi `/lb/replicas.json`,
  `/replica/<X>/api/digest`, `/cn<N>/api/status`; truy vết gọi `/cn<N>/api/movement/{id}` và
  `/replica/<X>/api/trace`. Mở thẳng một bản sao thì chỉ có góc nhìn của bản sao đó.
- Logic thuần (`compareViews`, `relayEdge`, `sinkEdge`, `brokerState`, `gossipEdge`) nhận `now` làm tham số, kiểm
  bằng `?selftest=1` (chạy tay trong trình duyệt, không nằm trong `make check`). Thêm logic thì thêm `check(...)`.
- Màu và font đặt bằng biến CSS ở `:root`.

Quy tắc chung xem CLAUDE.md ở gốc repo.
