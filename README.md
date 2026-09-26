# MiniGo demo: hệ thống kho phân tán chạy trên 2 máy

Bản demo cho môn Các hệ thống phân tán. Đây là lát cắt lõi của đề tài kho MiniGo:

> Chi nhánh bán hàng trên CSDL của chính nó → ghi sự kiện → gửi qua mạng thật → trung tâm tổng hợp thành bảng tồn toàn chuỗi.

Các tính chất phân tán demo cho thấy được:

- **Lỗi cục bộ (partial failure).** Rút mạng máy B thì chi nhánh vẫn bán được, trung tâm vẫn chạy. Chỉ có số liệu của CN2 đứng lại và bị đánh dấu "số cũ".
- **Nhất quán cuối (eventual consistency).** Cắm mạng lại thì số liệu tự khớp, không cần ai làm gì.
- **Không có đồng hồ chung.** Giờ hai máy lệch nhau, nên thứ tự sự kiện phải dựa vào số thứ tự chứ không dựa vào giờ.
- **Tách rời nhờ publish–subscribe.** Bên gửi và bên nhận không cần chạy cùng lúc và không cần biết nhau.
- **Trong suốt vị trí.** Người xem dashboard thấy một bảng tồn duy nhất, không cần biết số đến từ máy nào.

---

## 1. Hình dung toàn cảnh

```
            MÁY B                                            MÁY A
 ┌───────────────────────────┐              ┌──────────────────────────────────────────┐
 │  Chi nhánh 2 (Hà Đông)    │              │  Trung tâm (HQ)                          │
 │                           │              │                                          │
 │  Trình duyệt: màn hình POS│              │   ┌──────────┐   ┌───────┐   ┌────────┐  │
 │        │                  │   heartbeat  │   │ api_hq   │──▶│ db    │◀──│ sink   │  │
 │        ▼                  │  (HTTP 8000) │   │ dashboard│   │ (HQ)  │   │        │  │
 │   ┌─────────┐   ┌──────┐  │ ───────────▶ │   └──────────┘   └───────┘   └────▲───┘  │
 │   │ api_cn2 │──▶│ db   │  │              │                                   │      │
 │   └─────────┘   │ (CN2)│  │              │                         ┌─────────┴────┐ │
 │                 └──▲───┘  │   sự kiện    │                         │  redpanda    │ │
 │   ┌─────────┐      │      │ (Kafka 19092)│                         │  topic       │ │
 │   │ relay   │──────┘      │ ───────────────────────────────────▶   │  inventory.  │ │
 │   │         │ đọc outbox  │              │                         │  movement    │ │
 │   └─────────┘             │              │                         └──────▲───────┘ │
 └───────────────────────────┘              │                                │         │
                                            │  Chi nhánh 1 (Cầu Giấy): api_cn1, db,    │
                                            │  relay — y hệt máy B, gửi vào cùng chỗ ──┘
                                            └──────────────────────────────────────────┘
```

Máy A chạy trung tâm và chi nhánh 1. Máy B chạy chi nhánh 2. Hai máy chỉ nói chuyện với nhau qua hai đường: heartbeat (HTTP) và sự kiện (Kafka). Không ai đọc thẳng CSDL của ai.

### Một lượt bán đi qua những đâu

1. Nhân viên bấm **Bán 1** trên POS của CN2 (máy B).
2. `api_cn2` mở **một transaction** trên CSDL của CN2, làm ba việc: trừ tồn trong `inventory`, ghi một dòng vào sổ cái `stock_movement`, ghi một dòng vào `outbox`. Commit. Khách nhận hàng, xong, chỉ mất vài mili giây. Đến đây chưa có gì đi qua mạng.
3. `relay` (một tiến trình khác trên máy B) thấy dòng outbox mới, gửi nó qua mạng lên Redpanda ở máy A, chờ Redpanda xác nhận rồi mới đánh dấu `sent_at`.
4. `sink` ở máy A nhận sự kiện, kiểm tra xem đã thấy nó chưa. Nếu chưa, cập nhật `inventory_snapshot`.
5. Dashboard đọc `inventory_snapshot` mỗi 2 giây, và số trên màn hình đổi, kèm hiệu ứng nháy vàng.

Nếu mạng đứt ở bước 3 thì bước 1–2 vẫn chạy bình thường. Sự kiện nằm chờ trong outbox, và khi có mạng lại, relay gửi tiếp từ đúng chỗ dừng.

---

## 2. Cấu trúc thư mục

```
minigo-demo/
├── shared/products.sql        Danh mục 20 mã hàng, nạp giống nhau vào mọi node
├── branch/                    Mọi thứ của MỘT chi nhánh (dùng chung cho CN1, CN2, CN3)
│   ├── docker-compose.yml     3 container: db, api, relay
│   ├── cn1.env  cn2.env  cn3.env   Chỗ khác nhau duy nhất giữa các chi nhánh
│   ├── db/schema.sql          inventory, stock_movement, outbox
│   └── app/
│       ├── main.py            api_cn: bán, nhập, xem tồn, heartbeat
│       ├── relay.py           outbox → Redpanda
│       └── static/pos.html    Màn hình quầy
└── hq/                        Trung tâm
    ├── docker-compose.yml     5 container: redpanda, console, db, api, sink
    ├── hq.env                 IP của máy A
    ├── db/schema.sql          inventory_snapshot, event_log, node_status, sink_stats
    └── app/
        ├── main.py            api_hq: nhận heartbeat, API cho dashboard
        ├── sink.py            Redpanda → bảng tổng hợp, có chống trùng
        └── static/dashboard.html
```

Mỗi file Python đều có chú thích tiếng Việt giải thích từng bước, nên đọc code song song với tài liệu này sẽ dễ hiểu nhất. Nên đọc theo thứ tự: `branch/app/main.py` → `relay.py` → `hq/app/sink.py`.

---

## 3. Chuẩn bị

Cần trên **cả hai máy**:

- Docker Desktop (Windows/macOS) hoặc Docker Engine + Compose plugin (Linux). Kiểm tra bằng `docker compose version`.
- Toàn bộ thư mục `minigo-demo` (copy qua USB, git, hay cách nào cũng được).

Máy A nên có từ 8 GB RAM, vì phải chạy 8 container. Máy B chỉ chạy 3 container nhỏ.

> **Người dùng Windows:** nếu sửa file bằng Notepad cũ, xuống dòng có thể bị đổi thành kiểu Windows (CRLF). Các file ở đây không có script shell nên thường không sao, nhưng nếu dùng git thì file `.gitattributes` đã ép sẵn kiểu LF.

---

## 4. Bước 1: chạy thử mọi thứ trên máy A

Làm cho chạy được trên một máy trước, rồi mới tách ra. Như vậy khi có lỗi sẽ biết là lỗi code hay lỗi mạng.

### 4.1. Tìm IP của máy A

| Hệ điều hành | Lệnh | Tìm dòng |
|---|---|---|
| Windows | `ipconfig` | IPv4 Address của card Wi-Fi |
| macOS | `ipconfig getifaddr en0` | in ra luôn |
| Linux | `hostname -I` | địa chỉ đầu tiên |

Ví dụ ra `192.168.1.10`.

### 4.2. Điền IP vào ba file env

Sửa dòng `HQ_HOST=` trong `hq/hq.env`, `branch/cn1.env`, `branch/cn2.env` thành IP vừa tìm.

**Tại sao không dùng `localhost`?** Bên trong một container, `localhost` là chính container đó, không phải máy A. Relay của CN1 gọi `localhost:19092` sẽ gọi vào chính nó và không thấy gì. Dùng IP LAN thì container nào, máy nào cũng tới được đúng chỗ.

### 4.3. Bật trung tâm

```bash
cd hq
docker compose -p minigo-hq --env-file hq.env up -d --build
docker compose -p minigo-hq --env-file hq.env ps
```

Chờ khoảng 30 giây, cột STATUS của cả 5 container phải là `running` (redpanda và db có thêm `healthy`). Mở http://localhost:8000: dashboard hiện ra, báo chưa có chi nhánh nào.

`-p minigo-hq` đặt tên cho nhóm container. Tên riêng cho từng nhóm giúp chạy trung tâm và chi nhánh trên cùng máy mà không đụng nhau.

### 4.4. Bật chi nhánh 1 (vẫn trên máy A)

```bash
cd ../branch
docker compose -p minigo-cn1 --env-file cn1.env up -d --build
```

Mở http://localhost:8001: màn hình POS của CN1. Trong khoảng 5–10 giây, dashboard ở cổng 8000 hiện thẻ **CN1 Cầu Giấy — Đang hoạt động** và bảng tồn có cột CN1.

Bấm **Bán 1** ở POS, nhìn sang dashboard: ô tương ứng nháy vàng, số giảm 1, và bên phải xuất hiện sự kiện mới. Nếu thấy như vậy thì toàn bộ đường đi đã thông.

### 4.5. (Tuỳ chọn) Thử CN2 ngay trên máy A

Để chắc cấu hình CN2 đúng trước khi mang sang máy B, có thể chạy tạm trên máy A với cổng khác:

```bash
docker compose -p minigo-cn2 --env-file cn2.env up -d --build   # sửa API_PORT=8002 trước, nhớ đổi lại 8001 khi mang sang máy B
```

Thấy chạy ổn thì tắt và xoá dữ liệu để máy B khởi tạo lại từ đầu:

```bash
docker compose -p minigo-cn2 --env-file cn2.env down -v
```

---

## 5. Bước 2: đưa CN2 sang máy B

### 5.1. Nối hai máy vào cùng một mạng

**Cách chắc ăn nhất là phát hotspot từ điện thoại và cho cả hai laptop vào.** Wi-Fi trường thường bật chế độ cách ly thiết bị (client isolation), nên hai máy cùng Wi-Fi vẫn không gọi được nhau.

Cách dự phòng là cài [Tailscale](https://tailscale.com) trên cả hai máy, đăng nhập cùng tài khoản, rồi dùng IP `100.x.x.x` của máy A làm `HQ_HOST`. Cách này chạy được qua mọi mạng, kể cả khi hai máy ở hai nơi.

Đổi mạng thì IP máy A sẽ đổi, nên phải sửa lại `HQ_HOST` ở mọi file env và chạy lại `up -d` (xem mục 8).

### 5.2. Mở cổng trên máy A

Máy B cần gọi tới hai cổng của máy A: **8000** (heartbeat) và **19092** (Redpanda).

- Windows: mở PowerShell bằng quyền Administrator:
  ```powershell
  New-NetFirewallRule -DisplayName "MiniGo" -Direction Inbound -Protocol TCP -LocalPort 8000,19092 -Action Allow
  ```
- macOS: thường có hộp thoại hỏi cho phép kết nối vào, bấm Allow.
- Linux có ufw: `sudo ufw allow 8000,19092/tcp`

### 5.3. Kiểm tra từ máy B trước khi chạy

```bash
curl http://192.168.1.10:8000/health          # phải ra {"status":"ok"}
```

```powershell
Test-NetConnection 192.168.1.10 -Port 19092     # Windows: TcpTestSucceeded : True
```

```bash
nc -vz 192.168.1.10 19092                       # macOS/Linux: succeeded
```

Cả hai cổng thông thì mới chạy tiếp. Không thông thì xem mục 8.

### 5.4. Bật CN2 trên máy B

```bash
cd minigo-demo/branch
docker compose -p minigo-cn2 --env-file cn2.env up -d --build
docker compose -p minigo-cn2 --env-file cn2.env logs -f relay
```

Log relay phải có dòng `Đã gửi 20 sự kiện`: đó là 20 dòng tồn ban đầu đi lên trung tâm. Dashboard trên máy A hiện thêm thẻ CN2 và cột CN2.

Mở POS trên máy B tại http://localhost:8001. Đến đây đã có hệ phân tán chạy trên hai máy thật.

---

## 6. Kịch bản demo

Khi thuyết trình, dùng hai màn hình: máy B mở POS, máy A mở dashboard (và tab http://localhost:8080 của Redpanda Console nếu muốn cho xem sự kiện thô).

Để gõ lệnh ngắn hơn, có thể tạo alias. Trên macOS/Linux:

```bash
alias hq='docker compose -p minigo-hq --env-file hq.env'       # chạy trong thư mục hq/
alias cn2='docker compose -p minigo-cn2 --env-file cn2.env'    # chạy trong thư mục branch/
```

Trên PowerShell: `function hq { docker compose -p minigo-hq --env-file hq.env @args }`. Các lệnh dưới đây viết đầy đủ.

### Kịch bản 1: Bán ở máy này, số đổi ở máy kia

**Làm:** Bấm **Bán 1** vài lần trên POS máy B.

**Thấy:** Sau khoảng 1–2 giây, ô CN2 trên dashboard máy A nháy vàng và giảm số. Sự kiện hiện ở cột bên phải với độ trễ tính bằng mili giây.

**Nói:** Người xem dashboard thấy một bảng tồn duy nhất và không cần biết dữ liệu nằm ở máy nào. Đó là **tính trong suốt vị trí**. Việc bán hoàn tất ngay trên máy B mà không chờ trung tâm; việc báo lên là **bất đồng bộ**.

### Kịch bản 2: Rút mạng máy B (cảnh ăn điểm nhất)

**Làm:**
1. Tắt Wi-Fi trên máy B.
2. Trên POS máy B, bấm **Bán 20 đơn ngẫu nhiên**.
3. Chờ khoảng 20 giây, rồi bật Wi-Fi lại.

**Thấy:**
- Trong lúc mất mạng, POS máy B vẫn bán bình thường. Dải trạng thái chuyển đỏ, báo số sự kiện đang chờ trong outbox (con số tăng dần).
- Sau 15 giây, dashboard máy A tô sọc đỏ thẻ CN2 với dòng "Mất liên lạc … giây". Cột CN2 trong bảng chuyển nghiêng xám kèm nhãn "số cũ". CN1 vẫn chạy bình thường.
- Khi bật mạng, trong vài giây relay gửi hết phần tồn đọng, số CN2 trên dashboard khớp với máy B, và các sự kiện vừa tới được đánh dấu **Đến muộn** kèm độ trễ.

**Nói:** Đây là **lỗi cục bộ**: một phần hệ thống hỏng, phần còn lại vẫn chạy, điều mà hệ tập trung không có. Hệ chọn **sẵn sàng hơn nhất quán** (đánh đổi CAP): cửa hàng không được ngừng bán, còn báo cáo chậm vài phút thì chấp nhận được. Khi mạng về, hệ **nhất quán cuối** mà không ai phải làm gì.

Có thể mở thêm một terminal trên máy B chạy `docker compose -p minigo-cn2 --env-file cn2.env logs -f relay` để cả lớp thấy relay báo lỗi liên tục rồi tự nối lại.

### Kịch bản 3: Tắt sink, sự kiện vẫn không mất

**Làm (trên máy A, trong thư mục `hq/`):**
```bash
docker compose -p minigo-hq --env-file hq.env stop sink
```
Bán vài đơn ở cả hai chi nhánh. Rồi xem hàng chờ:
```bash
docker compose -p minigo-hq --env-file hq.env exec redpanda rpk group describe hq-snapshot
```
Cột `LAG` cho biết số sự kiện đang chờ sink đọc. Sau đó bật lại:
```bash
docker compose -p minigo-hq --env-file hq.env start sink
```

**Thấy:** Khi sink tắt, dashboard vẫn mở được nhưng số đứng yên, trong khi LAG tăng dần. Bật sink lên thì nó đọc bù hết, LAG về 0 và số khớp.

**Nói:** Chi nhánh gửi sự kiện mà không cần biết ai nhận, cũng không cần bên nhận đang chạy. Redpanda giữ sự kiện trong lúc chờ. Theo bảng phân loại ở mục 2.1.3 của Chương 2, đây là tách rời cả **về thời gian** lẫn **về tham chiếu**. Các dịch vụ là tiến trình độc lập, tắt một cái không kéo cái khác chết theo (**microservices**).

### Kịch bản 4: Đồng hồ hai máy không tin được

**Làm:** Trên máy B, tắt chế độ tự chỉnh giờ rồi chỉnh đồng hồ nhanh thêm 2 phút. Bán vài đơn.

**Thấy:** Trên dashboard, thẻ CN2 báo lệch giờ khoảng +120 giây. Các sự kiện của CN2 hiện độ trễ **âm**, tức là trung tâm "nhận được trước khi sự kiện xảy ra". Dù vậy, số tồn vẫn đúng.

**Nói:** Mỗi máy có đồng hồ riêng và chúng không bao giờ khớp hoàn toàn, nên không thể dựa vào giờ để biết cái gì xảy ra trước. Hệ thống sắp thứ tự bằng cặp `(branch_id, movement_id)`, một số tăng dần do chính chi nhánh cấp (xem `sink.py`).

**Nhớ bật lại tự chỉnh giờ sau khi demo xong.**

### Kịch bản 5: Phát lại toàn bộ sự kiện, số vẫn đúng

**Làm (máy A, thư mục `hq/`):**
```bash
docker compose -p minigo-hq --env-file hq.env stop sink
docker compose -p minigo-hq --env-file hq.env exec redpanda rpk group seek hq-snapshot --to start
docker compose -p minigo-hq --env-file hq.env start sink
```

**Thấy:** Sink đọc lại mọi sự kiện từ đầu. Dòng đầu dashboard, số "bỏ qua … bản trùng" tăng vọt, còn bảng tồn không đổi một con số nào.

**Nói:** Thao tác bán là **không idempotent**: gửi hai lần là trừ hai lần (mục 2.3.1 Chương 2). Hệ thống biến việc *áp sự kiện* ở trung tâm thành idempotent bằng khoá `(branch_id, movement_id)`, nên được phép gửi lại thoải mái. Nhờ vậy relay chỉ cần đảm bảo "không mất", không cần đảm bảo "không trùng", vốn khó hơn nhiều.

### Kịch bản 6 (tuỳ chọn): Tắt relay, outbox giữ hàng

```bash
docker compose -p minigo-cn2 --env-file cn2.env stop relay     # máy B
```

Bán vài đơn: POS báo số sự kiện chưa gửi tăng dần, dashboard không đổi. Chạy `start relay`: số tồn đọng về 0, dashboard khớp. Kịch bản này cho thấy việc bán và việc gửi là hai tiến trình tách rời, gián tiếp chứng minh vai trò của outbox.

---

## 7. Giải thích các quyết định thiết kế

### Tại sao phải có outbox? Gửi thẳng lên Kafka sau khi bán không được sao?

Thử viết kiểu "trừ tồn xong rồi gửi Kafka":

```
COMMIT trừ tồn        ← thành công
gửi Kafka             ← mạng đứt, hoặc tiến trình chết đúng lúc này
```

Tồn đã trừ nhưng sự kiện mất vĩnh viễn, và trung tâm sai số mãi mãi. Đảo ngược thứ tự cũng không cứu được: gửi trước rồi mới commit, nếu commit thất bại thì trung tâm lại nhận một lượt bán không có thật. Đây gọi là **bài toán ghi kép** (dual write).

Outbox giải bằng cách chỉ ghi vào **một nơi**: CSDL của chi nhánh, trong cùng transaction với việc trừ tồn. Việc gửi đi là chuyện sau, làm bao nhiêu lần cũng được. Xem hàm `record_movement()` trong `branch/app/main.py`.

### Tại sao relay là tiến trình riêng, không gộp vào api?

Để việc bán **không bao giờ** phải chờ mạng. Nếu api vừa bán vừa gửi, mỗi lần mạng chậm thì quầy cũng chậm theo. Tách ra thì mất mạng chỉ ảnh hưởng relay, còn quầy không biết gì.

### "At-least-once" và "idempotent" là gì, sao lại đi cặp với nhau?

Trong hệ phân tán, không có cách nào vừa rẻ vừa chắc chắn gửi **đúng một lần**. Tình huống không tránh được: relay gửi thành công, Redpanda đã nhận, nhưng relay chết trước khi kịp đánh dấu `sent_at`. Khởi động lại, nó gửi lần nữa.

Nên hệ chọn chiến lược: bên gửi đảm bảo **ít nhất một lần** (at-least-once, không bao giờ mất), bên nhận đảm bảo **áp nhiều lần cũng như một lần** (idempotent). Kết hợp lại cho ra hiệu quả "đúng một lần" mà không cần giao thức phức tạp.

Sink có hai lớp phòng thủ, xem `apply_event()` trong `hq/app/sink.py`:

- Lớp 1: `event_log` có khoá chính `(branch_id, movement_id)`. Sự kiện đã thấy thì `INSERT` không vào và bị bỏ qua.
- Lớp 2: khi cập nhật snapshot có điều kiện `WHERE last_movement < EXCLUDED.last_movement`, nên sự kiện cũ tới muộn không ghi đè được số mới.

Màn hình POS cũng áp dụng ý tưởng này ở chiều client → server: mỗi lần bấm sinh một `request_id`. Mạng chập chờn khiến trình duyệt gửi lại thì server trả kết quả cũ chứ không trừ lần hai.

### Tại sao Redpanda có hai cổng, 9092 và 19092?

Đây là lỗi mà hầu như ai dựng Kafka lần đầu cũng gặp.

Khi client kết nối, Kafka không chỉ nhận kết nối mà còn **trả về địa chỉ** client phải dùng cho các lần sau (advertised address). Nếu Redpanda tự giới thiệu là `redpanda:9092`, relay ở máy B sẽ đi tìm máy tên `redpanda` và không thấy, vì tên đó chỉ tồn tại bên trong mạng Docker của máy A.

Vì vậy Redpanda mở hai cửa, mỗi cửa tự giới thiệu một địa chỉ khác nhau:

| Cửa | Ai dùng | Tự giới thiệu là |
|---|---|---|
| internal 9092 | sink, console (cùng máy A, cùng mạng Docker) | `redpanda:9092` |
| external 19092 | relay ở mọi chi nhánh | `<IP máy A>:19092` |

Xem dòng `--advertise-kafka-addr` trong `hq/docker-compose.yml`.

### Tại sao tồn ban đầu cũng đi qua outbox?

Lần chạy đầu, mỗi chi nhánh tạo 20 dòng tồn và ghi luôn 20 biến động loại `INIT` vào outbox. Trung tâm nhận số ban đầu qua đúng con đường của mọi lượt bán, không cần cơ chế đồng bộ riêng. Chỉ có một đường dữ liệu thì ít chỗ sai hơn.

### Heartbeat và "lệch giờ đo được"

Mỗi 5 giây, chi nhánh gửi lên giờ của máy nó. Trung tâm trừ đi giờ của chính nó lúc nhận. Con số này gồm cả hai thành phần: độ lệch đồng hồ thật và thời gian gói tin đi trên mạng. Không tách riêng được hai phần nếu không dùng giao thức như NTP hay Cristian (sẽ học ở chương Đồng bộ hoá). Đây cũng là một ý hay để nói khi bảo vệ.

Quá 15 giây không có heartbeat thì trung tâm coi node đó mất liên lạc. Lưu ý: trung tâm không thể phân biệt "node chết" với "mạng tới node chậm". Đó chính là lý do phát hiện lỗi trong hệ phân tán khó.

---

## 8. Đối chiếu với Chương 2 (Kiến trúc)

| Khái niệm trong chương | Chỗ thể hiện trong demo |
|---|---|
| 2.1.1 Kiến trúc phân tầng | POS (giao diện) → api_cn (xử lý) → Postgres (dữ liệu) |
| 2.1.2 Microservices | api, relay, sink là các tiến trình độc lập, tắt riêng từng cái được (kịch bản 3, 6) |
| 2.1.2 RESTful | `GET /api/inventory`, `POST /api/sale`: tài nguyên có URI, server không giữ phiên |
| 2.1.3 Publish–subscribe, topic-based | Relay phát vào topic `inventory.movement`, sink đăng ký topic đó |
| 2.1.3 Tách rời thời gian và tham chiếu | Kịch bản 3: sink tắt, sự kiện vẫn chờ; chi nhánh không biết sink là ai |
| 2.2.1 Message broker | Redpanda: thêm bên nhận mới không phải sửa chi nhánh (N kết nối thay vì N²) |
| 2.3.1 Idempotent vs không idempotent | Kịch bản 5 và cơ chế `request_id` |
| 2.3.2 Kiến trúc nhiều tầng vật lý, thin client | Trình duyệt chỉ hiển thị, mọi xử lý ở server |
| 2.5.2 Edge–cloud | Chi nhánh xử lý tại chỗ và tự trị khi mất mạng (edge), trung tâm tổng hợp (cloud) |

---

## 9. Lỗi hay gặp

| Triệu chứng | Nguyên nhân | Cách xử lý |
|---|---|---|
| `Chưa đặt HQ_HOST` khi chạy lệnh | Quên `--env-file` | Mọi lệnh `docker compose` đều phải kèm `-p ... --env-file ...` |
| Relay máy B báo `Message timed out` liên tục | Không tới được cổng 19092, hoặc `HQ_HOST` sai | Chạy lại các lệnh kiểm tra ở mục 5.3; xem firewall máy A |
| Relay kết nối được rồi lại lỗi, log nhắc tới `redpanda:9092` hoặc `localhost` | `HQ_HOST` trong `hq.env` sai nên Redpanda tự giới thiệu sai địa chỉ | Sửa `hq.env`, chạy lại `up -d` ở thư mục `hq/` |
| Dashboard không thấy chi nhánh nào | Heartbeat không tới cổng 8000 | Trên máy chi nhánh chạy `curl http://<IP_A>:8000/health` |
| Hai máy cùng Wi-Fi nhưng không ping được nhau | Wi-Fi cách ly thiết bị | Dùng hotspot điện thoại hoặc Tailscale |
| Đổi mạng xong mọi thứ ngừng đồng bộ | IP máy A đổi | Sửa `HQ_HOST` ở mọi file env, chạy lại `up -d` ở tất cả các nhóm |
| Sửa `schema.sql` hay `products.sql` mà không thấy tác dụng | Script khởi tạo chỉ chạy khi volume còn trống | Xoá dữ liệu bằng `down -v` (xem dưới) |
| Container `redpanda` restart liên tục | Máy thiếu RAM | Tắt `console`: `docker compose -p minigo-hq --env-file hq.env stop console` |

**Làm lại từ đầu, xoá sạch dữ liệu:** chạy lệnh `down -v` cho **tất cả** các nhóm cùng lúc, vì trung tâm và chi nhánh phải bắt đầu lại đồng thời:

```bash
docker compose -p minigo-hq  --env-file hq.env  down -v    # trong hq/
docker compose -p minigo-cn1 --env-file cn1.env down -v    # trong branch/, máy A
docker compose -p minigo-cn2 --env-file cn2.env down -v    # trong branch/, máy B
```

Nếu chỉ xoá trung tâm mà giữ chi nhánh, trung tâm sẽ mất số tồn ban đầu, vì các sự kiện `INIT` đã được gửi từ trước.

---

## 10. Lệnh hay dùng

```bash
# Xem log trực tiếp
docker compose -p minigo-cn2 --env-file cn2.env logs -f relay
docker compose -p minigo-hq  --env-file hq.env  logs -f sink

# Vào thẳng CSDL một node để cho thầy xem nó chỉ chứa dữ liệu của chính nó
docker compose -p minigo-cn2 --env-file cn2.env exec db psql -U app -d kho \
  -c "SELECT branch_id, count(*) FROM inventory GROUP BY 1;"

# Xem các sự kiện đang nằm chờ trong outbox
docker compose -p minigo-cn2 --env-file cn2.env exec db psql -U app -d kho \
  -c "SELECT event_id, payload->>'move_type', created_at FROM outbox WHERE sent_at IS NULL;"

# Xem topic trên Redpanda
docker compose -p minigo-hq --env-file hq.env exec redpanda rpk topic describe inventory.movement

# Gọi API bằng tay (thay cho bấm trên POS)
curl -X POST localhost:8001/api/sale -H "Content-Type: application/json" \
  -d '{"product_id": 3, "qty": 2}'
```

Tài liệu API tự sinh của FastAPI có ở http://localhost:8001/docs (chi nhánh) và http://localhost:8000/docs (trung tâm), bấm thử được ngay trên trình duyệt.

---

## 11. Thêm chi nhánh 3

Chạy trên máy thứ ba (hoặc trên máy A):

```bash
docker compose -p minigo-cn3 --env-file cn3.env up -d --build
```

Không phải sửa một dòng nào ở trung tâm hay các chi nhánh khác: dashboard tự hiện thêm cột CN3. Đó là **khả năng mở rộng** mà broker mang lại, một câu nên nói khi bảo vệ.

---

## 12. Nối sang đề tài kho (môn Ứng dụng phát triển phân tán)

Toàn bộ phần này dùng lại được: lược đồ `inventory` / `stock_movement` / `outbox`, logic trừ tồn chống âm, sink chống trùng, `inventory_snapshot`, dashboard. Khi làm đề tài kho, bổ sung thêm:

- Thay `relay.py` bằng Debezium đọc WAL (bảng outbox giữ nguyên, bỏ cột `sent_at`).
- Thay `products.sql` nạp tay bằng logical replication từ trung tâm xuống.
- Thêm `postgres_fdw` và view `global_inventory` cho đường truy vấn nóng.
- Thêm vòng đối chiếu định kỳ 15 phút.
- Thêm 2PC cho điều chuyển hàng.

---

## Đã kiểm thử những gì

Đã chạy thật với PostgreSQL 16 và các thư viện Python đúng phiên bản trong `requirements.txt`: bán, nhập, xung đột version (409), hết hàng (422), gửi lại cùng `request_id`, heartbeat, relay khi không tới được Redpanda (outbox giữ nguyên, không mất sự kiện), sink nhận trùng và nhận lệch thứ tự, snapshot khớp 100% với node, và hai màn hình giao diện.

Chưa chạy được trong môi trường kiểm thử: bản thân Docker Compose và Redpanda. Nên lỗi nếu có sẽ nằm ở phần cấu hình container và mạng, vì vậy hãy làm bước 4 (một máy) cho chạy xong trước khi sang bước 5.
