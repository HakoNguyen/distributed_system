# 🚀 HƯỚNG DẪN THỰC HÀNH DEMO THỰC CHIẾN MINIGO V2 (2 MÁY A & B)

---

### 🖥️ Màn hình & Cửa sổ chuẩn bị trước khi nói

- **Trên Máy A (Máy bạn):**
  - **Cửa sổ 1 (Trình duyệt):** Mở `http://localhost/` *(Dashboard toàn chuỗi v2 qua Nginx Cổng 80)*.
  - **Cửa sổ 2 (Trình duyệt):** Mở `http://localhost:8000/` *(Dashboard trực tiếp bản sao A)* và `http://localhost:8080` *(Redpanda Console)*.
  - **Cửa sổ 3 (Terminal):** Mở sẵn tại thư mục `d:\minigo-demo\hq`.

- **Trên Máy B (Máy bạn cùng nhóm):**
  - **Cửa sổ 1 (Trình duyệt):** Mở `http://localhost:8001/` *(Màn hình quầy POS CN2 Hà Đông)*.
  - **Cửa sổ 2 (Công cụ):** Mở sẵn phần mềm **Clumsy 0.2** (chưa bấm Start).
  - **Cửa sổ 3 (Terminal):** Mở sẵn tại thư mục `minigo-demo/branch`.

---

### 📢 PHẦN 1: Mở màn & Giới thiệu tổng quan (30 giây)

* **Thao tác:** Đứng ở tab Dashboard `http://localhost/` trên Máy A.
* **Lời nói:**
  > *"Thưa thầy/cô, đây là bản demo Hệ thống Kho phân tán MiniGo v2. Hệ thống gồm 2 Chi nhánh bán hàng độc lập (CN1 Cầu Giấy trên Máy A, CN2 Hà Đông trên Máy B) và 2 Bản sao Trung tâm (Replica A và Replica B) tự đồng bộ bất đồng bộ qua Redpanda Kafka Broker. Toàn bộ người dùng truy cập qua cổng vào duy nhất là Nginx Load Balancer."*

---

### 🎬 PHẦN 2: Thao tác & Thuyết minh từng Kịch bản Chi tiết

---

#### 🔹 Kịch bản 1: Bán hàng tại chỗ & Trong suốt vị trí qua Nginx Load Balancer

* **Thao tác:** 
  1. Trên Máy B (POS CN2 `http://localhost:8001`), bấm nút **"Bán 1"** 3 lần hoặc bấm **"Bán 20 đơn ngẫu nhiên"**.
  2. Trên Máy A, nhìn vào Dashboard Nginx (`http://localhost/`).
* **Thấy:**
  - Trên POS Máy B: Phản hồi **"Xử lý tại chỗ trong < 20 ms"**, phía dưới báo độ trễ RTT tới các bản sao (ví dụ: `Bản sao máy A: 15 ms`, `Bản sao máy B: 2 ms`).
  - Trên Dashboard Máy A: Cột CN2 nháy vàng, số lượng tồn kho giảm ngay lập tức.
  - Nhìn góc phải trên Dashboard: Dòng chữ *"Lần làm mới này do bản sao máy **A** (hoặc **B**) trả lời"* thay đổi luân phiên (`A B A B`).
* **Nói (Ăn điểm):**
  > *"Thao tác bán diễn ra hoàn toàn tại CSDL cục bộ của quầy (Local Transaction) nên phản hồi chỉ mất vài mili-giây. Việc báo cáo lên Trung tâm diễn ra **bất đồng bộ (Asynchronous)** qua tiến trình `relay` đẩy vào Kafka. Người xem Dashboard truy cập qua Nginx Cổng 80 nhìn thấy 1 bảng tồn duy nhất mà không cần biết dữ liệu đang nằm ở máy nào – đây là tính **Trong suốt vị trí (Location Transparency)**."*

---

#### 🔹 Kịch bản 2: Tắt mạng Máy B — Lỗi cục bộ & Nhất quán cuối (KỊCH BẢN ĂN ĐIỂM NHẤT ⭐)

* **Thao tác:**
  1. Trên Máy B, **Tắt Wi-Fi** (hoặc chạy lệnh dừng relay: `docker compose -p minigo-cn2 --env-file cn2.env stop relay`).
  2. Tại quầy POS Máy B (`http://localhost:8001`), bấm **Bán 10 đơn**.
  3. Trên Máy A, truy cập đường dẫn `http://localhost/cn2/` (thử vào quầy CN2 qua Nginx Máy A).
  4. Mở lại Wi-Fi trên Máy B (hoặc chạy: `docker compose -p minigo-cn2 --env-file cn2.env start relay`).
* **Thấy:**
  - **Lúc tắt mạng:** POS Máy B chuyển dải màu đỏ báo *"Chưa gửi được... 10 sự kiện đang chờ trong outbox"*, nhưng thu ngân **vẫn bấm bán bình thường**, số tồn tại quầy vẫn trừ.
  - **Trên Dashboard Máy A:** Sau 15 giây, thẻ CN2 Hà Đông hiện sọc đỏ báo *"Mất liên lạc"*, cột số liệu CN2 bị xám nghiêng gắn nhãn *"số cũ"*. Vệt Nginx chỉ còn toàn chữ `A`. Đường dẫn `http://localhost/cn2/` hiện trang báo lỗi 503 vô cùng thân thiện.
  - **Lúc bật lại mạng:** Sau 5-10 giây, tiến trình `relay` báo *"Đã gửi 10 sự kiện"*, outbox về 0. Dashboard Máy A tự động chuyển lại màu xanh tươi, vệt `B` quay trở lại, số liệu 2 máy khớp 100%.
* **Nói (Ăn điểm):**
  > *"Đây thể hiện tính **Lỗi cục bộ (Partial Failure)**: Chi nhánh B mất mạng thì cửa hàng B vẫn bán được hàng bình thường, Trung tâm và CN1 vẫn hoạt động. Dữ liệu được bảo vệ an toàn nhờ **Outbox Pattern** (At-least-once). Khi có mạng lại, hệ thống tự động đồng bộ bù mà không cần con người can thiệp – đây chính là **Nhất quán cuối (Eventual Consistency)**."*

---

#### 🔹 Kịch bản 3: Tắt Trung tâm — Tách rời thời gian và tham chiếu (Decoupling)

* **Thao tác:**
  1. Trên Máy A (Terminal `hq`), tạm dừng tiến trình `sink`:
     ```powershell
     docker compose -p minigo-hq --env-file hq.env --profile core stop sink
     ```
  2. Bấm **Bán 5 đơn** tại POS Máy A (CN1) và POS Máy B (CN2).
  3. Kiểm tra hàng chờ Kafka bằng lệnh:
     ```powershell
     docker compose -p minigo-hq --env-file hq.env --profile core exec redpanda rpk group describe replica-A
     ```
  4. Bật lại tiến trình `sink`:
     ```powershell
     docker compose -p minigo-hq --env-file hq.env --profile core start sink
     ```
* **Thấy:**
  - Khi `sink` tắt: Dashboard đứng yên số liệu, nhưng lệnh `rpk` cho thấy cột `LAG` tăng lên 5 (sự kiện đang nằm chờ trong Redpanda).
  - Khi `sink` bật lại: Cột `LAG` về 0, Dashboard tự động nhảy bù đủ 5 đơn vừa bán.
* **Nói (Ăn điểm):**
  > *"Kiến trúc **Publish-Subscribe** qua Kafka giúp **tách rời về thời gian và tham chiếu (Decoupling)**. Chi nhánh gửi sự kiện mà không cần biết bên nhận là ai và không cần bên nhận phải đang hoạt động."*

---

#### 🔹 Kịch bản 4: Chống trùng lặp & Chống lệch thứ tự (Idempotency)

* **Thao tác:**
  1. Cho thầy/cô xem bảng **"Các bản sao trung tâm"** trên Dashboard: Mã băm dữ liệu (**Fingerprint**) của Replica A và Replica B giống hệt nhau (ví dụ: `a1b2c3d4`).
  2. Trên Máy A, chạy lệnh phát lại toàn bộ sự kiện từ đầu:
     ```powershell
     docker compose -p minigo-hq --env-file hq.env --profile core exec redpanda rpk group seek replica-A --to start
     ```
* **Thấy:**
  - Dòng thống kê ở góc trên Dashboard: Số *"bỏ qua X bản trùng"* tăng vọt lên.
  - Bảng tồn kho và mã **Fingerprint** không hề bị thay đổi hay biến động một con số nào.
* **Nói (Ăn điểm):**
  > *"Hệ thống đảm bảo tính **Idempotent** (khả nạp). Nhờ khoá chính `(branch_id, movement_id)` tại CSDL Trung tâm, dù mạng chập chờn gửi lặp sự kiện hay ta phát lại từ đầu thì số liệu tồn kho vẫn đúng 100%."*

---

#### 🔹 Kịch bản 5: Giả lập độ trễ mạng cao bằng Clumsy (Mạng chập chờn)

* **Thao tác:**
  1. Trên Máy B, mở phần mềm **Clumsy 0.2**.
  2. Nhập Filtering: `outbound and (tcp.DstPort == 8000 or tcp.DstPort == 19092)`.
  3. Tích chọn **Lag**: gõ `300` (ms) -> Bấm **Start**.
  4. Bấm **Bán 1** trên POS Máy B.
  5. Tích thêm **Drop**: `20` (%) -> Bấm **Stop** Clumsy sau 10 giây.
* **Thấy:**
  - Chip RTT trên POS Máy B tăng vọt lên **≥ 500 ms** (do thời gian đi + về).
  - Tuy nhiên, dòng chữ *"Xử lý tại chỗ"* của quầy POS **vẫn dưới 20 ms**!
  - Sau khi Stop Clumsy, mã Fingerprint giữa Máy A và Máy B vẫn khớp hoàn toàn.
* **Nói (Ăn điểm):**
  > *"Dù đường truyền mạng giữa Chi nhánh và Trung tâm bị trễ cao (lag 300ms) hay mất gói (drop 20%), tốc độ bán hàng tại quầy vẫn không hề bị ảnh hưởng. Dữ liệu cuối cùng vẫn tự khớp tuyệt đối."*

---

#### 🔹 Kịch bản 6: Kiểm tra tính cách ly CSDL (Isolation)

* **Thao tác:** Trên Máy B, mở Terminal chạy lệnh truy vấn trực tiếp CSDL Chi nhánh 2:
  ```powershell
  docker compose -p minigo-cn2 --env-file cn2.env exec db psql -U app -d kho -c "SELECT branch_id, count(*) FROM inventory GROUP BY 1;"
  ```
* **Thấy:** Kết quả chỉ trả về đúng 1 dòng duy nhất có `branch_id = 2`.
* **Nói (Ăn điểm):**
  > *"Mỗi chi nhánh chỉ nắm giữ đúng mảnh dữ liệu của chính mình (Partitioned Data). Không chi nhánh nào có thể đọc hay sửa trực tiếp CSDL của chi nhánh khác."*

---

### 💡 BẢNG TRA CỨU 5 TỪ KHÓA VÀNG ĐÁP TRẢ THẦY CÔ

| Thầy cô hỏi | Trả lời bằng Từ khóa | Giải thích ngắn gọn |
|---|---|---|
| *"Lỡ mất mạng giữa chừng thì sao?"* | **Partial Failure & Outbox Pattern** | Quầy vẫn bán bình thường nhờ ghi event vào bảng `outbox` cùng transaction với trừ tồn. |
| *"Làm sao biết dữ liệu 2 nơi giống nhau?"* | **Eventual Consistency & Fingerprint** | Mạng có lại dữ liệu tự đồng bộ bù; so sánh mã băm MD5 toàn bộ snapshot giữa các bản sao. |
| *"Gửi lặp 2 lần có bị trừ tồn 2 lần không?"* | **Idempotency (Khả nạp)** | Trung tâm dùng khoá `(branch_id, movement_id)`. Đã thấy rồi thì bỏ qua không trừ lần 2. |
| *"Sao người dùng không cần biết IP của từng máy?"* | **Location Transparency (Nginx)** | Nginx làm cổng vào duy nhất (Port 80) tự điều hướng và chia tải (Load Balancing). |
| *"Nếu Trung tâm quá tải/sập thì cửa hàng có sập không?"* | **Decoupling (Tách rời)** | Chi nhánh và Trung tâm giao tiếp qua Redpanda Kafka Broker nên độc lập hoàn toàn về thời gian. |

---

## 📋 BẢNG NGHIỆM THU TIÊU CHÍ CHẠY LIÊN MÁY

| Yêu cầu | Đạt khi | Kiểm ở đâu |
|---|---|---|
| **Chạy trên ≥ 2 máy thật, nối bằng overlay** | Hai máy thấy nhau qua IP `100.x` (Tailscale), cả hai chạy đủ container | `tailscale status`, `ping`, `docker compose ps` |
| **Trong suốt vị trí (Nginx, một IP)** | Mở `http://<IP_A>/` thấy vệt `A B A B`; `/cn2/` mở được POS máy B | Dashboard qua Nginx, `curl -I` |
| **Chịu lỗi & Failover** | Rút mạng B: Dashboard Nginx không báo lỗi, vệt chỉ còn `A`, POS B vẫn bán bình thường | Dashboard A, POS B |
| **Tự phục hồi (Eventual Consistency)** | Cắm lại mạng: outbox về 0 trong ≤ 30s, dấu vân tay A và B khớp trong ≤ 60s | Bảng bản sao, POS B |
| **Đồng bộ dữ liệu real-time** | Bán ở B, Dashboard A đổi trong ≤ 3s; A và B cùng dấu vân tay (Fingerprint) | Dashboard A |
| **Độ trễ mạng (RTT)** | Bật Clumsy trễ 300ms: RTT ≥ 500ms nhưng POS vẫn "xử lý tại chỗ" < 20ms | Chip RTT trên POS B, thẻ CN2 |
| **Chống trùng (Idempotency)** | Phát lại toàn bộ sự kiện: số bản trùng tăng vọt, dấu vân tay **không đổi** | Tab `http://localhost:8000` |
