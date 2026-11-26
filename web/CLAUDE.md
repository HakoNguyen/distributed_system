# web/

HTML + JS thuần, mỗi màn hình một file, không framework, không bước build. FastAPI phục vụ trực tiếp (file nằm
trong image: sửa xong phải build lại, `make local-up` hoặc `make up`).

- `pos.html`: màn hình quầy, do `branch_api` phục vụ. Gọi API bằng đường dẫn TƯƠNG ĐỐI (`api/inventory`, không có
  `/` đầu), vì nginx mở trang này dưới tiền tố `/cn2/`. Dạng phiếu: chế độ Bán hàng / Nhập hàng, ô tìm (gõ mã rồi
  Enter như máy quét), phiếu với số lượng 1–1000 (đúng giới hạn `StockChange`). Thanh toán gửi từng dòng một
  `api/sale` (hoặc `api/receipt`); mỗi dòng giữ một `request_id`: lỗi mạng thì giữ mã và khoá dòng để gửi lại không
  trừ hai lần (PT-08), server từ chối thì bỏ mã (`settle`). Giữ: dải trạng thái gửi, chip RTT, câu "Xử lý tại chỗ trong
  … ms", nút "Bán 20 đơn ngẫu nhiên" (mục Công cụ demo), vì kịch bản K1–K9 dùng. Tự kiểm: `?selftest=1`.
- `dashboard.html`: dashboard trụ sở, do `replica_api` phục vụ. Thanh bên (menu, bản sao trả lời, đồng bộ tóm tắt,
  selftest) và bốn tab `#tong-quan` (ô số liệu, bảng chi nhánh, cần đặt thêm hàng), `#ton-kho` (tìm, lọc dưới
  ngưỡng), `#su-kien` (danh sách, truy vết), `#he-thong` (đồng bộ của bản sao đang trả lời, sơ đồ, bảng kỹ thuật
  chi nhánh, bảng bản sao). Tab đang mở nằm trong `location.hash`; `docs/demo.md` mục 5 dùng các tên này. Tab ẩn bằng
  thuộc tính `hidden` (luật `[hidden]` có `!important` vì panel có `display` riêng); mọi tab vẫn được vẽ mỗi lần làm
  mới. Mỗi lần làm mới gọi một `api/overview` để số không bị trộn giữa hai bản sao. Đọc đơn điệu
  (`docs/spec.md` mục 5): chỉ nhận phản hồi mà mọi ô có `last_movement` không cũ hơn số đang hiện (`compareViews`),
  không thì giữ nguyên phản hồi cũ và gắn nhãn bản sao trễ. Phần chỉ có khi mở qua nginx: bảng bản sao và sơ đồ gọi
  `/lb/replicas.json`, `/replica/<X>/api/digest`, `/cn<N>/api/status`; truy vết gọi `/cn<N>/api/movement/{id}` và
  `/replica/<X>/api/trace`. Mở thẳng một bản sao thì chỉ có góc nhìn của bản sao đó.
- Logic thuần (`compareViews`, `relayEdge`, `sinkEdge`, `brokerState`, `gossipEdge`, `branchState`, `systemIssues`) nhận `now` hoặc
  dữ liệu làm tham số, kiểm bằng `?selftest=1` (chạy tay trong trình duyệt, không nằm trong `make check`). Thêm logic
  thì thêm `check(...)`.
- Màu và font đặt bằng biến CSS ở `:root`.
- Màn hình hẹp: cột grid chứa bảng phải là `minmax(0, 1fr)` (không dùng `1fr` trần), bảng rộng cuộn trong
  `.table-wrap`; nếu không, bảng `white-space: nowrap` kéo cả trang tràn ngang. Kiểm ở cỡ 375px.
- Tổng quan có dải `#sys-alert` (`systemIssues`): broker nào không chạy, bản sao nào không liên lạc được, đồng bộ
  dừng; trùng nguồn với chấm đỏ của tab Hệ thống, để trang đầu không báo "ổn" khi hệ đang suy giảm.
- Tab Sự kiện xếp theo lúc bản sao nhận (`received_at`), nên cột giờ cũng là lúc nhận, kèm ngày khi không phải hôm
  nay; giờ chi nhánh ghi nằm ở tooltip và truy vết.
- `routers/*.py` trả trang với `Cache-Control: no-cache`: build lại image là trình duyệt thấy giao diện mới.

Quy tắc chung xem CLAUDE.md ở gốc repo.
