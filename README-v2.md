# MiniGo demo v2: hệ thống kho phân tán trên 2–3 máy thật

Demo cho môn Các hệ thống phân tán. Một chuỗi cửa hàng tiện lợi có nhiều chi nhánh, mỗi chi nhánh bán hàng trên CSDL của chính nó, trụ sở xem tồn kho toàn chuỗi.

Bản v2 được thiết kế để chứng minh bằng mắt các tính chất sau:

| Tính chất | Cơ chế trong hệ thống | Kịch bản |
|---|---|---|
| Trong suốt vị trí (location transparency) | Nginx là cổng vào duy nhất, chia yêu cầu cho các bản sao | K2 |
| Chịu lỗi, chuyển đổi khi lỗi (fault tolerance, failover) | Mỗi máy có một bản sao trung tâm; nginx bỏ qua bản sao chết | K3 |
| Tự phục hồi (self-healing) | Outbox giữ sự kiện, Redpanda giữ vị trí đọc, nginx tự thử lại | K4 |
| Đồng bộ dữ liệu (data consistency) | Sự kiện đi qua Redpanda tới mọi bản sao; so bằng dấu vân tay | K1, K4 |
| Chịu được độ trễ mạng | Bán tại chỗ, đồng bộ bất đồng bộ; đo RTT trực tiếp | K5 |

Mọi máy được nối với nhau bằng **mạng overlay** (Tailscale hoặc ZeroTier), nên chạy được cả khi mỗi máy ở một nơi.

---

## 1. Kiến trúc

```
                           Người dùng chỉ biết MỘT địa chỉ: http://<IP máy A>/
                                              │
 ┌────────────────────────── MÁY A ───────────┼──────────────────────────────┐
 │                                            ▼                              │
 │   ┌──────────┐  sự kiện   ┌───────────────────────┐                       │
 │   │ redpanda │◀────────── │ nginx (cổng vào duy   │── chia tải ──┐        │
 │   └────┬─────┘            │ nhất, chia tải)       │              │        │
 │        │                  └──────────┬────────────┘              │        │
 │        │ đọc                         ▼                           │        │
 │        ├──────────▶ sink A ──▶ replica_db A ◀── replica_api A    │        │
 │        │                                        (dashboard)      │        │
 │        │          relay ◀── branch_db CN1 ◀── branch_api CN1     │        │
 │        │ ▲                                    (POS Cầu Giấy)     │        │
 └────────┼─┼───────────────────────────────────────────────────────┼────────┘
          │ │ sự kiện của CN1                                        │
     ═════╪═╪════════════ mạng overlay (Tailscale / ZeroTier) ═══════╪═══════
          │                                                          │
 ┌────────┼──────────────────────── MÁY B ───────────────────────────┼────────┐
 │        │ đọc                                                      ▼        │
 │        └──────────▶ sink B ──▶ replica_db B ◀── replica_api B (dashboard)  │
 │                                                                            │
 │   gửi sự kiện lên redpanda máy A ◀── relay ◀── branch_db CN2 ◀── branch_api│
 │                                                                  CN2 (POS) │
 └────────────────────────────────────────────────────────────────────────────┘
```

Mọi máy chạy **giống hệt nhau**: một chi nhánh (3 container) và một bản sao trung tâm (3 container). Riêng máy A chạy thêm nhóm **core** gồm Redpanda, Redpanda Console và nginx.

| | Máy A | Máy B | Máy C (tuỳ chọn) |
|---|---|---|---|
| Chi nhánh | CN1 Cầu Giấy | CN2 Hà Đông | CN3 Đà Nẵng |
| Bản sao trung tâm | Bản sao A | Bản sao B | Bản sao C |
| Core | redpanda, console, nginx | — | — |
| File env | `env/may-a.env` | `env/may-b.env` | `env/may-c.env` |

**Tại sao mỗi máy một bản sao trung tâm?** Nếu chỉ có một dashboard ở máy A, thì "chịu lỗi" chỉ là lời nói. Có nhiều bản sao, mỗi bản tự dựng bảng tồn toàn chuỗi từ cùng một luồng sự kiện, thì nginx có chỗ để chuyển sang khi một máy chết, và ta có thứ để so xem dữ liệu giữa các máy có thật sự khớp không.

### Một lượt bán đi qua những đâu

1. Thu ngân bấm **Bán 1** ở POS máy B.
2. `branch_api` mở **một transaction** trên CSDL của CN2: trừ tồn, ghi sổ cái `stock_movement`, ghi `outbox`. Commit. Xong trong vài mili giây, chưa có gì đi qua mạng.
3. `relay` ở máy B đọc outbox, gửi sự kiện qua mạng overlay lên Redpanda ở máy A, chờ xác nhận rồi mới đánh dấu đã gửi.
4. `sink A` và `sink B` **mỗi cái đọc riêng** toàn bộ luồng sự kiện (hai consumer group khác nhau), mỗi cái cập nhật bảng tổng hợp của bản sao mình.
5. Dashboard, mở qua nginx, lần lượt được bản sao A và bản sao B trả lời. Cả hai hiện cùng một con số.

---

## 2. Bước 1: nối các máy bằng mạng overlay

Mạng overlay là một mạng ảo dựng **trên** mạng thật. Mỗi máy nhận thêm một IP riêng (ví dụ `100.x.x.x`), và các máy gọi nhau bằng IP đó như đang cắm chung một switch, dù thực tế mỗi máy ở một nhà. Đây cũng chính là khái niệm *Overlay Network* ở slide "Xoá bỏ cấu trúc tập trung".

Chọn **một** trong hai công cụ. **Nhóm nên dùng Tailscale** vì cài nhanh hơn.

### Cách 1: Tailscale (khuyên dùng)

1. Tải và cài tại https://tailscale.com/download trên **mọi máy**.
2. Đăng nhập **cùng một tài khoản** (Google, Microsoft hay GitHub đều được) trên mọi máy.
3. Xem IP overlay của từng máy: bấm biểu tượng Tailscale trên thanh tác vụ, hoặc chạy `tailscale ip -4`. IP có dạng `100.x.y.z`.

### Cách 2: ZeroTier

1. Tạo tài khoản ở https://my.zerotier.com, bấm **Create A Network**, chép **Network ID** (16 ký tự).
2. Cài ZeroTier One trên mọi máy (https://www.zerotier.com/download), rồi Join network bằng Network ID đó.
3. Trở lại trang quản lý, tick ô **Auth** cho từng máy mới xin vào. Máy nào chưa được tick thì chưa vào mạng được.
4. Cột **Managed IPs** trên trang đó là IP overlay của từng máy.

### Kiểm tra hai máy thấy nhau

Từ máy B: `ping <IP overlay máy A>`. Có trả lời thì mạng overlay đã thông.

### Mở cổng firewall

| Máy | Cổng cần mở | Ai gọi vào |
|---|---|---|
| A | 80 (nginx), 8000, 19092 (Redpanda) | trình duyệt, chi nhánh các máy khác |
| B, C | 8000 (bản sao), 8001 (POS) | nginx ở máy A, heartbeat từ chi nhánh khác |

Trên Windows, mở PowerShell bằng quyền Administrator:

```powershell
# Máy A
New-NetFirewallRule -DisplayName "MiniGo" -Direction Inbound -Protocol TCP -LocalPort 80,8000,19092 -Action Allow
# Máy B, C
New-NetFirewallRule -DisplayName "MiniGo" -Direction Inbound -Protocol TCP -LocalPort 8000,8001 -Action Allow
```

Trên Linux có ufw: `sudo ufw allow 80,8000,8001,19092/tcp`. macOS thường tự hỏi, bấm Allow.

---

## 3. Bước 2: điền file env

Mỗi máy có một file trong thư mục `env/`. Mở **cả hai** file `may-a.env` và `may-b.env`, thay các IP mẫu `100.64.0.1`, `100.64.0.2` bằng IP overlay thật. Chúng xuất hiện ở các dòng `IP_A`, `IP_B`, `KAFKA_BROKERS`, `REPLICA_URLS`.

Rồi **trên mỗi máy**, copy file của máy đó thành `.env` ở thư mục gốc dự án:

```bash
# Máy A — Windows: copy env\may-a.env .env
cp env/may-a.env .env
# Máy B — Windows: copy env\may-b.env .env
cp env/may-b.env .env
```

Sau bước này, trên mọi máy, mọi lệnh đều là `docker compose ...` ngắn gọn, không cần thêm tham số.

**Tại sao trong file env có chỗ ghi `replica_api:8000`, có chỗ ghi IP?** Container trên cùng một máy gọi nhau bằng tên service trong mạng Docker (nhanh, không phụ thuộc mạng ngoài). Container ở máy khác thì phải đi qua IP overlay.

---

## 4. Bước 3: chạy

**Máy A trước:**

```bash
docker compose up -d --build
docker compose ps
```

Phải thấy **9 container** (redpanda, console, nginx, và 6 container của chi nhánh và bản sao). Nếu không thấy redpanda, console, nginx, kiểm tra lại dòng `COMPOSE_PROFILES=core` trong `.env`, hoặc chạy `docker compose --profile core up -d`.

**Rồi máy B:** cùng lệnh `docker compose up -d --build`, phải thấy 6 container.

**Kiểm tra từng bước, trên máy A:**

| Mở | Phải thấy |
|---|---|
| http://localhost:8001 | POS CN1 Cầu Giấy |
| http://localhost:8000 | Dashboard của bản sao A |
| http://localhost/ | Dashboard qua nginx; dòng đầu ghi bản sao nào trả lời, có ô "Các bản sao trung tâm" |
| http://localhost/cn2/ | POS của CN2, **đang chạy trên máy B** |
| http://localhost:8080 | Redpanda Console, có topic `inventory.movement` |

Trên dashboard qua nginx, sau khoảng 10 giây phải có đủ hai thẻ CN1, CN2, và bảng bản sao có hai dòng A, B cùng ghi **Khớp từng ô**. Đến đây thì hệ thống đã thông hoàn toàn.

---

## 5. Công cụ giả lập độ trễ mạng

Mạng overlay giữa hai laptop cạnh nhau thường chỉ trễ vài mili giây, trong khi chi nhánh Đà Nẵng nối về Hà Nội thật sẽ trễ hàng chục đến hàng trăm mili giây. Các công cụ dưới đây làm mạng xấu đi **có kiểm soát** để thấy hệ thống phản ứng ra sao.

### Clumsy (Windows)

1. Tải bản `clumsy-0.3-win64` tại https://github.com/jagt/clumsy/releases, giải nén.
2. Chạy `clumsy.exe` **bằng quyền Administrator** (chuột phải, Run as administrator).
3. Ô **Filtering**, gõ bộ lọc để chỉ làm xấu đường tới máy A:
   ```
   ip.DstAddr == 100.64.0.1 or ip.SrcAddr == 100.64.0.1
   ```
   (thay bằng IP overlay thật của máy A)
4. Tick **Lag**, điền `300` ms. Muốn thêm mất gói thì tick **Drop**, điền `20` (%).
5. Bấm **Start**. Bấm **Stop** để trả mạng về bình thường.

Lưu ý: bộ lọc trên áp dụng cả hai chiều, nên RTT đo được sẽ tăng khoảng 2 × 300 = 600 ms.

### tc netem (Linux)

Chạy trên máy chi nhánh, áp lên card mạng overlay (`tailscale0` với Tailscale, `zt...` với ZeroTier; xem bằng `ip link`):

```bash
sudo tc qdisc add dev tailscale0 root netem delay 300ms             # trễ 300 ms
sudo tc qdisc change dev tailscale0 root netem delay 300ms loss 20% # thêm mất 20% gói
sudo tc qdisc del dev tailscale0 root                               # trả về bình thường
```

Vì chỉ áp lên card overlay, mạng Internet bình thường của máy không bị ảnh hưởng.

### Phương án dự phòng: giả lập ngay trong container

Nếu Clumsy hay tc trên máy thật không tác động tới traffic của Docker (kiểm tra bằng cách nhìn chip RTT trên POS, xem K5), dùng script có sẵn trong image chi nhánh. Nó chỉ làm trễ gói tin đi tới **một IP**, nên kết nối tới CSDL cục bộ vẫn nhanh:

```bash
# Trên máy B: làm trễ đường tới máy A, cho cả relay (sự kiện) và branch_api (heartbeat)
docker compose exec relay      sh tre.sh on 300 100.64.0.1
docker compose exec branch_api sh tre.sh on 300 100.64.0.1
# thêm mất 20% gói:  ... sh tre.sh on 300 100.64.0.1 20
# bỏ:                ... sh tre.sh off
```

---

## 6. Kịch bản demo

Bố trí màn hình khi thuyết trình:
- **Máy A** chiếu lên: dashboard qua nginx `http://localhost/`.
- **Máy B**: POS `http://localhost:8001` (đây là máy sẽ bị rút mạng).
- Nếu được, mở thêm tab `http://localhost:8000` trên máy B, tức dashboard của riêng bản sao B, dùng cho K3.

Bảng tóm tắt: **kịch bản nào chứng minh tính chất gì, nhìn ở đâu, thấy gì**:

| # | Tính chất | Làm gì | Nhìn ở đâu | Thấy gì |
|---|---|---|---|---|
| K1 | Đồng bộ dữ liệu | Bán ở POS máy B | Dashboard máy A | Ô CN2 nháy vàng, giảm số trong 1–2 giây; bảng bản sao A và B cùng dấu vân tay, "Khớp từng ô" |
| K2 | Trong suốt vị trí | Mở `http://<IP máy A>/` và `/cn2/` | Dòng "do bản sao máy … trả lời"; `curl -I` | Vệt `A B A B`: người dùng gõ một địa chỉ nhưng được hai máy phục vụ; `/cn2/` mở POS của máy B qua IP máy A |
| K3 | Chịu lỗi, failover | Rút mạng máy B | Dashboard máy A; POS máy B | Dashboard vẫn chạy, vệt chỉ còn `A A A`; bản sao B "Không liên lạc được"; thẻ CN2 tô đỏ, số cũ; POS máy B vẫn bán, dải đỏ đếm sự kiện chờ |
| K4 | Tự phục hồi | Cắm mạng lại, không làm gì khác | Bảng bản sao; thẻ CN2; vệt served-by | B "Đang đuổi theo, thiếu N sự kiện" rồi "Khớp từng ô"; CN2 hết đỏ, sự kiện "Đến muộn" hiện ra; vệt có lại `B` |
| K5 | Độ trễ mạng | Bật Clumsy/tc trễ 300 ms trên máy B | Chip RTT trên POS máy B; thẻ CN2 trên dashboard | RTT từ vài ms lên hàng trăm ms, sự kiện trễ theo; nhưng POS vẫn báo "xử lý tại chỗ trong ~5 ms" |
| K6 | Chống trùng (phụ) | Phát lại toàn bộ sự kiện | Dòng đầu dashboard | Số bản trùng bỏ qua tăng vọt, bảng tồn không đổi |

Chi tiết từng kịch bản:

### K1. Đồng bộ dữ liệu giữa các máy

**Làm:** Bấm **Bán 1** vài lần trên POS máy B.

**Thấy:** Trên dashboard máy A, ô CN2 nháy vàng và giảm số sau 1–2 giây, sự kiện hiện ở cột bên phải kèm độ trễ. Ở ô **Các bản sao trung tâm**, hai dòng A và B có **cùng dấu vân tay** (mã băm của toàn bộ bảng tồn) và cùng ghi *Khớp từng ô*.

**Nói:** Dữ liệu được đồng bộ tự động giữa các máy bằng luồng sự kiện: chi nhánh phát, mỗi bản sao tự đọc và áp. Dấu vân tay giống nhau chứng minh hai máy giữ **đúng cùng một số liệu đến từng ô**, không chỉ "trông giống".

**Nói rõ mức nhất quán:** Đây là **nhất quán cuối** (eventual consistency), không phải nhất quán mạnh. "Thời gian thực" ở đây nghĩa là trễ 1–2 giây, và con số trễ đó hiện ngay trên màn hình. Nếu thầy hỏi vì sao không làm nhất quán mạnh: vì muốn vậy thì mỗi lượt bán phải chờ mọi máy xác nhận, mất mạng là ngừng bán. Đó là đánh đổi CAP mà hệ chọn.

### K2. Trong suốt vị trí qua nginx

**Làm:**
1. Mở `http://<IP máy A>/` (hoặc `http://localhost/` ngay trên máy A).
2. Chạy vài lần: `curl -I http://localhost/api/stats`
3. Mở `http://localhost/cn2/`.

**Thấy:**
- Dòng đầu dashboard ghi "Lần làm mới này do bản sao máy **A** trả lời", và vệt nhỏ bên cạnh xen kẽ `A B A B`: nginx chia lần lượt (round-robin).
- `curl -I` in ra hai dòng `X-Served-By: replica-A` và `X-Upstream: ...`, đổi qua lại giữa các lần chạy.
- `/cn2/` mở màn hình POS của CN2, dù CN2 chạy trên máy B.

**Nói:** Người dùng chỉ biết **một địa chỉ**. Họ không biết, và không cần biết, phía sau có mấy máy, máy nào đang trả lời, CN2 nằm ở đâu. Đó là tính trong suốt vị trí. Nginx ở đây vừa là **bộ cân bằng tải** vừa là cổng vào duy nhất.

### K3. Chịu lỗi và chuyển đổi khi lỗi: rút mạng máy B

**Làm:** Tắt Wi-Fi (hoặc rút dây mạng) máy B. Trên POS máy B, bấm **Bán 20 đơn ngẫu nhiên**. Chờ khoảng 20 giây.

**Thấy trên dashboard máy A (qua nginx):**
- Dashboard **vẫn chạy bình thường**. Vệt served-by chỉ còn `A A A`: nginx phát hiện bản sao B không trả lời và tự chuyển hết sang A. Thỉnh thoảng một lần làm mới chậm khoảng 1 giây, vì nginx chờ B 1 giây rồi mới bỏ cuộc và thử lại (xem `proxy_connect_timeout` trong `core/nginx/default.conf.template`).
- Ô bản sao: dòng B ghi **Không liên lạc được**.
- Sau 15 giây, thẻ CN2 tô sọc đỏ "Mất liên lạc … giây", cột CN2 chuyển xám nghiêng kèm nhãn "số cũ". CN1 vẫn chạy bình thường.
- Mở `http://localhost/cn2/`: trang báo rõ "Không liên lạc được với chi nhánh này" thay vì treo.

**Thấy trên máy B:**
- POS **vẫn bán được**. Dải trạng thái chuyển đỏ "Chưa gửi được lên trung tâm từ … giây", số sự kiện chờ trong outbox tăng dần. Chip "Bản sao máy A: mất liên lạc".
- Tab `localhost:8000` (bản sao B) vẫn mở được nhưng số đứng yên. Điều thú vị là **bản sao B thấy CN2 còn sống còn CN1 mất liên lạc**, ngược hẳn với bản sao A.

**Nói:**
- Lỗi cục bộ: một máy chết, phần còn lại vẫn chạy, và người dùng qua nginx gần như không nhận ra.
- Mỗi bên mạng bị chia cắt vẫn phục vụ được, nhưng với số liệu cũ: **ưu tiên sẵn sàng hơn nhất quán**.
- Hai bản sao có hai "góc nhìn" khác nhau về việc ai còn sống. Trong hệ phân tán **không có trạng thái toàn cục** mà mọi máy cùng thấy, và một máy không phân biệt được "máy kia chết" với "đường mạng tới máy kia bị đứt".

### K4. Tự phục hồi: cắm mạng lại

**Làm:** Bật Wi-Fi máy B. **Không bấm gì thêm.**

**Thấy (trong khoảng 10–20 giây):**
1. Relay máy B gửi bù toàn bộ sự kiện tồn đọng; dải đỏ trên POS biến mất.
2. Dashboard máy A: các sự kiện của CN2 hiện ra, đánh dấu **Đến muộn** kèm độ trễ; thẻ CN2 hết đỏ.
3. Ô bản sao: dòng B hiện **Đang đuổi theo, thiếu N sự kiện**, N giảm dần, rồi chuyển sang **Khớp từng ô**, cùng dấu vân tay với A.
4. Vệt served-by có lại chữ `B`: nginx tự đưa bản sao B trở lại sau tối đa 10 giây (`fail_timeout=10s`).

**Nói:** Ba cơ chế tự phục hồi chạy cùng lúc mà không ai can thiệp:
- **Outbox** giữ sự kiện của chi nhánh, relay gửi tiếp từ đúng chỗ dừng.
- **Redpanda** nhớ vị trí đã đọc của từng bản sao (offset của consumer group), nên sink B đọc tiếp đúng phần còn thiếu.
- **Nginx** định kỳ thử lại bản sao đã bị gạch tên.

**Biến thể nếu còn thời gian:** chỉ tắt tiến trình, không rút mạng.

```bash
docker compose stop sink     # trên máy B
# bán vài đơn ở cả hai máy, nhìn dòng B "Đang đuổi theo" tăng dần
docker compose start sink
```

### K5. Độ trễ mạng

**Làm:** Trên máy B, bật Clumsy (hoặc tc) với trễ 300 ms tới máy A (mục 5). Bấm bán vài lần.

**Thấy:**
- Trên POS máy B: chip **Bản sao máy A** tăng từ vài chục ms lên khoảng 300–600 ms, còn chip **Bản sao máy B** vẫn thấp (cùng máy, không qua mạng).
- Trên dashboard: thẻ CN2 có **Độ trễ vòng (RTT)** tăng tương ứng; sự kiện của CN2 có độ trễ lớn hơn hẳn CN1.
- Nhưng dòng thông báo trên POS vẫn ghi **"Xử lý tại chỗ trong ~5 ms"**. Khách không phải chờ thêm chút nào.

RTT đo được gồm cả thời gian bản sao xử lý heartbeat (ghi vào CSDL), nên khi chưa bật giả lập, con số thường khoảng 5–40 ms chứ không phải 0.

**Nói:** Đặt hai con số cạnh nhau để so sánh. Nếu hệ thống tập trung, mỗi lượt bán phải đi về trung tâm ít nhất một vòng, tức ít nhất 300–600 ms, và thực tế nhiều hơn vì một transaction cần vài lượt hỏi đáp với CSDL. Kiến trúc này đẩy độ trễ ra khỏi đường bán hàng, chỉ để nó ảnh hưởng tới việc đồng bộ, đúng tinh thần Edge Computing: xử lý ở gần người dùng.

**Thêm mất gói:** bật Drop 20% (hoặc `sh tre.sh on 300 <IP_A> 20`). Sự kiện đến chậm hơn, heartbeat chập chờn, nhưng sau khi tắt Clumsy, dấu vân tay hai bản sao vẫn khớp: **không mất sự kiện nào**, vì relay chỉ đánh dấu đã gửi khi Redpanda xác nhận.

Nhớ **Stop** Clumsy (hoặc `tre.sh off`) sau khi xong.

### K6 (phụ). Phát lại sự kiện, số vẫn đúng

Trên máy A:

```bash
docker compose stop sink
docker compose exec redpanda rpk group seek replica-A --to start
docker compose start sink
```

Dòng đầu dashboard (khi bản sao A trả lời): số "bỏ qua … bản trùng" tăng vọt, bảng tồn không đổi, dấu vân tay A vẫn khớp B. Áp một sự kiện nhiều lần cho kết quả như áp một lần (idempotent), nên hệ thống được phép gửi lại thoải mái.

---

## 7. Những giới hạn nên nói thẳng khi bảo vệ

Nói trước những điểm này cho thấy nhóm hiểu hệ thống của mình, tốt hơn nhiều so với để thầy tự hỏi ra.

- **Máy A là điểm chết duy nhất cho phần đồng bộ và cổng vào.** Nginx và Redpanda chỉ chạy ở máy A. Rút mạng máy A thì: quầy ở mọi máy **vẫn bán**, dashboard của bản sao B vẫn mở được trực tiếp ở `B:8000` (số cũ), nhưng địa chỉ nginx không vào được và việc đồng bộ tạm dừng. Cắm lại thì tự phục hồi như K4. Muốn bỏ điểm chết này cần chạy Redpanda thành cụm 3 máy (mất một máy vẫn còn đa số 2/3) và thêm một địa chỉ IP ảo chuyển giữa hai nginx (keepalived). Việc đó nằm ngoài phạm vi demo. **Vì vậy khi demo, rút mạng máy B.**
- **Dữ liệu của mỗi chi nhánh chỉ có một bản chính**, ở chính máy chi nhánh. Bản sao trung tâm chỉ là bản tổng hợp để đọc. Máy B hỏng ổ cứng thì mất các lượt bán chưa kịp gửi đi.
- **Nhất quán cuối, không phải nhất quán mạnh.** Trong lúc bản sao B còn đang đuổi theo, hai lần làm mới liên tiếp (một lần A trả lời, một lần B) có thể thấy **số khác nhau**, thậm chí số "lùi lại". Nếu thầy để ý thấy thì đó là một câu hỏi rất hay: hệ thống không đảm bảo *đọc đơn điệu* (monotonic reads), một mô hình nhất quán sẽ học ở chương Nhất quán và nhân bản.
- **Nginx chỉ tự thử lại yêu cầu idempotent (GET).** Lệnh bán (POST) gửi qua nginx mà thất bại thì không được thử lại tự động, vì gửi hai lần có thể thành hai lượt bán. POS tự bảo vệ bằng `request_id`.

---

## 8. Đối chiếu với Chương 2

| Slide | Chỗ thể hiện trong demo |
|---|---|
| Kiến trúc phần mềm và kiến trúc hệ thống | Cùng một bộ code và một file compose; đặt lên 1, 2 hay 3 máy chỉ khác file `.env` |
| Layered, RESTful | POS → branch_api → Postgres; các tài nguyên `/api/inventory`, `/api/sale` |
| Microservices, publish–subscribe | api, relay, sink, nginx là các tiến trình độc lập; relay phát vào topic, các sink đăng ký |
| Middleware: Broker | Redpanda: thêm máy C không phải sửa máy nào khác |
| Middleware: Interceptor | Nginx chen vào giữa trình duyệt và bản sao, tự chọn bản sao và tự thử lại mà client không hay biết |
| Thin/Fat client, 3-tier | Trình duyệt là thin client; chi nhánh "béo" như fat client: xử lý tại chỗ, chạy offline tốt, đồng bộ khó |
| Overlay network | Tailscale / ZeroTier là một mạng phủ dựng trên Internet |
| Super-peer, BitTorrent tracker | Máy chủ điều phối của Tailscale giúp các máy tìm thấy nhau, rồi dữ liệu đi thẳng giữa các máy, giống vai trò tracker |
| Edge & Fog | Chi nhánh là edge: xử lý tại chỗ, độ trễ thấp (K5) |
| Phổ kiến trúc | Hệ nằm giữa phổ: phi tập trung ở phần bán hàng, tập trung ở phần điều phối (máy A) |

---

## 9. Lỗi hay gặp

| Triệu chứng | Nguyên nhân | Cách xử lý |
|---|---|---|
| `Chưa đặt ... trong .env` | Chưa copy file env thành `.env` | Mục 3 |
| Máy A không có redpanda, nginx | Profile core chưa bật | Kiểm tra `COMPOSE_PROFILES=core`, hoặc `docker compose --profile core up -d` |
| Relay máy B báo `Message timed out` | Không tới được `IP_A:19092` | `ping` IP máy A; kiểm tra firewall máy A; kiểm tra `KAFKA_BROKERS` |
| Relay nối được rồi lỗi, log nhắc `localhost` hay `redpanda` | `IP_A` trong `.env` máy A sai nên Redpanda tự giới thiệu sai địa chỉ | Sửa `.env` máy A, chạy lại `docker compose up -d` |
| Bảng bản sao dòng B luôn "Không liên lạc được" | Nginx không tới được `IP_B:8000` | Mở firewall máy B cổng 8000; từ máy A: `curl http://<IP_B>:8000/health` |
| Không có ô "Các bản sao trung tâm" | Đang mở dashboard trực tiếp ở cổng 8000, không qua nginx | Mở `http://localhost/` (cổng 80) |
| Cổng 80 bị chiếm (Windows hay gặp) | IIS hoặc ứng dụng khác | Thêm `NGINX_PORT=8088` vào `.env`, mở `http://localhost:8088/` |
| Thêm máy C mà nginx lỗi khởi động | Bỏ `#` các dòng `[MÁY C]` nhưng chưa đặt `IP_C` | Thêm `IP_C=...` vào `.env` máy A |
| Sửa `schema.sql` không thấy tác dụng | Script khởi tạo chỉ chạy khi volume trống | `docker compose down -v` trên **mọi máy** rồi chạy lại |

**Làm lại từ đầu:** chạy `docker compose down -v` trên **tất cả** các máy cùng lúc, rồi `up -d --build` lại, máy A trước.

---

## 10. Lệnh hay dùng

```bash
docker compose ps                         # container nào đang chạy
docker compose logs -f relay              # relay gửi được không
docker compose logs -f sink               # sink đang áp sự kiện nào
docker compose exec redpanda rpk group list                    # (máy A) các consumer group
docker compose exec redpanda rpk group describe replica-B      # (máy A) bản sao B còn thiếu bao nhiêu (cột LAG)
curl -I http://localhost/api/stats        # (máy A) bản sao nào trả lời
docker compose exec branch_db psql -U app -d kho -c "SELECT branch_id, count(*) FROM inventory GROUP BY 1;"
```

Tài liệu API tự sinh: `http://localhost:8001/docs` (chi nhánh), `http://localhost:8000/docs` (bản sao).

---

## 11. Đã kiểm thử những gì

Đã chạy thật với PostgreSQL 16, nginx và đúng các thư viện Python trong `requirements.txt`, mô phỏng 2 bản sao và 2 chi nhánh trên một máy:
- Heartbeat tới cả hai bản sao, có đo RTT.
- Bán qua nginx `/cn2/`, trả kèm thời gian xử lý.
- Nginx chia `A B A B`; giết bản sao B thì mọi yêu cầu chuyển sang A và vẫn trả 200.
- Chi nhánh chết thì `/cn2/` trả trang báo mất liên lạc.
- Hai bản sao lệch dấu vân tay, rồi khớp lại khi bản sao chậm đuổi kịp.
- Chống trùng, dải đỏ của POS khi outbox kẹt, và giao diện hai màn hình.

**Chưa chạy được** trong môi trường kiểm thử: Docker Compose, Redpanda, mạng overlay, Clumsy và lệnh `tc` (môi trường không có module netem). Nếu có lỗi thì nhiều khả năng ở cấu hình container và mạng. Nên dựng đủ trên hai máy **sớm**, ít nhất hai ngày trước hôm demo, và chạy đủ K1 đến K5 ít nhất hai lần.
