# web/

HTML + JS thuần, mỗi màn hình một file, không framework, không bước build. FastAPI phục vụ trực tiếp (file nằm
trong image: sửa xong phải build lại, `make local-up` hoặc `make up`).

- `pos.html`: màn hình quầy, do `branch_api` phục vụ; chi nhánh chết thì nginx trả chính file này cho `/cnX/`
  (`@pos_page`, vòng 6, file mount vào nginx nên sửa xong không cần build lại cho đường này). Gọi API bằng đường dẫn
  TƯƠNG ĐỐI (`api/inventory`, không có `/` đầu), vì nginx mở trang này dưới tiền tố `/cn2/`. Dạng phiếu: chế độ Bán hàng / Nhập hàng, ô tìm (gõ mã rồi
  Enter như máy quét), phiếu với số lượng 1–1000 (đúng giới hạn `StockChange`). Thanh toán gửi từng dòng một
  `api/sale` (hoặc `api/receipt`); mỗi dòng giữ một `request_id`: lỗi mạng thì giữ mã và khoá dòng để gửi lại không
  trừ hai lần (PT-08), server từ chối thì bỏ mã (`settle`). Giữ: dải trạng thái gửi (từ vòng 6b là danh sách cảnh báo), chip RTT, câu "Xử lý tại chỗ trong
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
- Cổng vào (vòng 5): nginx chạy ở mọi node. Mở qua nginx thì trang đọc `/lb/gateways.json` một lần; cổng đang dùng
  không trả lời thì gọi cổng kế tiếp (`gateList`, `nextGate`; khác origin, nginx bật CORS), không tự quay về. Dashboard:
  mọi lời gọi đi qua `getJSON` → `url()` (còn ở cổng đầu thì URL giữ nguyên), `api/overview` chờ tối đa 4 giây,
  chuyển cổng khi lỗi mạng, quá giờ hay 502–504; thanh bên ô "Cổng vào". POS: mọi lời gọi qua `call()` (chờ 4 giây,
  chuyển cổng khi lỗi mạng hay quá giờ), URL = `apiUrl(cổng, posPrefix(pathname), "api/sale")`; mở thẳng chi nhánh
  thì không có tiền tố, như cũ. Lượt bán lỗi giữa chừng giữ `request_id` (PT-08), không tự gửi lại POST.
- Ghi hộ (vòng 6, PT-14), chỉ khi mở qua nginx: `refresh()` lỗi `HANDOFF_AFTER_FAILS` (2) lần liên tiếp thì hỏi
  `/replica/<X>/api/nodes` (đúng bản sao sẽ ghi hộ). Chế độ `posMode(fails, verdict, recovery.state)`: `local`,
  `waiting` (kết luận chưa OFFLINE: khoá Thanh toán, giữ phiếu), `handoff` (bán qua `/replica/<X>/api/handoff`, bảng hàng
  là tồn tạm tính `stock`, khoá Nhập hàng và Bán 20 đơn), `recovering` (chi nhánh trả 503 `branch_recovering`: khoá
  Thanh toán). Bản sao: thứ tự `/lb/replicas.json`, giữ nguyên tới khi lỗi mạng hoặc 5xx (`nextGate`). Số chi nhánh lấy
  từ `/cnX/` khi `api/info` không trả lời (`branchFromPrefix`). `settle` giữ `request_id` cả khi gặp `branch_recovering`,
  `branch_not_offline`, 502–504. Lượt ghi hộ bị từ chối, phục hồi chưa đủ: cảnh báo P-08, P-07 (vòng 6b).
  Dashboard: `branchState` ghi "Đang phục hồi (áp ghi hộ)" khi `recovering`; bảng chi nhánh thêm cột "Ghi hộ" (chờ, đã
  áp, từ chối, `handoffTotals` cộng `digest.handoff` qua các bản sao); phục hồi, ghi hộ chờ áp, bị từ chối là cảnh báo
  D-12..D-15 (vòng 6b, dưới).
- Trạng thái chi nhánh theo kết luận đa số `verdict` (PT-13) ở bảng chi nhánh, ô "Chi nhánh hoạt động", cảnh báo;
  bảng kỹ thuật chi nhánh (tab Hệ thống) có thêm góc nhìn từng bản sao (`views`) và kết luận. SUSPECT ghi "Nghi ngờ,
  chưa đủ đa số". `alive` (góc nhìn riêng của bản sao đang trả lời) vẫn dùng cho nhãn "số cũ" và sơ đồ.
- Logic thuần (`compareViews`, `relayEdge`, `sinkEdge`, `brokerState`, `gossipEdge`, `branchState`, `alertsFrom`,
  `sortAlerts`, `trackAlerts`, `gateList`, `nextGate`, `handoffTotals`, `handoffText`; POS `settle`, `match`, `posPrefix`,
  `apiUrl`, `gateList`, `nextGate`, `posMode`, `branchFromPrefix`, `posAlerts`, `loadAcked`, `ackRejected`) nhận `now` hoặc
  dữ liệu làm tham số, kiểm bằng `?selftest=1` (chạy tay trong trình duyệt, không nằm trong `make check`). Thêm logic
  thì thêm `check(...)`.
- Màu và font đặt bằng biến CSS ở `:root`.
- Màn hình hẹp: cột grid chứa bảng phải là `minmax(0, 1fr)` (không dùng `1fr` trần), bảng rộng cuộn trong
  `.table-wrap`; nếu không, bảng `white-space: nowrap` kéo cả trang tràn ngang. Kiểm ở cỡ 375px.
- Cảnh báo (vòng 6b, danh mục D-01..D-20, P-01..P-10 ở `docs/demo.md` mục 5): dashboard `alertsFrom(input, now)` tính
  cảnh báo gốc từ overview, digest mọi bản sao, `/cn<N>/api/status`, dò cổng; mỗi sự cố một id cố định, hệ quả (`parent`)
  gộp vào "kéo theo"; `trackAlerts(state, alerts, now)` chống nháy (`ALERT_CONFIRM`), mốc "từ" (server, hoặc "~" trang
  thấy), `hold`/`ttl`, nhật ký sự cố (`localStorage` `minigo.incidents`, thẻ "Nhật ký sự cố" ở tab Hệ thống). Dải
  `#sys-alert` ở Tổng quan; D-19 ở `#conn-error`, D-20 ở `#mono`. Dò cổng `probeGates` mỗi `GATE_PROBE_S` giây
  (`GET <cổng>/lb/gateways.json`). POS: `posAlerts(ctx, now, seen)` vẽ vào `#link` (thay cho `#note` cũ), "Đã biết" cho
  lượt ghi hộ bị từ chối (`loadAcked`, `ackRejected`, `localStorage` `minigo.rejectedAck`). Thêm cảnh báo: thêm dòng danh
  mục, thêm `check` trong selftest, không gọi mạng trong hàm thuần.
- Tab Sự kiện xếp theo lúc bản sao nhận (`received_at`), nên cột giờ cũng là lúc nhận, kèm ngày khi không phải hôm
  nay; giờ chi nhánh ghi nằm ở tooltip và truy vết.
- `routers/*.py` trả trang với `Cache-Control: no-cache`: build lại image là trình duyệt thấy giao diện mới.

Quy tắc chung xem CLAUDE.md ở gốc repo.
