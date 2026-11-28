# Kịch bản demo

Dựng hệ thống trên 2–3 máy thật, rồi đi qua K1–K9 để chứng minh từng tính chất ở `spec.md` mục 2.
Nên dựng đủ trên hai máy **sớm**, ít nhất hai ngày trước hôm demo, và chạy đủ K1 đến K5 ít nhất hai lần.
Chỉ có một máy: mô phỏng 3 máy, xem mục 3, phần "Chạy trên một máy"; K1–K9 chạy như nhau.

## 1. Nối các máy bằng mạng overlay

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
| A, B, C | 80 (nginx, cổng vào ở mọi máy từ vòng 5), 8000 (bản sao), 8001 (POS), 19092, 33145 (Redpanda) | trình duyệt, nginx mọi máy, heartbeat, relay, sink và broker máy khác |

Trên Windows, mở PowerShell bằng quyền Administrator (mọi máy):

```powershell
New-NetFirewallRule -DisplayName "MiniGo" -Direction Inbound -Protocol TCP -LocalPort 80,8000,8001,19092,33145 -Action Allow
```

Trên Linux có ufw: `sudo ufw allow 80,8000,8001,19092,33145/tcp`. macOS thường tự hỏi, bấm Allow.

## 2. Điền file env

Mỗi máy có một file mẫu trong `infra/env/`. Mở **cả ba** file `infra/env/may-a.env`, `may-b.env`, `may-c.env`, thay các IP mẫu `100.64.0.1`, `100.64.0.2`, `100.64.0.3` bằng IP overlay thật. Chúng xuất hiện ở các dòng `BROKER_SEEDS`, `KAFKA_BROKERS`, `REPLICA_A/B/C`, `BRANCH_A/B/C`, `GATEWAYS`, `REPLICA_URLS`, `BROKER_HOST`, `BRANCH_URL`. Khối `BROKER_SEEDS`, `KAFKA_BROKERS`, `REPLICA_A/B/C`, `BRANCH_A/B/C`, `GATEWAYS` phải giống nhau ở mọi file; `BROKER_HOST` là IP overlay của **chính máy đó** (broker tự giới thiệu địa chỉ này cho máy khác); `BRANCH_URL` là `http://<IP overlay chính máy đó>:8001` (chi nhánh gửi kèm heartbeat để bản sao mọi máy đối soát khi mất broker).

`REPLICA_B`, `BRANCH_B`... là địa chỉ đầy đủ `host:port` mà nginx (chạy ở mọi máy) dùng để gọi bản sao và POS của từng máy: `100.64.0.2:8000` là bản sao máy B, `100.64.0.2:8001` là POS CN2 (cổng host). Cả máy của chính nginx cũng ghi bằng IP overlay (`REPLICA_A=100.64.0.1:8000`), vì cùng một khối chạy ở cả ba máy (giả định chưa kiểm: container gọi được IP overlay của chính máy mình, `docs/plan.md` mục 6). `GATEWAYS` là các địa chỉ trình duyệt dùng để mở cổng vào (`http://100.64.0.1,...`).

**Chỉ có 2 máy thật?** Cụm broker cần đủ mọi seed mới lập được, và Redpanda không nhận RF=2, nên với 2 máy chỉ máy A chạy broker (như trước vòng 2, broker vẫn là điểm chết; K7 cần 3 máy hoặc chế độ một máy). Sửa ở **cả hai** file `may-a.env`, `may-b.env`: `BROKER_SEEDS=<IP A>:33145`, `KAFKA_BROKERS=<IP A>:19092`; ở `may-b.env` thêm `#` trước `COMPOSE_PROFILES=broker`. `topic-init` tự lấy RF = số seed = 1. Phần còn lại vẫn chạy, nhưng dòng C trên bảng bản sao ghi "Không liên lạc được", `/cn3/` báo mất liên lạc, và thỉnh thoảng một request qua nginx chậm khoảng 1 giây (mỗi worker nginx tự thử lại máy C sau 10 giây). Muốn gọn: trong `infra/nginx/default.conf.template` thêm `#` trước dòng `server ${REPLICA_C}` và bỏ `"C"` ở `/lb/replicas.json`.

Rồi **trên mỗi máy**, copy file của máy đó thành `.env` ở gốc repo:

```bash
# Máy A — Windows: copy infra\env\may-a.env .env
cp infra/env/may-a.env .env
# Máy B — Windows: copy infra\env\may-b.env .env
cp infra/env/may-b.env .env
```

Sau bước này, trên mọi máy, mọi lệnh đều là `docker compose ...` ngắn gọn, không cần thêm tham số.

**Tại sao trong file env có chỗ ghi `replica_api:8000`, có chỗ ghi IP?** Container trên cùng một máy gọi nhau bằng tên service trong mạng Docker (nhanh, không phụ thuộc mạng ngoài). Container ở máy khác thì phải đi qua IP overlay.

**Lỗi từng gặp:** đặt `REPLICA_B` trỏ về máy A (hoặc cho cả `A=` lẫn `B=` trong `REPLICA_URLS` cùng một địa chỉ). Khi đó nginx "chia tải" giữa A và chính A, dòng B trên bảng bản sao là A tự so với mình, còn bản sao B thật không nhận heartbeat nào. `REPLICA_B` luôn là IP overlay của **máy B**.

## 3. Chạy

**Trên cả ba máy** (thứ tự nào cũng được):

```bash
make up        # hoặc: docker compose up -d --build
docker compose ps -a
```

Máy A phải thấy **9 container chạy** (redpanda, console, nginx, và 6 container của chi nhánh và bản sao) cộng `topic-init` đã `Exited (0)`; máy B, C mỗi máy **8 container** (thêm redpanda, nginx). Nếu thiếu redpanda, console, kiểm tra dòng `COMPOSE_PROFILES` trong `.env` (`core,broker` ở máy A, `broker` ở máy B, C); nginx chạy ở mọi máy, không phụ thuộc profile.

**Nâng từ bản trước vòng 5:** schema bản sao có thêm bảng `peer_view`, nên chạy `make reset` một lần trên **mọi** máy (một máy: `make local-reset`, lệnh này cũng dựng lại mạng `minigo-wan` có vùng IP động riêng). Dữ liệu demo bị xoá.

Cụm broker chỉ lập khi **đủ 3 broker** (mọi địa chỉ trong `BROKER_SEEDS`); trước đó relay, sink báo lỗi và tự thử lại, `docker compose logs topic-init` ghi "Chờ cụm broker". Kiểm tra: `docker compose exec redpanda rpk cluster health` phải có `Healthy: true`, `All nodes: [1 2 3]`.

**Đã chạy bản một broker (trước vòng 2)?** Dữ liệu broker cũ không nhập được vào cụm: chạy `make reset` trên **mọi** máy.

**Kiểm tra từng bước, trên máy A:**

| Mở | Phải thấy |
|---|---|
| http://localhost:8001 | POS CN1 Cầu Giấy |
| http://localhost:8000 | Dashboard của bản sao A |
| http://localhost/ | Dashboard qua nginx; dòng đầu ghi bản sao nào trả lời, có ô "Các bản sao trung tâm" |
| http://localhost/cn2/ | POS của CN2, **đang chạy trên máy B** |
| http://localhost:8080 | Redpanda Console, có topic `inventory.movement` |

Trên dashboard qua nginx, sau khoảng 10 giây phải có đủ hai thẻ CN1, CN2, và bảng bản sao có hai dòng A, B cùng ghi **Khớp từng ô**. Đến đây thì hệ thống đã thông hoàn toàn.

### Chạy trên một máy (3 node, không cần mạng overlay)

Mỗi "máy" là một compose project (`minigo-a`, `minigo-b`, `minigo-c`) chạy cùng `infra/compose.yml`, ghép thêm
`infra/compose.local.yml`, env ở `infra/env/local-<x>.env` (không cần `.env`). "Mạng overlay" là docker network
chung `minigo-wan`. "Rút mạng máy B" là gỡ mọi container của B khỏi `minigo-wan`: B vẫn chạy đủ bên trong (CSDL,
POS, bản sao, broker), chỉ mất liên lạc với node khác, đúng như rút dây mạng. RAM: 23 container (3 broker, mỗi broker `--memory=512M`) đo được khoảng 1,23 GB (19/11/2026); vòng 5 thêm 2 nginx (25 container).
Đã chạy bản một broker (vòng 1)? Chạy `make local-reset` một lần: volume broker cũ là cụm một node.
**Nâng từ bản trước vòng 5:** chạy `make local-reset` một lần (bảng mới `peer_view`; mạng `minigo-wan` tạo lại có
vùng IP động riêng). `make local-up` trên mạng cũ sẽ dừng và nhắc việc này.

```bash
make local-up        # tạo minigo-wan, dựng node C, B rồi A (25 container, cộng topic-init chạy một lần)
make cut N=b         # rút mạng node B
make heal N=b        # cắm lại, đúng IP và alias cũ
make local-down      # dừng 3 node, giữ dữ liệu
make local-reset     # xoá dữ liệu 3 node rồi dựng lại
make pause N=b S=branch_api    # "chậm": tạm dừng một container (unpause để chạy tiếp)
make kill N=a S=nginx          # "chết": giết một container (start để bật lại)
```

| Node | POS | Dashboard bản sao | Cổng vào (nginx) | Riêng node A |
|---|---|---|---|---|
| A | http://localhost:8001 (CN1) | http://localhost:8000 | http://localhost/ | Console http://localhost:8080 |
| B | http://localhost:8011 (CN2) | http://localhost:8010 | http://localhost:8012/ | |
| C | http://localhost:8021 (CN3) | http://localhost:8020 | http://localhost:8022/ | |

Ba cổng vào giống hệt nhau: `localhost:8012/cn2/` cũng là POS CN2, `localhost:8022/` cũng là dashboard toàn chuỗi.

K1–K9 ở mục 5 giữ nguyên, chỉ đổi thao tác:

| Kịch bản | Máy thật | Một máy |
|---|---|---|
| POS máy B, dashboard bản sao B | `localhost:8001`, `localhost:8000` trên máy B | `localhost:8011`, `localhost:8010` |
| K3 rút mạng máy B | Tắt Wi-Fi máy B | `make cut N=b` |
| K4 cắm lại | Bật Wi-Fi máy B | `make heal N=b` |
| K5 trễ 300 ms tới máy A | Clumsy, tc, hoặc `tre.sh on 300 <IP máy A>` | `docker exec minigo-b-branch_api-1 sh tre.sh on 300 replica-a` (chip RTT); thêm `docker exec minigo-b-relay-1 sh tre.sh on 300 redpanda-a` thì chỉ chậm phần sự kiện gửi tới broker 1. Bỏ: `... sh tre.sh off` |
| K6 phát lại | `docker compose stop sink` ... | `docker stop minigo-a-sink-1`, `docker exec minigo-a-redpanda-1 rpk group seek replica-A --to start`, `docker start minigo-a-sink-1` |
| K7a dừng 1/3 broker | `docker compose stop redpanda` trên một máy | `docker stop minigo-b-redpanda-1`; bật lại: `docker start minigo-b-redpanda-1` |
| K7b dừng 2/3 broker | `docker compose stop redpanda` trên máy B và C | `docker stop minigo-b-redpanda-1 minigo-c-redpanda-1`; bật lại: `docker start ...` |
| K7c rút mạng máy A | Tắt Wi-Fi máy A | `make cut N=a`, `make heal N=a` |
| K8 bản sao B lỡ sự kiện | `docker compose stop sink` (máy B), bán, `docker compose exec redpanda rpk group seek replica-B --to end`, `docker compose start sink` | `docker stop minigo-b-sink-1`, bán ở `localhost:8011`, `docker exec minigo-a-redpanda-1 rpk group seek replica-B --to end`, `docker start minigo-b-sink-1` |
| K9 dừng cả 3 broker | `docker compose stop redpanda` trên cả 3 máy | `docker stop minigo-a-redpanda-1 minigo-b-redpanda-1 minigo-c-redpanda-1`; bật lại: `docker start ...` |
| K13 mất cổng vào A | Rút mạng máy A, hoặc `docker compose stop nginx` trên máy A | `make kill N=a S=nginx` (chết) hoặc `make pause N=a S=nginx` (treo); bật lại `make start` / `make unpause`. **Không dùng `make cut N=a`**: cổng host không đi qua `minigo-wan`, trình duyệt cùng máy vẫn gọi được nginx A |
| K14 chi nhánh B chậm / chết | `docker compose pause branch_api` / `docker compose kill branch_api` trên máy B | `make pause N=b S=branch_api` / `make kill N=b S=branch_api`; biến thể: `docker exec minigo-b-branch_api-1 sh tre.sh on 0 replica-a 100` (mất 100% gói tới riêng bản sao A), bỏ: `... sh tre.sh off` |
| K15 chi nhánh B sập (ghi hộ) | `docker compose kill branch_api branch_db` trên máy B; bật lại: `docker compose start branch_db`, rồi `branch_api` | `make kill N=b S=branch_api`, `make kill N=b S=branch_db`; bật lại: `make start N=b S=branch_db`, chờ healthy, `make start N=b S=branch_api`. Biến thể REJECTED: trước đó `make kill N=b S=relay`; biến thể hai nơi cùng ghi: `make kill N=b S=nginx` rồi `make cut N=b` (xem K15) |
| Xem gossip, đối soát | `curl localhost:8000/api/digest` (trường `sync_peers`) | `curl localhost:8010/api/digest`; log: `docker logs minigo-b-replica_api-1 \| grep gossip` |
| Xem cụm broker | `docker compose exec redpanda rpk cluster health` | `docker exec minigo-a-redpanda-1 rpk cluster health`, `... rpk topic describe inventory.movement -p` |
| Xem container, log | `make ps`, `make logs S=relay` | `docker ps --filter name=minigo-b`, `docker logs -f minigo-b-relay-1` |

**Vì sao gọi nhau bằng `replica-b` mà không bằng `replica_api`?** Compose tự thêm tên service làm alias trên mọi
network, nên trên `minigo-wan` tên `replica_api` trỏ về cả ba node. Mỗi node có alias riêng (`branch-b`,
`replica-b`, `redpanda-a`), gắn trên cả mạng riêng của node lẫn `minigo-wan`: lúc B bị rút mạng, CN2 vẫn gửi
heartbeat được cho bản sao B.

**Vì sao `heal` phải nối lại đúng IP cũ?** Broker cần: kết nối RPC nó mở trước lúc rút mạng gắn với IP cũ, IP đổi
thì broker đó không gọi được broker khác nữa (thử ở vòng 2: K7a sau đó hỏng). `make cut` ghi IP và alias vào
`.cut-<x>` ở gốc repo, `make heal` đọc lại. Từ vòng 5, mọi container trên `minigo-wan` có **IP cố định**
(`WAN_IP_PREFIX`: node A `10.210.0.11`–`.18`, B `.21`–`.28`, C `.31`–`.38`), còn IP động chỉ cấp trong
`10.210.0.128/25`: không container nào lấy mất IP của container khác, nên dựng lại (`make local-up`) trong lúc một
node bị rút mạng, hay bật lại broker sau `heal`, không còn lỗi `Address already in use` (đo 27/11/2026: cut B, dựng
lại hẳn node A, C, heal B, dừng broker B, dựng lại node A, bật broker B: mọi container chạy, cụm `Healthy: true`).
Nginx thì phân giải tên động (`resolve`), không còn nhớ IP.

Giới hạn của bản mô phỏng:
- Cổng host của nginx không đi qua `minigo-wan`, nên `make cut N=a` không làm trình duyệt cùng máy mất cổng A (K13
  dùng `make kill`/`make pause` nginx A). Nginx A bị cut vẫn trả lời, chỉ thấy bản sao A và CN1.
- DNS của Docker Desktop mất ~8 giây mới báo "không có" tên của container đã dừng; relay, sink đặt
  `dns_opt: timeout:1, attempts:1` (`infra/compose.local.yml`) để không treo khi một broker tắt. Máy thật dùng IP.
- Đo ngày 19/11/2026 (cụm 3 broker): sau `make heal N=b`, outbox CN2 về 0 trong 5–9 giây; 3 bản sao khớp sau
  2–27 giây.

## 4. Giả lập độ trễ mạng

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

## 5. Kịch bản K1–K9, K11–K15

(K10 dành cho vòng 7.) Từ vòng 4 hai màn hình được làm lại theo thao tác nghiệp vụ. Dashboard trụ sở có thanh bên
(menu, bản sao đang trả lời, trạng thái đồng bộ tóm tắt) và bốn tab; tab đang mở nằm trong địa chỉ
(`http://localhost/#he-thong`) nên tải lại vẫn giữ. Hai tab đầu cho người quản lý, tab Hệ thống cho phần kỹ thuật.
POS là màn hình quầy dạng phiếu. Các kịch bản bên dưới viết từ trước vòng 4 gọi tên chỗ cũ:

| Chỗ cũ trong kịch bản | Từ vòng 4 nằm ở |
|---|---|
| POS: "Bán 1", "Nhập 10" | Chọn **Bán hàng** / **Nhập hàng**, thêm mặt hàng vào phiếu (bấm dòng, hoặc gõ mã rồi Enter như máy quét), chỉnh số lượng 1–1000, bấm **Thanh toán** / **Nhập kho**. Mỗi dòng phiếu một `request_id`: mất kết nối giữa chừng thì gửi lại không trừ hai lần |
| POS: "Bán 20 đơn ngẫu nhiên" | Mục **Công cụ demo** dưới phiếu |
| POS: dải trạng thái gửi, chip RTT, "Xử lý tại chỗ trong ~5 ms" | Dải ngay dưới tên chi nhánh; chip RTT góc phải đầu trang; câu "Xử lý tại chỗ trong … ms" hiện dưới nút Thanh toán |
| Dashboard "dòng đầu": bản sao nào trả lời, vệt `A B C` | Thanh bên, mục "Bản sao trả lời" |
| Dashboard: số đã áp / bản trùng, dòng "Đồng bộ", "Gossip lần cuối" | Tab **Hệ thống** (`#he-thong`), thẻ "Đồng bộ của bản sao đang trả lời"; tóm tắt ở thanh bên và ô "Đồng bộ về trụ sở" của tab Tổng quan |
| Dải vàng đọc đơn điệu (K11) | Đầu vùng chính, hiện ở mọi tab |
| Thẻ chi nhánh | Tab **Tổng quan** (`#tong-quan`), bảng "Chi nhánh" (Hoạt động / Còn sống, đồng bộ dừng / Mất liên lạc); chi tiết RTT, lệch giờ, gửi lên Redpanda ở bảng "Chi nhánh" của tab Hệ thống |
| Bảng tồn kho, chấm cam "đối soát" | Tab **Tồn kho** (`#ton-kho`), có ô tìm và lọc "Chỉ hàng dưới ngưỡng"; hàng dưới ngưỡng cũng tóm tắt ở "Cần đặt thêm hàng" của tab Tổng quan |
| Cột "Sự kiện vừa nhận", khung truy vết (K12) | Tab **Sự kiện** (`#su-kien`): bảng sự kiện bên trái (mỗi sự kiện một dòng), truy vết bên phải |
| Sơ đồ đồng bộ, ô / bảng "Các bản sao trung tâm" (dấu vân tay, cột Gossip) | Tab **Hệ thống**; mở thẳng một bản sao thì bảng bản sao báo "chỉ có khi mở qua nginx" |

Chấm màu cạnh tên tab ở thanh bên: Tổng quan đỏ khi có chi nhánh mất liên lạc, vàng khi đồng bộ dừng; Hệ thống đỏ khi
có bản sao không liên lạc được hoặc đồng bộ dừng, vàng khi dấu vân tay lệch hoặc còn tồn đọng.

Tab Hệ thống có **sơ đồ đồng bộ** (topology sống), vẽ luồng từ trái sang phải: cột trái
CN1–CN3, giữa ("Log chung") là khối Redpanda với ba chấm broker 1, 2, 3, cột phải bản sao A–C. Kênh 1: dòng của ba chi
nhánh **dồn vào** khối Redpanda rồi **tách ra** tới từng bản sao. Kênh 2: cung chấm (gossip) nối các bản sao ở mép
phải. Kênh 3: đối soát, nét đứt vàng đi vòng dưới cùng từ bản sao về chi nhánh, chỉ hiện khi đang đối soát. Đường bình
thường mảnh, xám nhạt; chỉ đường có vấn đề mới có màu: vàng tồn đọng, đỏ lỗi, xám nét đứt không rõ hoặc không chạy. Có
dữ liệu đi qua thì một chấm chạy dọc đường (màu chi nhánh trên đường relay, xanh trên đường tới bản sao). Hộp
chỉ ghi tên, chỉ thêm một dòng ngắn khi có chuyện ("chờ 3", "gửi lỗi", "mất liên lạc", "sink dừng", "không liên
lạc"); số liệu chi tiết nằm ở chú thích khi di chuột (chữ trong ngoặc kép ở bảng "Trên sơ đồ đồng bộ" bên dưới là
chú thích đó). Đây là hình trả lời câu hỏi "ReplicaA và ReplicaB trao đổi thông tin
bằng cơ chế gì" (`docs/plan.md` mục 3.2). Mở qua nginx thì sơ đồ ghép góc nhìn của mọi bản sao và chi nhánh; mở thẳng
một bản sao thì chỉ có góc nhìn của bản sao đó.

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
| K4 | Tự phục hồi | Cắm mạng lại, không làm gì khác | Bảng bản sao; thẻ CN2; vệt served-by | B "Đang đuổi theo, thiếu N sự kiện" rồi "Khớp từng ô"; CN2 hết đỏ, sự kiện đến muộn hiện ra (số vàng ở cột "Trễ"); vệt có lại `B` |
| K5 | Độ trễ mạng | Bật Clumsy/tc trễ 300 ms trên máy B | Chip RTT trên POS máy B; thẻ CN2 trên dashboard | RTT từ vài ms lên hàng trăm ms, sự kiện trễ theo; nhưng POS vẫn báo "xử lý tại chỗ trong ~5 ms" |
| K6 | Chống trùng (phụ) | Phát lại toàn bộ sự kiện | Dòng đầu dashboard | Số bản trùng bỏ qua tăng vọt, bảng tồn không đổi |
| K7a | Chịu lỗi broker | Dừng 1/3 broker, bán tiếp | Dashboard; Console | Đồng bộ tiếp sau vài giây, leader chuyển sang broker khác; không mất sự kiện |
| K7b | Mất đa số broker | Dừng 2/3 broker, bán tiếp, rồi bật lại | POS; dòng "Đồng bộ" trên dashboard | POS "Gửi lên Redpanda: lỗi từ HH:MM:SS", outbox tăng; dashboard "Đồng bộ dừng từ HH:MM:SS", chi nhánh vẫn "còn sống"; bật lại thì tự đồng bộ bù |
| K7c | Mất máy A (broker + nginx) | Rút mạng máy A | Dashboard máy B, C (cổng 8000) | B và C vẫn đồng bộ với nhau qua 2 broker còn lại; cắm lại thì 3 bản sao khớp |
| K8 | Bản sao tự vá lẫn nhau (gossip) | Dừng sink B, bán, cho B bỏ qua các sự kiện đó | Bảng bản sao (cột Gossip); dashboard B | B lệch rồi khớp lại trong ≤ 20 giây, "vá N ô"; B mãi ít hơn A N sự kiện đã áp nhưng vẫn "Khớp từng ô" |
| K9 | Đối soát với chi nhánh | Dừng cả 3 broker, bán ở CN2 | Dòng "Đồng bộ"; ô CN2 trên bảng tồn | Sau 15–25 giây kể từ "dừng từ", 3 bản sao cập nhật CN2, ô có chấm cam "đối soát", 3 dấu vân tay khớp dù broker còn dừng |
| K11 | Đọc đơn điệu | Dừng sink B, bán ở CN2, xem dashboard qua nginx | Dải vàng đầu trang; vệt served-by ở thanh bên; tab Tồn kho, cột CN2 | Lần B trả lời: số CN2 **không lùi**, ô vàng trong vệt, "Bản sao B trễ N sự kiện ở CN2"; gossip vá B thì nhãn tự mất |
| K12 | Truy vết sự kiện | Tab Sự kiện, bấm một sự kiện | Khung truy vết bên phải | Mốc chi nhánh ghi, broker ghi (phân hoạch, offset, timestamp Kafka), relay đánh dấu đã gửi, từng bản sao nhận qua Redpanda hay được vá bằng gossip/đối soát |
| K13 | Mất cổng vào, client tự chuyển | Mở dashboard và POS qua cổng A, giết hoặc treo nginx A | Ô "Cổng vào" ở thanh bên; dòng "cập nhật" ở đầu trang; thông báo dưới phiếu POS | Trang tự chuyển sang cổng B, vẫn làm mới; lượt bán dở gửi lại qua cổng B không trừ hai lần |
| K15 | Chi nhánh sập vẫn bán (ghi hộ) | Dừng `branch_api`, `branch_db` của B; bán 5 đơn ở POS qua cổng vào; bật lại | POS `localhost/cn2/` (dải trạng thái, dải đỏ "bị từ chối"); bảng chi nhánh (cột Ghi hộ), dải sự cố | POS "chờ" → "Đang ghi hộ qua trung tâm (bản sao A)"; bật lại: "Chi nhánh đang phục hồi", rồi bán tại chỗ; cột Ghi hộ "chờ 5" → "đã áp 5"; 3 dấu vân tay khớp. Biến thể: lượt vượt tồn thật thành REJECTED |
| K14 | Chậm hay chết, kết luận theo đa số | Pause rồi kill `branch_api` của B; biến thể chỉ cắt CN2 → bản sao A | Bảng chi nhánh (Tổng quan), dải sự cố; tab Hệ thống, bảng kỹ thuật chi nhánh cột "Góc nhìn từng bản sao", "Kết luận (đa số)" | Cả hai ca đi Nghi ngờ rồi Mất liên lạc; biến thể: góc nhìn A "mất", kết luận vẫn "sống" |

Trên sơ đồ đồng bộ khi chạy lại K1–K9 (22/11/2026, 3 node một máy, `make local-reset` sau vòng 4). Đã kiểm trên
giao diện (Chrome headless, đọc trạng thái từng cạnh và chụp màn hình): K1, K2, K3, K4, K7a, K7b, K7c, K9. K5, K6
kiểm số qua API (RTT, bản trùng, dấu vân tay); phần nhấp nháy ở K6 và cạnh sink B xám ở K8 suy từ logic đã kiểm bằng
`?selftest=1` (ảnh K11 chụp 7 giây sau khi dừng sink B nên cạnh còn xanh, ngưỡng là 15 giây):

| # | Sơ đồ phải thấy |
|---|---|
| K1 | Mọi cạnh xanh; cạnh relay CN2 và cụm → sink A, B, C nhấp nháy khi bán; cụm "3/3 broker" |
| K2 | Hộp bản sao đang trả lời viền đậm, đổi theo vệt `A B C` |
| K3 | Hộp bản sao B đỏ "không liên lạc được", CN2 đỏ "mất liên lạc", broker 2 đỏ "0/2 sink thấy", cụm "2/3 broker", gossip A–B và B–C đỏ. Mở thẳng `:8010`: "chỉ có góc nhìn của bản sao này", B thấy CN1, CN3 mất liên lạc, sink B đỏ, cạnh đối soát B → CN2 vàng |
| K4 | Mọi cạnh xanh lại; trong lúc đuổi nhau có thể hiện dải đọc đơn điệu ("Bản sao C trễ 8 ô ở CN2"), số không lùi |
| K5 | Không đổi màu (RTT nằm trên thẻ CN2: 607 ms) |
| K6 | Cạnh sink A nhấp nháy liên tục; mọi cạnh xanh |
| K7a | Broker đã dừng đỏ "0/3 sink thấy", cụm "2/3 broker"; vài chục giây đầu broker còn sống có thể vàng "k/3 sink thấy" (các sink thấy metadata khác nhau) rồi xanh lại |
| K7b | Relay ba chi nhánh đỏ "gửi lỗi từ …", cụm → sink đỏ, cụm "không hỏi được", broker xám "không biết"; sau ~15 giây hiện cạnh đối soát vàng nét đứt từ mọi bản sao tới mọi chi nhánh; thẻ "Còn sống, đồng bộ dừng" |
| K7c | Mở thẳng `:8010`: broker 1 đỏ, CN1 đỏ, gossip B–A đỏ, B–C xanh; sau `heal` mọi cạnh xanh trong ~25 giây |
| K8 | Cụm → sink B xám "sink không chạy" (sau 15 giây); cạnh gossip A–B / B–C nhấp nháy khi vá |
| K9 | Như K7b, thêm relay CN1, CN3 vẫn xanh nếu không bán gì (relay chỉ ghi trạng thái khi có lô để gửi) |

### Danh mục cảnh báo (vòng 6b)

Mọi tình huống lỗi trong hệ đều có một cảnh báo: mức **đỏ** (dữ liệu ngừng chảy, quầy hoặc người xem bị ảnh hưởng) hoặc
**vàng** (suy giảm nhưng hệ tự chịu được hay tự xử lý), ghi "từ HH:MM:SS", tự tắt khi hết lỗi. Trình duyệt tự tính từ dữ
liệu đang lấy về (`api/overview`, `/replica/<X>/api/digest`, `/cn<N>/api/status`, dò cổng vào); server không đổi gì.

Quy ước:
- **Mốc "từ"** lấy từ server khi có (`broker_lost_at`, `broker_checked_at`, `failing_since` của relay và gossip,
  `last_seen`, `recovery.since`, `rejected_at`, `oldest_unsent_s`, `seconds_since_ok`); không có thì là lúc trang thấy
  lần đầu, ghi "từ ~HH:MM:SS" (mở trang giữa chừng sự cố thì mốc này muộn hơn thật).
- **Chống nháy**: cảnh báo không có mốc server bật khi điều kiện đúng ở 2 lần làm mới liên tiếp (`ALERT_CONFIRM`, khoảng
  4 giây); mọi cảnh báo tắt khi điều kiện sai ở 2 lần làm mới liên tiếp. Một số dòng có ngưỡng riêng (cột Ngưỡng).
  Cùng sự cố bật lại trong 10 giây sau khi tắt (chập chờn, ví dụ metadata broker sau `heal`) thì nối vào dòng nhật ký cũ.
- **Không lặp**: mỗi sự cố một mã cố định (`branch:2` dùng chung cho nghi ngờ và mất liên lạc: lên mức vẫn là một sự cố).
  Cảnh báo **gốc** gộp các **hệ quả** của nó vào cùng một dòng ("kéo theo: …"); chỉ cảnh báo gốc vào nhật ký. Cảnh báo
  vừa thành hệ quả (lên mức: "Bản sao B không liên lạc được" → "Máy B mất liên lạc") tắt ngay, không chờ 2 lần vắng;
  nhật ký ghi "gộp vào: …" ở cột Kết thúc (lỗi chưa hết, chỉ đổi cảnh báo gốc).
- **Xếp**: đỏ trước vàng, cùng mức thì sự cố bắt đầu sớm hơn đứng trước.
- **Nhật ký sự cố** (tab Hệ thống, thẻ "Nhật ký sự cố"): mỗi cảnh báo gốc một dòng: mức cao nhất đã có, chữ, bắt đầu,
  kết thúc, kéo dài; lưu `localStorage` (`minigo.incidents`, tối đa 200 dòng) nên mỗi trình duyệt một nhật ký, tải lại
  trang vẫn còn, nút "Xoá nhật ký". Sự cố xảy ra khi không có trang nào mở thì không có trong nhật ký.
- **Mở thẳng một bản sao** (`:8000`, `:8010`): chỉ có cảnh báo từ góc nhìn của bản sao đó (cột "Mở thẳng"), kèm dòng
  "chỉ góc nhìn của bản sao X". POS mở thẳng chi nhánh (`:8001`): không có P-04, P-05, P-09.

**Dashboard.** Dải `#sys-alert` ở đầu tab Tổng quan (mọi dòng trừ D-19, D-20); D-19 ở dải `#conn-error`, D-20 ở dải
`#mono` (cả hai hiện ở mọi tab). Chấm cạnh tên tab Tổng quan theo mức cao nhất. Mọi dòng vào nhật ký.

| # | Điều kiện kích hoạt | Ngưỡng | Mức | Chữ hiện (rút gọn) · mốc "từ" | Gộp làm hệ quả | Tự tắt khi | Mở thẳng | Kịch bản |
|---|---|---|---|---|---|---|---|---|
| D-01 | Bản sao X không trả lời qua cổng vào **và** đa số kết luận chi nhánh cùng máy OFFLINE | 2 lần làm mới | đỏ | "Máy B mất liên lạc (bản sao B, CN2)" · `last_seen` của CN | D-05, D-06, D-08, D-09, D-13 của máy đó | bản sao trả lời lại hoặc chi nhánh hết OFFLINE | không | K3, K7c (qua cổng `8012`) |
| D-02 | ≥ 2 bản sao trả lời, **mọi** sink đang chạy có `broker_ok = false`, sink mất sớm nhất đã đủ 15 giây (`broker_lost_at`) | 15 giây (`BROKER_ALERT_S`; dưới đó là bầu leader, đo ở K3: 6–10 giây) | đỏ | "Cụm Redpanda mất đa số, đồng bộ qua Redpanda dừng"; có đối soát thì thêm "đang đối soát thẳng với chi nhánh (lần cuối …)" · `broker_lost_at` sớm nhất | D-03, D-07, D-16, D-17 | sink đọc lại được | không (thành D-03) | K7b, K9 |
| D-03 | Sink của bản sao X đang chạy, mất broker từ 15 giây, không thuộc D-02 | 15 giây | đỏ | "Bản sao X không đọc được Redpanda" (+ đối soát như D-02) · `broker_lost_at` | — | đọc lại được | có | K3 (mở thẳng `:8010`), K7c (qua cổng A) |
| D-04 | Sink của bản sao X không kiểm broker quá 15 giây (`broker_checked_at`) | 15 giây | vàng | "Sink bản sao X dừng (kiểm lần cuối …)" · `broker_checked_at` | D-07 của X | sink chạy lại | có | K8, K11 |
| D-05 | Broker k: không sink nào (đang đọc được cụm) thấy nó trong metadata; cụm còn đa số | liên tục 30 giây (sau khi một broker dừng, metadata mọi sink có thể bỏ sót cả broker còn sống: đo ở K7a 6 và 22 giây) | vàng | "Broker B không chạy (cụm còn 2/3)" · ~trang thấy | — | broker có lại | có, nếu sink bản sao này đọc được cụm | K7a |
| D-06 | Bản sao X không trả lời qua cổng vào, không thuộc D-01 | 2 lần làm mới | vàng | "Bản sao X không liên lạc được" · `failing_since` gossip sớm nhất của bản sao khác về X | D-08 tới X | trả lời lại | không (thành D-08) | K3 (15 giây đầu), K7c (qua cổng A) |
| D-07 | Dấu vân tay bản sao X khác bản sao dẫn đầu, sink X đang chạy | liên tục 20 giây | vàng | "Bản sao X lệch dữ liệu so với bản sao Y, gossip chưa vá" · ~trang thấy | — | khớp lại | không | selftest; chạy tay: K8 (gộp dưới D-04) |
| D-08 | Gossip X → Y có `failing_since` cũ hơn 15 giây (2 lần gossip lỗi), X trả lời | 15 giây | vàng | "Gossip X → Y lỗi" · `failing_since` | — | gossip lại được | có | K3 (mở thẳng `:8010`: B → A, B → C) |
| D-09 | Kết luận đa số (`verdict`) về CNn là OFFLINE | theo PT-13 | đỏ | "CN2 mất liên lạc (3/3 bản sao)" · `last_seen` | D-12, D-13, D-17 của CNn | hết OFFLINE | có | K14, K15 |
| D-10 | `verdict` là SUSPECT (cùng sự cố với D-09) | theo PT-13 | vàng | "CN2 nghi ngờ, chưa đủ đa số" · `last_seen` | như D-09 | hết SUSPECT | có | K14; K3 (mở thẳng `:8010`: CN1, CN3) |
| D-11 | `verdict` là ONLINE nhưng có bản sao thấy SUSPECT/OFFLINE | liên tục 10 giây | vàng | "Bản sao A không nhận heartbeat CN2 (1/3 góc nhìn, kết luận vẫn sống)" · ~trang thấy | — | mọi góc nhìn sống | có | K14 biến thể |
| D-12 | Chi nhánh RECOVERING (`recovery.state`; mở thẳng: `recovering` trong heartbeat) | ngay | vàng | "CN2 đang phục hồi (áp ghi hộ, chưa nhận bán): đã áp a, còn p" · `recovery.since` | D-13 của CNn | ONLINE | có, mốc ~ | K4, K14, K15 |
| D-13 | Còn lượt ghi hộ PENDING (cộng qua digest), chi nhánh không OFFLINE, không RECOVERING | 2 lần làm mới | vàng | "CN2: n lượt ghi hộ chờ chi nhánh áp" · ~trang thấy | — | hết PENDING | có | K15 (gộp dưới D-09, D-12) |
| D-14 | Có lượt ghi hộ REJECTED (`recovery.rejected_items`) trong 5 phút gần nhất | 5 phút | đỏ | "CN2: k lượt ghi hộ bị TỪ CHỐI khi áp lại (mã 11 ×10, tồn thật 2)" · `rejected_at` | — | 5 phút sau lượt mới nhất (vẫn còn ở cột Ghi hộ và nhật ký) | có, đếm từ digest, mốc ~, tắt sau 5 phút kể từ lúc trang thấy | K15 biến thể REJECTED |
| D-15 | `recovery.incomplete` | ngay | vàng | "CN2 phục hồi chưa đủ: chưa gom được ghi hộ từ bản sao C" · `recovery.since` | — | hết `incomplete` | không | chạy tay riêng: K15 trong lúc dừng `replica_api` C quá 60 giây |
| D-16 | `relay.failing_since` của CNn cũ hơn 15 giây | 15 giây (relay lỗi vài giây lúc bầu leader, đo ở K7c) | đỏ | "CN2 gửi lên Redpanda lỗi" · `failing_since` | D-17 của CNn | relay gửi được | không | K7b (gộp dưới D-02), K7c (qua cổng A, CN1) |
| D-17 | Outbox CNn có sự kiện chờ quá 10 giây (`oldest_unsent_s`; mở thẳng: `outbox_backlog > 0` liên tục 10 giây theo heartbeat), relay không báo lỗi (relay lỗi dưới 15 giây thì chưa báo cả hai) | 10 giây | vàng | "CN2: k sự kiện chờ gửi lên Redpanda (relay không chạy?)" · giờ sự kiện cũ nhất | — | outbox về 0 | có, mốc ~ | K15 biến thể REJECTED (`make kill N=b S=relay`) |
| D-18 | Dò cổng vào X lỗi (mỗi 10 giây `GET <cổng>/lb/gateways.json`, chờ 2 giây; trang vừa chuyển khỏi X thì dò ngay). Trang chuyển cổng mà dò X vẫn trả lời (bản sao, chi nhánh phía sau chậm) thì không báo, thanh bên vẫn ghi đã chuyển | lần dò lỗi đầu | vàng | "Cổng vào localhost không trả lời (đã chuyển sang localhost:8012)" · lần lỗi đầu | — | dò lại được (trang vẫn ở cổng mới) | không | K13 |
| D-19 | Không đọc được `api/overview` qua mọi cổng | ngay | đỏ | dải `#conn-error` như cũ, thêm "từ …" · ~trang thấy | — | đọc lại được | có | mọi nginx (hoặc bản sao đang mở thẳng) chết |
| D-20 | Đọc đơn điệu: bản sao X trả lời cũ hơn số đang hiện | ngay | vàng | dải `#mono` như cũ ("Bản sao B trễ 5 sự kiện ở CN2"), thêm "từ ~…" | — | phản hồi của X được nhận lại | không | K11, K4 |

**POS.** Dải trạng thái `#link` dưới tên chi nhánh thành danh sách cảnh báo (thay cho `#link` và `#note` cũ), xếp
như dashboard; không có cảnh báo thì như cũ ("Mọi lượt bán đã gửi lên trung tâm" / "Đang gửi n sự kiện"). POS không
có nhật ký.

| # | Điều kiện kích hoạt | Mức | Chữ hiện (rút gọn) · mốc "từ" | Gộp | Tự tắt khi | Mở thẳng | Kịch bản |
|---|---|---|---|---|---|---|---|
| P-01 | `relay.failing_since` | đỏ | "Gửi lên Redpanda: lỗi từ HH:MM:SS. Quầy vẫn bán; n sự kiện chờ trong outbox" | P-02 | relay gửi được | có | K7b, K3 |
| P-02 | `sync_stuck` (sự kiện cũ nhất chờ ≥ 5 giây), relay không báo lỗi | vàng | "n sự kiện chưa gửi lên trung tâm" · giờ sự kiện cũ nhất | — | outbox về 0 | có | K15 biến thể REJECTED |
| P-03 | Heartbeat tới bản sao X lỗi (`links[].ok = false`) | vàng | "Bản sao máy A mất liên lạc" · now − `seconds_since_ok` | — | heartbeat lại được | có | K3, K7c, K14 biến thể |
| P-04 | Chế độ `waiting` (chi nhánh lỗi 2 lần, kết luận chưa OFFLINE), chỉ khi mở qua cổng vào | đỏ | như vòng 6 ("Không gọi được chi nhánh … Chưa ghi hộ") · ~lần lỗi đầu | — | chi nhánh trả lời hoặc chuyển ghi hộ | không | K15 |
| P-05 | Chế độ `handoff` | vàng | như vòng 6 ("Đang ghi hộ qua trung tâm (bản sao A)") · ~trang thấy | — | chi nhánh trả lời lại | không | K15 |
| P-06 | Chế độ `recovering` | vàng | như vòng 6 ("Chi nhánh đang phục hồi …") · `recovery.since` | — | ONLINE | có | K4, K14, K15 |
| P-07 | `recovery.incomplete` | vàng | như vòng 6 ("Phục hồi chưa đủ …") · `recovery.since` | — | hết `incomplete` | có | như D-15 |
| P-08 | `recovery.rejected_items` có lượt chưa được bấm **"Đã biết"** | đỏ | như vòng 6 ("Lượt ghi hộ bị TỪ CHỐI …") · `rejected_at` sớm nhất, nút "Đã biết" | — | **chỉ khi thu ngân bấm "Đã biết"** (lưu `localStorage` `minigo.rejectedAck` theo `request_id`); không tự tắt theo thời gian | có | K15 biến thể REJECTED |
| P-09 | Dò cổng vào lỗi (như D-18; chuyển cổng vì chi nhánh treo, cổng vẫn trả lời thì không báo, đo ở K14) | vàng | "Cổng vào localhost không trả lời, đang dùng localhost:8012" · lần lỗi đầu | — | dò lại được | không | K13 |
| P-10 | Mở thẳng chi nhánh mà không đọc được dữ liệu của chính nó | đỏ | "Không đọc được dữ liệu của chính chi nhánh …" · ~trang thấy | — | đọc lại được | chỉ mở thẳng | dừng `branch_db` khi mở `:8011` |

Kịch bản không phải lỗi nên **không** có cảnh báo nào: K1, K2, K5 (trễ, không mất gói), K6, K12. Thời gian hiện, tắt đo
được ghi ở `docs/tests.md`.

**Cảnh báo phải thấy theo kịch bản** (nhìn ở dải đầu tab Tổng quan, POS dải dưới tên chi nhánh, nhật ký ở tab Hệ thống;
giây tính từ lúc gây lỗi, đo 27/11/2026, 3 node một máy):

| # | Dashboard qua cổng vào | Dashboard mở thẳng / POS | Hết lỗi |
|---|---|---|---|
| K3 | "Bản sao B không liên lạc được" (giây 6), "CN2 nghi ngờ" (11), rồi một dòng đỏ "Máy B mất liên lạc (bản sao B, CN2)" kéo theo broker B, gossip, CN2 (15). Có lần cổng A chờ phân giải `replica-b` quá 4 giây nên trang tự chuyển sang cổng 8012 (phía B bị cô lập): thanh bên ghi đã chuyển, dải thấy "Bản sao A, C không liên lạc được" | `:8010`: đỏ "Bản sao B không đọc được Redpanda; đang đối soát thẳng với chi nhánh", "CN1, CN3 nghi ngờ", "Gossip B → A / B → C lỗi", "CN2: n sự kiện chờ gửi (theo heartbeat)". POS `:8011`: "Bản sao máy A, C mất liên lạc", "n sự kiện chưa gửi", rồi đỏ "Gửi lên Redpanda: lỗi từ …" | K4 |
| K4 | "Máy B mất liên lạc" tắt 2–3 giây sau `heal`; ≤ 15 giây còn lẻ "Gossip … lỗi", "CN2 mất liên lạc", "Bản sao B không đọc được Redpanda" (mỗi kênh tự thử lại theo chu kỳ riêng), "CN2 đang phục hồi" vài giây; nhật ký đủ dòng bắt đầu, kết thúc | POS: "Chi nhánh đang phục hồi" rồi "Mọi lượt bán đã gửi" sau ~10 giây | — |
| K7a | "Broker B không chạy (cụm còn 2/3)" ở giây ~43 (chờ 30 giây vì metadata chập chờn) | — | tắt 7 giây sau khi bật broker |
| K7b, K9 | Một dòng đỏ "Cụm Redpanda mất đa số …; đang đối soát thẳng với chi nhánh" ở giây 17–23, kéo theo relay, outbox | POS: "n sự kiện chưa gửi" (11), đỏ "Gửi lên Redpanda: lỗi từ …" (15) | POS hết sau ~9 giây; dashboard sau ~55–60 giây (sink đọc lại chậm, `docs/plan.md` mục 6), có lúc chuyển thành từng "Bản sao X không đọc được Redpanda" rồi tắt |
| K7c | Qua cổng 8012: "Bản sao A không liên lạc được" (5), rồi đỏ "Máy A mất liên lạc" (14). Qua cổng A: "Bản sao B, C không liên lạc được", "CN2, CN3 nghi ngờ", đỏ "Bản sao A không đọc được Redpanda", "CN1 gửi lên Redpanda lỗi" | POS `:8001`: "Bản sao máy B, C mất liên lạc", đỏ "Gửi lên Redpanda: lỗi" | ≤ 15 giây sau `heal` |
| K8, K11 | "Sink bản sao B dừng (kiểm lần cuối …)" kéo theo "lệch dữ liệu" (14); dải vàng "Bản sao B trễ 5 sự kiện ở CN2 (từ ~…)" | `:8010`: "Sink bản sao B dừng" | 5 giây sau khi bật sink; dải đọc đơn điệu hết khi gossip vá |
| K13 | "Cổng vào localhost không trả lời, đã chuyển sang localhost:8012" (1) | POS qua cổng: cùng cảnh báo | 5 giây sau khi bật nginx A (dò cổng); trang vẫn ở cổng mới |
| K14 | Pause: "CN2 nghi ngờ" (12), đỏ "CN2 mất liên lạc (2/3 bản sao)" (20); unpause: "CN2 đang phục hồi". Kill: nghi ngờ (8), mất liên lạc (12). Biến thể: "Bản sao A không nhận heartbeat CN2 (1/3 góc nhìn, kết luận vẫn sống)" (18) | POS qua cổng: đỏ "Không gọi được chi nhánh … Chưa ghi hộ" (4), "Đang ghi hộ qua trung tâm" (12); biến thể: "Bản sao máy A mất liên lạc" (3) | 5–10 giây sau `unpause`, `start`, `tre.sh off` |
| K15 | "CN2 nghi ngờ" (8), đỏ "CN2 mất liên lạc" kéo theo "5 lượt ghi hộ chờ áp" (19) | POS: đỏ "Không gọi được chi nhánh" (3), "Đang ghi hộ qua trung tâm (bản sao A): 5 lượt chờ" (18) | ~9 giây sau `start`; RECOVERING dưới 2 giây nên có lần không kịp hiện "đang phục hồi" |
| K15 REJECTED | "CN2: 1 sự kiện chờ gửi lên Redpanda (relay không chạy?)" (15 giây sau khi giết relay); sau khi bật lại: đỏ "CN2: 1 lượt ghi hộ bị TỪ CHỐI khi áp lại (mã 11 ×10, tồn thật 2)" | POS: "n sự kiện chưa gửi" (10); đỏ "Lượt ghi hộ bị TỪ CHỐI …" kèm nút **Đã biết** | dashboard: 5 phút sau lượt bị từ chối; POS: khi bấm Đã biết |
| D-15 | "Bản sao C không liên lạc được"; 60 giây sau khi chi nhánh bật lại: "CN2 phục hồi chưa đủ: chưa gom được ghi hộ từ bản sao C" | POS: "Phục hồi chưa đủ …" | 7 giây sau khi bật `replica_api` C |
| P-10 | — | POS `:8011` khi dừng `branch_db`: đỏ "Không đọc được dữ liệu của chính chi nhánh" (5) | khi `branch_db` chạy lại |

Chi tiết từng kịch bản:

### K1. Đồng bộ dữ liệu giữa các máy

**Làm:** Trên POS máy B, thêm vài mặt hàng vào phiếu rồi bấm **Thanh toán** (vài lần).

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

**Nói:** Người dùng chỉ biết **một địa chỉ**. Họ không biết, và không cần biết, phía sau có mấy máy, máy nào đang trả lời, CN2 nằm ở đâu. Đó là tính trong suốt vị trí. Nginx ở đây vừa là **bộ cân bằng tải** vừa là cổng vào. Từ vòng 5 mỗi máy có một nginx giống hệt nhau (`localhost:8012/`, `localhost:8022/` trên một máy), nên địa chỉ nào cũng được; cổng đang dùng chết thì trang tự chuyển (K13).

### K3. Chịu lỗi và chuyển đổi khi lỗi: rút mạng máy B

**Làm:** Tắt Wi-Fi (hoặc rút dây mạng) máy B. Trên POS máy B, bấm **Bán 20 đơn ngẫu nhiên** (mục Công cụ demo). Chờ khoảng 20 giây.

**Thấy trên dashboard máy A (qua nginx):**
- Dashboard **vẫn chạy bình thường**. Vệt served-by chỉ còn `A A A`: nginx phát hiện bản sao B không trả lời và tự chuyển hết sang A. Thỉnh thoảng một lần làm mới chậm khoảng 1 giây, vì nginx chờ B 1 giây rồi mới bỏ cuộc và thử lại (xem `proxy_connect_timeout` trong `infra/nginx/default.conf.template`).
- Ô bản sao: dòng B ghi **Không liên lạc được**.
- Sau 15 giây, thẻ CN2 tô sọc đỏ "Mất liên lạc … giây", cột CN2 chuyển xám nghiêng kèm nhãn "số cũ". CN1 vẫn chạy bình thường.
- Mở `http://localhost/cn2/`: từ vòng 6 nginx trả chính trang POS (`@pos_page`); trang báo "Không gọi được chi nhánh"
  rồi, khi đa số kết luận OFFLINE, chuyển sang ghi hộ qua trung tâm (xem K15 biến thể hai nơi cùng ghi). Đường API
  `/cn2/api/...` vẫn trả trang 503 "Không liên lạc được với chi nhánh này".

**Thấy trên máy B:**
- POS **vẫn bán được**. Dải trạng thái chuyển đỏ "Chưa gửi được lên trung tâm từ … giây", số sự kiện chờ trong outbox tăng dần. Chip "Bản sao máy A: mất liên lạc".
- Tab `localhost:8000` (bản sao B) vẫn mở được. Điều thú vị là **bản sao B thấy CN2 còn sống còn CN1, CN3 mất liên lạc**, ngược hẳn với bản sao A. Nhưng từ vòng 5 (PT-13), B không lấy được góc nhìn của A, C nên chỉ có 1/3 góc nhìn: thẻ CN1, CN3 trên dashboard B ghi **"Nghi ngờ, chưa đủ đa số"** (bảng kỹ thuật ở tab Hệ thống: góc nhìn B "mất", A, C "–"), không ghi "Mất liên lạc". Phía A, C (đa số) thì kết luận CN2 "Mất liên lạc (2/3 bản sao)". B cũng mất broker (broker máy B một mình là thiểu số), nên sau khoảng 15 giây B **đối soát thẳng với CN2** (cùng máy): cột CN2 trên dashboard B có số mới kèm chấm cam "đối soát", trong khi CN1, CN3 đứng ở số cũ. Dashboard A lúc này vẫn thấy CN2 số cũ: hai bên mạng bị chia cắt có hai góc nhìn khác nhau.

**Nói:**
- Lỗi cục bộ: một máy chết, phần còn lại vẫn chạy, và người dùng qua nginx gần như không nhận ra.
- Mỗi bên mạng bị chia cắt vẫn phục vụ được, nhưng với số liệu cũ: **ưu tiên sẵn sàng hơn nhất quán**.
- Hai bản sao có hai "góc nhìn" khác nhau về việc ai còn sống. Trong hệ phân tán **không có trạng thái toàn cục** mà mọi máy cùng thấy, và một máy không phân biệt được "máy kia chết" với "đường mạng tới máy kia bị đứt".

### K4. Tự phục hồi: cắm mạng lại

**Làm:** Bật Wi-Fi máy B. **Không bấm gì thêm.**

**Thấy (trong khoảng 10–20 giây):**
1. Relay máy B gửi bù toàn bộ sự kiện tồn đọng; dải đỏ trên POS biến mất.
2. Dashboard máy A: các sự kiện của CN2 hiện ra, cột **Trễ** tô vàng (trên 5 giây); thẻ CN2 hết đỏ.
3. Ô bản sao: dòng B hiện **Đang đuổi theo, thiếu N sự kiện**, N giảm dần, rồi chuyển sang **Khớp từng ô**, cùng dấu vân tay với A.
4. Vệt served-by có lại chữ `B`: nginx tự đưa bản sao B trở lại sau tối đa 10 giây (`fail_timeout=10s`).
5. Từ vòng 6: POS máy B báo **"Chi nhánh đang phục hồi"** vài giây (bán trả 503 `branch_recovering`) rồi bán lại bình
   thường, dù không có lượt ghi hộ nào. Lý do: lúc vừa cắm lại, bản sao A, C vẫn kết luận CN2 OFFLINE (còn nhận ghi hộ),
   nên chi nhánh chờ tới khi không bản sao nào còn nhận ghi hộ (PT-14). Không phải lỗi. Đo 27/11/2026 (3 node một
   máy, `make heal N=b`): RECOVERING từ giây 4,6 tới giây 6,3; `make heal N=a` (K7c): CN1 RECOVERING từ giây 2,1 tới 5,9.

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

**Làm:** Trên máy B, bật Clumsy (hoặc tc) với trễ 300 ms tới máy A (mục 4). Bấm bán vài lần.

**Thấy:**
- Trên POS máy B: chip **Bản sao máy A** tăng từ vài chục ms lên khoảng 300–600 ms, còn chip **Bản sao máy B** vẫn thấp (cùng máy, không qua mạng).
- Trên dashboard: thẻ CN2 có **Độ trễ vòng (RTT)** tăng tương ứng; sự kiện của CN2 có độ trễ lớn hơn hẳn CN1.
- Nhưng dòng thông báo trên POS vẫn ghi **"Xử lý tại chỗ trong ~5 ms"**. Khách không phải chờ thêm chút nào.

RTT đo được gồm cả thời gian bản sao xử lý heartbeat (ghi vào CSDL), nên khi chưa bật giả lập, con số thường khoảng 5–40 ms chứ không phải 0.

**Nói:** Đặt hai con số cạnh nhau để so sánh. Nếu hệ thống tập trung, mỗi lượt bán phải đi về trung tâm ít nhất một vòng, tức ít nhất 300–600 ms, và thực tế nhiều hơn vì một transaction cần vài lượt hỏi đáp với CSDL. Kiến trúc này đẩy độ trễ ra khỏi đường bán hàng, chỉ để nó ảnh hưởng tới việc đồng bộ, đúng tinh thần Edge Computing: xử lý ở gần người dùng.

**Thêm mất gói:** bật Drop 20% (hoặc `sh tre.sh on 300 <IP máy A> 20`). Sự kiện đến chậm hơn, heartbeat chập chờn, nhưng sau khi tắt Clumsy, dấu vân tay hai bản sao vẫn khớp: **không mất sự kiện nào**, vì relay chỉ đánh dấu đã gửi khi Redpanda xác nhận.

Nhớ **Stop** Clumsy (hoặc `tre.sh off`) sau khi xong.

### K6 (phụ). Phát lại sự kiện, số vẫn đúng

Trên máy A:

```bash
docker compose stop sink
docker compose exec redpanda rpk group seek replica-A --to start
docker compose start sink
```

Dòng đầu dashboard (khi bản sao A trả lời): số "bỏ qua … bản trùng" tăng vọt, bảng tồn không đổi, dấu vân tay A vẫn khớp B. Áp một sự kiện nhiều lần cho kết quả như áp một lần (idempotent), nên hệ thống được phép gửi lại thoải mái.

### K7. Redpanda gặp sự cố (câu hỏi của thầy)

Ba máy, ba broker thành một cụm Raft; topic `inventory.movement` có 3 bản mỗi phân hoạch (RF=3), `acks=all` nghĩa là
đa số broker đã ghi đĩa (đã tắt write caching và bỏ-fsync của chế độ dev). Mở sẵn: dashboard qua nginx, POS CN2,
Console `http://localhost:8080` (mục Topics → `inventory.movement` → Partitions, cột Leader).

Lệnh dừng/bật broker: máy thật `docker compose stop redpanda` / `docker compose start redpanda` trên máy đó; một máy
`docker stop minigo-b-redpanda-1` / `docker start minigo-b-redpanda-1`. Xem cụm: `rpk cluster health` (mục 9).

#### K7a. Mất 1/3 broker: phòng bằng cụm

**Làm:** Ở Console xem broker nào đang là leader phân hoạch 0. Dừng broker đó. Bấm **Bán 20 đơn ngẫu nhiên** ở cả ba
POS.

**Thấy:**
- POS cả ba chi nhánh gửi xong trong vài giây; dashboard cập nhật bình thường. Có thể thấy "Đồng bộ dừng" vài giây
  lúc cụm bầu leader mới, rồi tự hết.
- Console: cột Leader của phân hoạch đó chuyển sang broker khác.
- Bật lại broker: cụm `Healthy: true`, 3 bản sao cùng dấu vân tay; số sự kiện mỗi bản sao bằng số dòng sổ cái của
  từng chi nhánh: **không mất sự kiện nào**.

**Nói:** Raft cần đa số (2/3). Mất một broker vẫn còn đa số nên tự bầu leader mới; producer và consumer đọc lại
metadata rồi tự chuyển sang leader mới. Không ai phải làm gì.

#### K7b. Mất đa số broker: chống bằng hiển thị rõ, quầy vẫn bán

**Làm:** Dừng 2 broker (B và C). Bán 20 đơn ở mỗi POS, chờ 20 giây, bán thêm. Rồi bật lại cả hai, **không làm gì thêm**.

**Thấy:**
- POS vẫn bán bình thường. Dải trạng thái đỏ "Gửi lên Redpanda: lỗi từ HH:MM:SS", số sự kiện chờ trong outbox tăng.
- Dashboard: dòng "Đồng bộ qua Redpanda dừng từ HH:MM:SS: bản sao này không đọc được Redpanda … sau 15 giây sẽ đối
  soát thẳng với chi nhánh". Thẻ chi nhánh ghi "Còn sống, đồng bộ dừng": heartbeat (HTTP thẳng) vẫn tới, chỉ đồng bộ
  (qua broker) dừng. Hai trạng thái được tách.
- Khoảng 15–25 giây sau mốc "dừng từ": dòng đó đổi thành "**đang đối soát thẳng với chi nhánh** (lần cuối
  HH:MM:SS)"; các ô vừa bán cập nhật kèm chấm cam "đối soát", 3 dấu vân tay khớp **ngay trong lúc broker còn dừng**
  (chi tiết ở K9).
- Bật lại: outbox về 0 trong khoảng 10 giây, dải đỏ biến mất; sink đọc tiếp sau đó, sự kiện đến muộn hiện ra (số vàng),
  dashboard hết "Đồng bộ dừng", dấu vân tay không đổi (số đã đúng từ lúc đối soát).

**Nói:** Redpanda là đường nhanh, không phải nguồn sự thật. Nguồn sự thật là sổ cái từng chi nhánh: broker chết thì
chỉ chậm, không mất. Outbox giữ sự kiện, relay chỉ đánh dấu đã gửi khi cụm xác nhận (PT-03), sink chỉ commit sau khi
ghi CSDL (PT-06). Trong lúc chờ, bản sao đọc thẳng nguồn sự thật qua API (đối soát).

#### K7c. Mất cả máy A (broker 1 và nginx)

**Làm:** Rút mạng máy A (một máy: `make cut N=a`). Bán ở POS máy B và C (`localhost:8001` trên máy đó; một máy
`localhost:8011`, `8021`). Mở thẳng dashboard máy B và C (cổng 8000; một máy `localhost:8010`, `8020`).

**Thấy:**
- Máy thật: địa chỉ nginx máy A không vào được; dashboard đang mở qua cổng A tự chuyển sang cổng B (K13), trang mới
  thì mở `http://<IP máy B>/`. Một máy: cổng `localhost/` vẫn trả lời (cổng host không đi qua `minigo-wan`) nhưng
  nginx A chỉ thấy bản sao A; dùng cổng `localhost:8012/` để xem phía B, C.
- Sau 10–20 giây, dashboard B và C cùng dấu vân tay, cùng số sự kiện: hai máy còn lại vẫn đồng bộ qua 2 broker.
  Dashboard A đứng ở số cũ, báo "Đồng bộ dừng"; POS CN1 báo lỗi gửi nhưng vẫn bán.
- Cắm lại (`make heal N=a`): CN1 gửi bù, 3 bản sao khớp mà không thao tác tay.

Đo ngày 19/11/2026 (3 node một máy): K7a outbox về 0 trong ≤ 4–16 giây, không mất sự kiện; K7b đồng bộ bù xong
khoảng 15 giây sau khi bật lại; K7c B và C khớp nhau sau 8–16 giây, sau `heal` 3 bản sao khớp trong 3–38 giây.

Đo lại ngày 22/11/2026 (vòng 3, có gossip và đối soát): K7a outbox về 0 sau ~14 giây, 3 bản sao khớp sau ~18 giây,
sổ cái = `event_log`; K7b 3 bản sao đối soát xong 11–18 giây sau mốc mất broker và khớp trong lúc broker còn dừng; bật
lại thì outbox về 0 sau 11 giây nhưng **sink đọc tiếp sau ~55 giây** (vòng 2 đo ~15 giây; vòng 3 không sửa sink, chưa
rõ nguyên nhân), dấu vân tay không đổi trong suốt thời gian đó; K7c B, C khớp sau 13 giây, A (bị cô lập) tự đối soát
CN1, sau `heal` 3 bản sao khớp trong 5 giây.

### K8. Bản sao tự vá lẫn nhau: gossip

Mở sẵn: dashboard qua nginx (bảng "Các bản sao trung tâm", cột **Gossip**), dashboard B (`localhost:8010` một máy;
dòng "Gossip lần cuối …" dưới dòng đồng bộ).

**Làm:**
1. Dừng sink B: `docker stop minigo-b-sink-1` (máy thật: `docker compose stop sink` trên máy B).
2. Bán vài đơn ở CN2 và CN1: `curl -X POST "localhost:8011/api/sale/random?count=5"`, `curl -X POST "localhost:8001/api/sale/random?count=3"`.
3. Chờ, không làm gì. Đo bằng vòng lặp in dấu vân tay hai bên mỗi 2 giây:
   ```bash
   for i in $(seq 15); do date +%T; for p in 8000 8010; do curl -s localhost:$p/api/digest | grep -o '"fingerprint":"[^"]*"'; done; sleep 2; done
   ```
4. Cho B bỏ qua hẳn các sự kiện đó trên Redpanda, rồi bật sink:
   `docker exec minigo-a-redpanda-1 rpk group seek replica-B --to end`, `docker start minigo-b-sink-1`.

**Thấy:**
- Sau 1–2 giây A, C đổi dấu vân tay, B đứng ở số cũ (bảng bản sao: "Đang đuổi theo"); dashboard B báo sink không chạy.
- Trong **≤ 20 giây** kể từ lúc A cập nhật, B khớp lại ("Khớp từng ô"), cột Gossip của B: "vá N ô; A … giây trước".
  N = số ô vừa bán. Log: `docker logs minigo-b-replica_api-1 | grep gossip` → "Vá N ô nhờ bản sao A".
- Sau bước 4: dấu vân tay B vẫn khớp; "Sự kiện đã áp" của B **mãi ít hơn A đúng số sự kiện đã bỏ qua** (gossip chỉ vá
  số tồn, không bịa dòng nhật ký, `docs/db.md` mục 3). Bán tiếp thì B nhận qua Redpanda như thường, khoảng cách giữ nguyên.

**Nói:** Ngoài log chung, các bản sao nói chuyện trực tiếp: mỗi 10 giây so dấu vân tay, lệch thì kéo snapshot của
bên kia và merge từng ô theo luật "`movement_id` lớn hơn thắng". Luật này giao hoán, lũy đẳng (CRDT dạng trạng thái),
nên merge bao nhiêu lần, từ ai, theo thứ tự nào cũng hội tụ. Chỉ vá ô thiếu ở 2 lần kiểm liên tiếp, để kênh chính
(Redpanda) có thời gian làm việc: bán bình thường (K1) thì "vá 0 ô".

Vì sao "≤ 20 giây": gossip chạy mỗi 10 giây; lần kiểm đầu thấy lệch chỉ ghi nhớ, lần sau (10 giây sau) mới vá.

### K9. Đối soát với chi nhánh khi mất cả cụm broker

**Làm:** Dừng cả 3 broker (`docker stop minigo-a-redpanda-1 minigo-b-redpanda-1 minigo-c-redpanda-1`; máy thật:
`docker compose stop redpanda` trên cả ba máy). Bán 5 đơn ở CN2. Chờ khoảng 30 giây. Rồi bật lại cả 3 broker.

**Thấy:**
- Sau 4–7 giây: dashboard "Đồng bộ qua Redpanda dừng từ HH:MM:SS … sau 15 giây sẽ đối soát thẳng với chi nhánh".
- 15–25 giây sau mốc đó (sink kiểm 5 giây một lần, đối soát cũng vậy): "đang đối soát thẳng với chi nhánh (lần cuối HH:MM:SS)"; ô CN2 vừa bán đổi số kèm nhãn
  **chấm cam "đối soát"**; 3 bản sao cùng dấu vân tay dù broker vẫn dừng. `sync_peers` có dòng `CN2`, `reconcile`.
- Bật lại broker: outbox về 0, sink đọc tiếp, sự kiện đến muộn hiện ra (số vàng), "Sự kiện đã áp" tăng đúng 5, dấu vân tay
  không đổi. Chấm cam "đối soát" còn tới khi ô đó có lượt bán mới đi qua Redpanda.

**Nói:** Đây là tầng "phục hồi" của câu hỏi Redpanda: broker chỉ là đường nhanh, nguồn sự thật là sổ cái chi nhánh.
Mất cả cụm broker, bản sao đọc thẳng snapshot của chi nhánh qua API (chỉ đọc, không ghi về, không gọi thẳng CSDL chi
nhánh: PT-07) và merge bằng đúng luật của sink và gossip (PT-10). Chi nhánh trả tồn và `movement_id` mới nhất trong
**một câu lệnh**, nên hai con số nhất quán với nhau.

Đo ngày 22/11/2026 (3 node một máy):
- K8: B lệch lúc A cập nhật, khớp lại sau 13 giây, "vá 8 ô" (bán 5 + 3 đơn, 8 ô khác nhau); sau `seek --to end`
  "Sự kiện đã áp" B = 286 so với A = 294.
- K9: mốc mất broker 12:18:50; A, C đối soát xong lúc 12:19:08 (+18 giây), B lúc 12:19:12 (+22 giây); 3 dấu vân tay
  khớp trong lúc broker dừng. Bật lại: outbox về 0 sau 5 giây, sink đọc tiếp sau ~55 giây (như K7b), +5 sự kiện, dấu
  vân tay không đổi.

### K11. Đọc đơn điệu: bản sao trễ không làm số lùi lại

Mở sẵn: dashboard qua nginx `http://localhost/` (vệt served-by xen kẽ `A B C`).

**Làm:**
1. Dừng sink B: `docker stop minigo-b-sink-1` (máy thật: `docker compose stop sink` trên máy B).
2. Bán vài đơn ở CN2: `curl -X POST "localhost:8011/api/sale/random?count=5"` (hoặc bấm trên POS).
3. Nhìn dashboard khoảng 20 giây, không bấm gì. Đối chứng: mở thêm tab `http://localhost:8010` (thẳng bản sao B).
4. Bật lại: `docker start minigo-b-sink-1`.

**Thấy:**
- Sau 1–2 giây các ô CN2 đổi số (A hoặc C trả lời). Tới lượt B trả lời: số **giữ nguyên**, không lùi về số cũ; ô
  của B trong vệt served-by ở thanh bên tô vàng, ghi "(trễ, giữ số cũ)"; dải vàng đầu trang "Bản sao B trễ 5 sự kiện ở CN2
  (trả lời lúc HH:MM:SS). Đang giữ số mới nhất đã thấy, không để số lùi lại (đọc đơn điệu)". Bảng bản sao: B "Đang
  đuổi theo".
- Tab `:8010` (chỉ B) vẫn hiện số cũ: đó là số thật của B, chỉ lớp đọc đơn điệu của tab qua nginx mới giữ số mới.
- Trong ≤ 20 giây gossip vá B (K8), lần B trả lời sau đó được nhận lại, dải vàng tự mất.

**Nói:** Nhất quán cuối cho phép hai bản sao tạm khác nhau; qua nginx, hai lần làm mới liên tiếp có thể rơi vào hai
bản sao, nên trước vòng 4 số có thể "lùi lại". Đọc đơn điệu (Tanenbaum 7.3, mô hình lấy client làm trung tâm): đã
đọc x thì lần sau đọc x phải ra cùng giá trị hoặc mới hơn. Tab dashboard nhớ phiên bản từng ô (`movement_id` do chi
nhánh cấp, không phải đồng hồ) và chỉ nhận phản hồi không cũ hơn ở **mọi ô**; không thì giữ nguyên phản hồi cũ và
nói rõ bản sao nào trễ bao nhiêu. Không trộn số của hai bản sao: màn hình luôn là đúng một phản hồi.

Đo ngày 22/11/2026 (3 node một máy, lấy mẫu mỗi giây trong 32 giây): 6 lần B trả lời bị giữ số cũ, nhãn "Bản sao B
trễ 5 sự kiện ở CN2"; **0 lần** ô CN2 lùi phiên bản trên màn hình; gossip vá B sau ~22 giây, nhãn tự mất. Chạy lại K4
cũng thấy "Bản sao C trễ 8 ô ở CN2" vài giây, 0 lần lùi.

### K12. Truy vết một sự kiện qua chi nhánh, broker, từng bản sao

Mở dashboard qua nginx (mở thẳng một bản sao thì chỉ có dòng của bản sao đó, không hỏi được chi nhánh).

**Làm:** bán 1 đơn ở CN2, rồi mở tab **Sự kiện** và bấm dòng của nó trong bảng bên trái (hoặc Tab tới dòng rồi
Enter; dòng đang chọn tô xanh nhạt). "Làm mới" hỏi lại; "Đóng" bỏ chọn.

**Thấy** (khung "CN2 #N", mỗi bước một dòng; mốc đầu là giờ chi nhánh ghi, các mốc sau là "+x,xx giây" tính từ mốc
đó, rê chuột để xem giờ đầy đủ đến mili giây; chấm xanh = bình thường, vàng = vá, đỏ = chưa nhận / mất liên lạc,
xám = bỏ qua hoặc chưa rõ):
1. **CN2 ghi sổ**: sổ cái và outbox cùng một transaction, giờ chi nhánh.
2. **Vào Redpanda**: broker leader ghi vào phân hoạch p, offset o; timestamp Kafka (topic `LogAppendTime`), giờ broker.
3. **CN2 xác nhận đã gửi**: relay nhận xác nhận của cụm, đánh dấu `outbox.sent_at`, giờ chi nhánh. Mốc này luôn sau
   mốc 2: broker ghi rồi mới xác nhận, relay nhận xác nhận rồi mới đánh dấu (PT-03). Mở thẳng một bản sao thì không
   có bước này.
4. **Bản sao A, B, C**: "+x giây" (nhận qua Redpanda), hoặc vàng "vá bằng gossip / đối soát tới #N, không qua
   Redpanda", hoặc xám "bỏ qua: đã có #N mới hơn, số tồn vẫn đúng", hoặc đỏ "chưa nhận" / "mất liên lạc".

Biến thể:
- **Sau K8**: bấm một sự kiện B đã bỏ qua (hiện khi A hoặc C trả lời): dòng B vàng "vá bằng gossip tới #N", A và C
  xanh. Đo ngày 26/11 (dừng sink B, bán 1 đơn): A +1,96 giây, C +1,50 giây, B vàng +12,34 giây "vá bằng gossip".
- **Sau K9 / K7b** (khi đã bật lại broker): bấm một sự kiện có số vàng ở cột "Trễ" bán trong lúc mất đa
  số: mốc "Vào Redpanda" sau lúc bật lại broker, mỗi bản sao xanh kèm ghi chú "đã vá trước bằng đối soát lúc …".

**Nói:** Ba kênh hiện ra trên cùng một sự kiện. Redpanda là đường nhanh: bình thường cả ba bản sao nhận trong vài
chục mili giây sau khi broker ghi. Khi đường nhanh hỏng, số tồn vẫn tới bằng gossip hoặc đối soát, nhưng chỉ là số mới
nhất của ô, không có nhật ký từng lượt. Ba loại mốc theo ba đồng hồ khác nhau, chỉ để hiển thị; thứ tự dựa vào
`movement_id`.

Đo ngày 22/11/2026 (3 node một máy):
- CN2 #22: chi nhánh ghi 13:45:16,160; broker ghi 13:45:17,603 (phân hoạch 1, offset 22); `sent_at` 13:45:17,605;
  A, B, C nhận 13:45:17,606–693 (1,4–1,5 giây sau khi chi nhánh ghi, phần lớn là chu kỳ đọc outbox của relay).
- Sau K8: CN2 #24, dòng B "ô được vá bằng gossip lúc 13:46:15,147, tới #24", A, C nhận qua Redpanda 13:45:57,68.
- Sau K7b: CN2 #79 bán 13:53:03 khi mất đa số; ô đã vá bằng đối soát 13:53:11–19 ở cả ba bản sao; broker ghi
  13:54:05 (bật lại 13:53:56); bản sao nhận 13:54:50–57. Khoảng ~50 giây giữa broker ghi và sink đọc chính là độ chậm
  "sink đọc tiếp sau ~55 giây" ở `docs/plan.md` mục 6, giờ nhìn thấy được trên giao diện.

### K13. Mất cổng vào: trang tự chuyển cổng

Mở sẵn: dashboard qua cổng A `http://localhost/` (máy thật `http://<IP máy A>/`), thanh bên ô **Cổng vào** ghi
"localhost (1/3)"; POS CN2 qua cổng A `http://localhost/cn2/`.

**Làm:**
1. `make kill N=a S=nginx` (máy thật: rút mạng máy A, hoặc `docker compose stop nginx` trên máy A).
2. Trên POS: thêm một mặt hàng vào phiếu, **trước khi bấm Thanh toán** chạy `make start N=a S=nginx` rồi
   `make pause N=a S=nginx` (cổng treo: nhận kết nối mà không trả lời), bấm **Thanh toán**, đợi thông báo, bấm
   **Thanh toán** lần nữa. Cuối cùng `make unpause N=a S=nginx`.
3. Mở tab mới `http://localhost/` khi nginx A đang chết.

**Thấy:**
- Dashboard: ngay lần làm mới kế tiếp, ô Cổng vào đổi thành "localhost:8012 (2/3), cổng localhost không trả lời, đã
  chuyển"; dòng "cập nhật HH:MM:SS · bản sao X" vẫn chạy mỗi 2 giây, vệt served-by vẫn `A B C`, bảng bản sao đủ 3 dòng.
  Cổng treo (pause) thì chậm hơn: chờ hết 4 giây rồi mới chuyển.
- POS: lượt bán gửi vào cổng treo báo "Chưa rõ đã ghi chưa (mất kết nối)", dòng bị khoá, giữ `request_id`; trang đã
  chuyển sang cổng 8012. Bấm lại thì "Đã bán 1 mặt hàng". Tồn giảm **đúng 1**, sổ cái có đúng một dòng với
  `request_id` đó, kể cả khi yêu cầu kẹt trong nginx A được thả ra sau `unpause` (PT-08).
- Tab mới mở `http://localhost/` báo không kết nối được: trang chưa mở thì không có danh sách cổng, phải tự gõ
  `localhost:8012`.
- Không tự quay về cổng A khi A sống lại (tránh chuyển qua chuyển lại); tải lại trang thì về cổng đã gõ.

**Nói:** Giống `bootstrap.servers` của Kafka: client biết nhiều địa chỉ và tự thử lần lượt, không cần VIP hay
keepalived (không chạy được trên Docker Desktop Windows). Ba nginx cấu hình giống hệt nhau nên cổng nào cũng thấy cả
hệ. Giới hạn: chỉ trang ĐANG MỞ mới tự chuyển; production dùng một tên DNS trỏ nhiều địa chỉ (`docs/spec.md` mục 6).
Một máy: không dùng `make cut N=a`, vì cổng host không đi qua `minigo-wan`, trình duyệt cùng máy vẫn tới nginx A.

Đo ngày 27/11/2026 (3 node một máy, Edge headless điều khiển qua DevTools): kill nginx A thì chuyển sang 8012 sau
2,7 giây, các lần làm mới sau đều được; pause thì chuyển sau ~6 giây (4 giây chờ + chu kỳ 2 giây). POS qua cổng treo:
tồn mã 3 ở CN2 141 → 140, một dòng sổ cái cho `request_id`.

### K14. Chậm hay chết: kết luận theo đa số bản sao

Mở sẵn: dashboard qua cổng vào, tab **Hệ thống**, bảng kỹ thuật chi nhánh (cột "Góc nhìn từng bản sao", "Kết luận
(đa số)"); tab Tổng quan (bảng chi nhánh, dải sự cố). Theo dõi bằng lệnh:
`curl -s localhost:8000/api/nodes` (mỗi chi nhánh có `state`, `views`, `verdict`).

**Làm:**
1. `make pause N=b S=branch_api` (chậm: tiến trình còn đó nhưng không gửi heartbeat). Chờ 20 giây.
   `make unpause N=b S=branch_api`.
2. `make kill N=b S=branch_api` (chết). Chờ 20 giây. `make start N=b S=branch_api`.
3. Biến thể: `docker exec minigo-b-branch_api-1 sh tre.sh on 0 replica-a 100` (mất 100% gói từ CN2 tới riêng bản
   sao A). Chờ 20 giây. `... sh tre.sh off`.

**Thấy:**
- Bước 1 và 2 giống hệt nhau: góc nhìn từng bản sao "sống" → "nghi ngờ" (heartbeat cũ từ 8 giây) → "mất" (từ 15
  giây); kết luận đa số đi theo, chậm hơn vài giây vì góc nhìn được kéo mỗi 5 giây. Thẻ CN2 "Nghi ngờ, chưa đủ đa
  số" rồi "Mất liên lạc … (3/3 bản sao)", dải sự cố "CN2 mất liên lạc (3/3 bản sao)", ô "Chi nhánh hoạt động" 2/3.
  Bật lại thì về "Hoạt động" trong vài giây. `docker kill` không bị `restart: unless-stopped` tự bật lại.
- Biến thể: chỉ góc nhìn của A về CN2 đi "nghi ngờ" rồi "mất"; B, C vẫn "sống"; **kết luận vẫn "sống" ở cả ba bản
  sao**, kể cả dashboard mở thẳng bản sao A (`localhost:8000`). POS CN2 có chip "Bản sao máy A: mất liên lạc".

**Nói:** Timeout không phân biệt được chậm với chết (mô hình bất đồng bộ, không đặt được giới hạn trên cho độ trễ).
Vì vậy mỗi bản sao chỉ **nghi ngờ** theo góc nhìn của mình, và hệ chỉ **kết luận** OFFLINE khi đa số bản sao, tính
trên tổng số bản sao cấu hình, cùng thấy OFFLINE (PT-13): một đường mạng hỏng riêng lẻ không làm cả hệ coi chi nhánh
là chết, và bản sao bị cô lập (K3) không tự kết luận được. MiniGo không có HQ điều phối như repo tham khảo cùng môn;
kết luận rút ra từ các bản sao ngang hàng. Vòng 6 (ghi hộ) chỉ chạy khi kết luận này là OFFLINE.

Đo ngày 27/11/2026 (3 node một máy, lấy mẫu `/api/nodes` mỗi giây, mốc 0 = lúc chạy lệnh): pause: góc nhìn SUSPECT ở
giây 6–10, OFFLINE ở 13–17; kết luận SUSPECT ở 7–10, OFFLINE ở 13–17 (cả 3 bản sao đồng ý ở giây 17); unpause:
ONLINE ở cả 3 sau ≤ 4 giây. kill: góc nhìn SUSPECT ở giây 3–7, OFFLINE ở 10; kết luận OFFLINE ở 11–14; container
`Exited (137)`, không tự bật lại; start: ONLINE ở cả 3 sau ≤ 6 giây. Biến thể: A thấy SUSPECT ở giây 5, OFFLINE ở 11,
B, C ghi nhận góc nhìn đó sau ≤ 5 giây; kết luận ONLINE suốt 30 giây ở cả 3; `tre.sh off` thì góc nhìn A về ONLINE
sau ~6 giây.

Từ vòng 6, sau `unpause` và sau `start` chi nhánh ở **RECOVERING** vài giây dù không có ghi hộ (đa số còn kết luận
OFFLINE, tức còn nhận ghi hộ; chi nhánh chờ tới khi hết, PT-14); POS báo "Chi nhánh đang phục hồi", dashboard ghi
"Đang phục hồi (áp ghi hộ)". Không phải lỗi. Đo 27/11/2026 (3 node một máy, lấy mẫu `/api/status` mỗi 0,5 giây, mốc 0
= lúc chạy lệnh): `unpause`: RECOVERING ngay, ONLINE ở giây 5,0; `start` sau `kill`: RECOVERING ở giây 1,3, ONLINE ở
giây 5,6. Pause, kill: kết luận SUSPECT ở giây 8–9, OFFLINE ở giây 16–17 như vòng 5.

### K15. Chi nhánh sập vẫn bán: ghi hộ (hinted handoff)

Mở sẵn: POS CN2 **qua cổng vào** `http://localhost/cn2/` (POS mở thẳng `:8011` thì chi nhánh chết là mất trang);
dashboard `http://localhost/`, tab Tổng quan (bảng chi nhánh có cột "Ghi hộ", dải sự cố). Theo dõi bằng lệnh:
`curl -s localhost:8011/api/status` (trường `recovery`), `curl -s "localhost/replica/A/api/handoff?branch_id=2"`.

**Làm:**
1. `make kill N=b S=branch_api`, `make kill N=b S=branch_db` (server chi nhánh sập; relay B vẫn chạy).
2. Chờ POS chuyển sang ghi hộ (khoảng 15–20 giây), bán 5 đơn (5 lần Thanh toán).
3. (Tuỳ chọn) Tải lại trang POS: vẫn mở được, nginx trả trang từ `@pos_page`.
4. `make start N=b S=branch_db`, chờ `docker inspect -f {{.State.Health.Status}} minigo-b-branch_db-1` ra `healthy`,
   rồi `make start N=b S=branch_api`.
5. Gửi lại lần hai (giả lập ack bị mất): đặt lại các lượt ở bản sao A về PENDING:
   `docker exec minigo-a-replica_db-1 psql -U app -d kho -c "UPDATE handoff SET status='PENDING', movement_id=NULL, decided_at=NULL WHERE branch_id=2"`.
   Chi nhánh kéo lại, áp lại: tồn và số dòng sổ cái không đổi.

**Thấy:**
- POS: ngay sau khi dừng, dải đỏ "Không gọi được chi nhánh. Trung tâm: vẫn thấy chi nhánh sống / nghi ngờ, chưa đủ đa
  số. Chưa ghi hộ", nút Thanh toán bị khoá. Khi đa số kết luận OFFLINE: dải vàng "Đang ghi hộ qua trung tâm (bản sao
  A): n lượt chờ chi nhánh áp lại. Tồn hiển thị là tồn tạm tính; chỉ bán, không nhập"; nút Nhập hàng và Bán 20 đơn bị
  khoá; mỗi lần Thanh toán ghi "Đã ghi hộ … qua bản sao A".
- Dashboard: CN2 "Mất liên lạc … (3/3 bản sao)", cột Ghi hộ "chờ 5 · đã áp 0 · từ chối 0", dải sự cố "CN2: 5 lượt ghi
  hộ chờ chi nhánh áp".
- Bật lại: POS "Chi nhánh đang phục hồi: đã áp 5 lượt ghi hộ, từ chối 0, còn 0 chờ. Chưa nhận bán mới", rồi về bán tại
  chỗ; dashboard CN2 "Đang phục hồi (áp ghi hộ)" rồi "Hoạt động", cột Ghi hộ "đã áp 5". Tồn 5 mã giảm đúng số đã ghi
  hộ, 5 dòng sổ cái mang đúng 5 `request_id`; 3 dấu vân tay khớp.
- Bước 5: chi nhánh RECOVERING khoảng 2 giây rồi ONLINE; tồn, số dòng sổ cái không đổi (PT-08, PT-14).

**Biến thể REJECTED** (lượt ghi hộ vượt tồn thật): `make kill N=b S=relay` trước bước 1, rồi bán tại quầy
(`localhost:8011`) cho một mã còn 2; trung tâm vẫn thấy số cũ vì relay dừng. Dừng `branch_api`, `branch_db`; ở POS
qua cổng vào ghi hộ 10 cái mã đó (tồn tạm tính đủ nên bản sao nhận). Bật `relay`, `branch_db`, `branch_api`. Thấy:
lượt đó REJECTED; POS có dải đỏ "Lượt ghi hộ bị TỪ CHỐI khi chi nhánh áp lại: … ×10 (tồn thật chỉ còn 2, lúc …)";
dashboard cột Ghi hộ "từ chối 1"; tồn mã đó vẫn 2.

**Biến thể hai nơi cùng ghi** (bằng chứng cho giới hạn ở `docs/spec.md` mục 6): `make kill N=b S=nginx` (một máy:
để trình duyệt không vòng qua cổng 8012 của chính máy B; máy thật rút mạng máy B là mất luôn cổng đó), `make cut N=b`.
POS qua cổng A vào ghi hộ; quầy mở thẳng `localhost:8011` vẫn bán (chi nhánh ONLINE, không gọi được A, C). Bán tại
quầy cho một mã còn 1, rồi ở POS cổng A ghi hộ 3 cái mã đó (trung tâm vẫn thấy số cũ). `make heal N=b`,
`make start N=b S=nginx`. Thấy: chi nhánh vào RECOVERING, lượt thừa thành REJECTED, rồi ONLINE; 3 dấu vân tay khớp.

**Nói:** Server chi nhánh là nơi duy nhất giữ bản chính của tồn, nên khi nó sập, trung tâm **giữ hộ** lượt bán
(store-and-forward, hinted handoff như Dynamo) chứ không ghi thay. Chỉ ghi hộ khi **đa số** bản sao kết luận OFFLINE
(PT-13), và chính bản sao nhận cũng kiểm lại. Chi nhánh sống lại thì **tự kéo** về (bản sao không ghi vào CSDL chi
nhánh, PT-07), áp qua đúng đường bán hàng (`request_id` chống trừ hai lần), theo thứ tự `handoff_id` do bản sao cấp
(không dựa vào đồng hồ); chưa áp xong thì chưa bán mới (PT-14). Đổi lại là chọn A trong CAP: tồn tạm tính có thể sai
(snapshot thiếu lượt chưa kịp gửi, mạng chia cắt làm hai nơi cùng ghi), chỉ phát hiện lúc áp lại; lượt thừa thành
REJECTED và hiện ra, không mất lặng lẽ. Cách triệt để là lease kèm fencing token (kiến trúc mục tiêu, vòng 7).

Đo ngày 27/11/2026 (3 node một máy, Edge headless điều khiển qua DevTools): POS chuyển "chờ" sau ~4 giây, "ghi hộ" sau
17 giây kể từ lúc dừng; 5 đơn ghi hộ ở bản sao A; bật lại: RECOVERING sau 1,3 giây, áp đủ 5 lượt, ONLINE sau 5,3 giây
(tính từ `make start` `branch_api`); tồn 5 mã giảm đúng 2, 5 dòng sổ cái; gửi lại lần hai: RECOVERING ~2 giây, tồn
không đổi, vẫn 5 dòng; 3 dấu vân tay khớp. Biến thể REJECTED: mã 11 tồn thật 2, ghi hộ 10 thì REJECTED, lượt kèm theo
(mã 8) vẫn áp; tồn mã 11 vẫn 2. Biến thể hai nơi cùng ghi: POS cổng A ghi hộ sau 15 giây kể từ `cut`; sau `heal`, chi
nhánh RECOVERING ở giây 4, lượt thừa REJECTED, ONLINE ở giây 8,4; 3 dấu vân tay khớp.

## 6. Câu hỏi thường gặp khi bảo vệ

| Câu hỏi | Từ khoá | Trả lời ngắn |
|---|---|---|
| Mất mạng giữa chừng thì sao? | Lỗi cục bộ, outbox | Quầy vẫn bán: sự kiện ghi vào `outbox` cùng transaction với trừ tồn, relay gửi bù khi có mạng. |
| Làm sao biết dữ liệu hai nơi giống nhau? | Nhất quán cuối, dấu vân tay | Có mạng lại thì tự đồng bộ bù; so mã băm toàn bộ snapshot giữa các bản sao. |
| Gửi lặp hai lần có trừ tồn hai lần không? | Lũy đẳng | Bản sao dùng khoá `(branch_id, movement_id)`; thấy rồi thì bỏ qua. Chi nhánh dùng `request_id`. |
| Sao người dùng không cần biết IP từng máy? | Trong suốt vị trí | Nginx là cổng vào, tự chọn bản sao và chia tải; ba nginx giống hệt nhau nên vào máy nào cũng thấy cả hệ. |
| Hệ có HA không? Còn điểm chết duy nhất nào? | Sẵn sàng cao, failover phía client, bộ phát hiện lỗi, đa số (quorum) | Bỏ được ở các tầng: broker là cụm 3 (K7a), bản sao trung tâm có 3 và nginx chia tải (K3), **cổng vào** có 3 nginx, trang đang mở tự chuyển cổng như `bootstrap.servers` của Kafka (K13). Phát hiện chi nhánh chết bằng timeout nên không phân biệt chậm với chết (K14); để không kết luận sai khi chỉ một bản sao mất liên lạc, chỉ coi OFFLINE khi **đa số 2/3 bản sao** cùng thấy (PT-13), bản sao bị cô lập chỉ "nghi ngờ". Còn lại: dữ liệu mỗi chi nhánh chỉ một bản chính (server chi nhánh chết thì quầy bán tiếp bằng ghi hộ qua trung tâm, K15; vòng 7 standby CSDL); trang mở mới khi cổng quen thuộc đã chết phải tự gõ cổng khác (production: DNS nhiều địa chỉ hoặc VIP). Một máy vẫn là một miền lỗi. |
| Chi nhánh sập thì sao? | Ghi hộ (hinted handoff, store-and-forward), RECOVERING, chọn A trong CAP | Quầy mở qua cổng vào vẫn bán (K15): đa số bản sao kết luận OFFLINE thì POS gửi lượt bán lên **một** bản sao, bản sao kiểm "tồn tạm tính" và giữ hộ. Chi nhánh bật lại ở RECOVERING, **tự kéo** ghi hộ về (bản sao không ghi vào CSDL chi nhánh), áp đúng một lần nhờ `request_id`, theo `handoff_id` (không dựa vào đồng hồ), xong mới bán mới (PT-14). Lượt không đủ tồn thật thành REJECTED và hiện trên POS, dashboard. Giá phải trả: mạng chia cắt thì hai nơi cùng ghi, có thể bán quá tồn, chỉ biết lúc áp lại; cách triệt để là lease kèm fencing token. |
| Trung tâm sập thì cửa hàng có sập không? | Tách rời qua broker | Chi nhánh và trung tâm nói chuyện qua Redpanda, không cần chạy cùng lúc. |
| Redpanda gặp sự cố thì xử lý thế nào? | Phòng, chống, phục hồi | **Phòng**: cụm 3 broker, RF=3, mất 1 broker tự bầu leader mới (K7a). **Chống**: mất đa số thì quầy vẫn bán, outbox giữ sự kiện, POS và dashboard báo "đồng bộ dừng từ HH:MM:SS" (K7b). Mất đa số quá 15 giây thì bản sao **đối soát thẳng với chi nhánh** qua API (chỉ đọc), số tồn vẫn đúng (K9). **Phục hồi**: có lại đa số thì relay gửi bù, sink đọc tiếp từ offset, không ai làm gì (K7b, K7c). Mất hẳn dữ liệu broker: số tồn dựng lại từ bản sao khác (gossip, K8) hoặc từ chi nhánh (đối soát, K9); chỉ mất nhật ký các sự kiện chưa kịp đọc. Redpanda là đường nhanh, không phải nguồn sự thật: nguồn sự thật là sổ cái chi nhánh. |
| ReplicaA và ReplicaB trao đổi thông tin bằng cơ chế gì? | Nhân bản máy trạng thái qua log chung; gossip (anti-entropy); CRDT theo từng ô | Ba kênh, một luật merge. (1) Gián tiếp: cùng đọc một log trên Redpanda (mỗi bên một consumer group), áp lũy đẳng nên ra cùng trạng thái. (2) Trực tiếp: mỗi 10 giây gọi `/api/digest` của nhau; dấu vân tay lệch ở 2 lần kiểm liên tiếp thì kéo `/api/snapshot` và vá ô còn thiếu (K8). (3) Mất broker thì mỗi bên đọc thẳng chi nhánh (K9). Luật "`movement_id` lớn hơn thắng" theo từng ô giao hoán, lũy đẳng, nên đến từ kênh nào, theo thứ tự nào cũng hội tụ (PT-10). |
| Qua nginx, lần làm mới sau rơi vào bản sao trễ thì số có lùi không? | Đọc đơn điệu (monotonic reads), nhất quán lấy client làm trung tâm | Không (K11). Tab dashboard nhớ phiên bản (`movement_id`) từng ô đã hiện, chỉ nhận phản hồi không cũ hơn ở mọi ô; bản sao trễ thì giữ nguyên số cũ và ghi "Bản sao B trễ N sự kiện ở CN2". Bảo đảm trong một lần mở trang; không cần chờ mọi bản sao đồng bộ (vẫn là nhất quán cuối giữa các bản sao). |
| Gossip có làm sai số khi sink đang chạy bình thường không? | Lũy đẳng, chờ kênh chính | Không: chỉ vá ô thiếu ở 2 lần kiểm cách nhau 10 giây, và chỉ ghi đè khi `movement_id` mới hơn. Bán liên tục (K1) thì "vá 0 ô". Sự kiện tới sau khi ô đã được vá vẫn vào nhật ký nhưng không đổi số. |

## 7. Bảng nghiệm thu chạy liên máy

| Yêu cầu | Đạt khi | Kiểm ở đâu |
|---|---|---|
| Chạy trên ≥ 2 máy thật, nối bằng overlay | Hai máy thấy nhau qua IP `100.x` (Tailscale), cả hai chạy đủ container | `tailscale status`, `ping`, `docker compose ps` |
| Trong suốt vị trí (Nginx, một IP) | Mở `http://<IP máy A>/` thấy vệt `A B A B`; `/cn2/` mở được POS máy B | Dashboard qua Nginx, `curl -I` |
| Chịu lỗi & Failover | Rút mạng B: Dashboard Nginx không báo lỗi, vệt chỉ còn `A`, POS B vẫn bán bình thường | Dashboard A, POS B |
| Tự phục hồi (Eventual Consistency) | Cắm lại mạng: outbox về 0 trong ≤ 30s, dấu vân tay A và B khớp trong ≤ 60s | Bảng bản sao, POS B |
| Đồng bộ dữ liệu real-time | Bán ở B, Dashboard A đổi trong ≤ 3s; A và B cùng dấu vân tay (Fingerprint) | Dashboard A |
| Độ trễ mạng (RTT) | Bật Clumsy trễ 300ms: RTT ≥ 500ms nhưng POS vẫn "xử lý tại chỗ" < 20ms | Chip RTT trên POS B, thẻ CN2 |
| Chống trùng (Idempotency) | Phát lại toàn bộ sự kiện: số bản trùng tăng vọt, dấu vân tay không đổi | Tab `http://localhost:8000` |
| Cổng vào không còn điểm chết (K13) | Dashboard, POS đang mở qua máy A; tắt nginx (hoặc rút mạng) máy A: trang tự chuyển sang cổng máy B, vẫn làm mới, lượt bán gửi lại không trừ hai lần | Ô "Cổng vào" ở thanh bên, POS |
| Chi nhánh sập vẫn bán (K15) | Dừng server chi nhánh B: POS qua cổng vào ghi hộ; bật lại: RECOVERING, áp đủ, rồi bán tại chỗ; 3 dấu vân tay khớp; lượt vượt tồn thật REJECTED và hiện ra | POS qua cổng vào, bảng chi nhánh cột Ghi hộ |
| Phát hiện lỗi theo đa số (K14) | Dừng/tạm dừng chi nhánh B: 3 bản sao đi Nghi ngờ rồi Mất liên lạc; chỉ một bản sao mất liên lạc thì kết luận vẫn "sống" | Tab Hệ thống, bảng kỹ thuật chi nhánh |
| Chịu lỗi broker (cần 3 máy) | Dừng 1/3 broker: không mất sự kiện, dấu vân tay khớp. Dừng 2/3 rồi bật lại: POS và dashboard báo "đồng bộ dừng", sau đó tự khớp không thao tác tay | POS, dòng "Đồng bộ" trên dashboard, Console |
| Gossip giữa bản sao (K8) | Bản sao lỡ sự kiện khớp lại trong ≤ 20 giây, cột Gossip "vá N ô"; bán bình thường thì "vá 0 ô" | Bảng bản sao qua nginx, dashboard B |
| Đối soát với chi nhánh (K9) | Dừng cả 3 broker, bán: sau 15–25 giây 3 bản sao khớp, ô có chấm cam "đối soát" | Dòng "Đồng bộ", bảng tồn |

## 8. Lỗi hay gặp

| Triệu chứng | Nguyên nhân | Cách xử lý |
|---|---|---|
| `Chưa đặt ... trong .env` | Chưa copy file env thành `.env` | Mục 2 |
| Máy A không có redpanda, console, nginx | Profile chưa bật | `COMPOSE_PROFILES=core,broker` (máy A), `broker` (máy B, C) |
| Relay, sink lỗi mãi; log redpanda `Error requesting cluster bootstrap info` | Cụm chưa đủ 3 broker (cụm chỉ lập khi đủ mọi seed) | Bật broker các máy còn lại; mở cổng 33145; kiểm tra `BROKER_SEEDS` giống nhau ở mọi máy |
| Relay báo `Message timed out` | Không tới được broker leader | `ping` máy đó; mở cổng 19092; kiểm tra `KAFKA_BROKERS` |
| Relay nối được rồi lỗi, log nhắc địa chỉ lạ | `BROKER_HOST` của một máy sai nên broker đó tự giới thiệu sai địa chỉ | `BROKER_HOST` = IP overlay của chính máy đó; sửa rồi `docker compose up -d` |
| Redpanda lỗi khởi động sau khi lên vòng 2 | Volume broker cũ (một broker) | `make reset` trên mọi máy (một máy: `make local-reset`) |
| Một máy: `docker start minigo-x-redpanda-1` hoặc `make heal` báo `Address already in use` | Mạng `minigo-wan` tạo từ bản trước vòng 5 (chưa có IP cố định, vùng động riêng) | `make local-reset` một lần |
| Một máy: `make local-up` báo "Mạng minigo-wan tạo từ bản trước vòng 5" | Mạng cũ chưa tách vùng IP động | `make local-reset` một lần (xoá dữ liệu demo) |
| Dashboard ghi "Cổng vào: chỉ cổng này" dù mở qua nginx | Trang không đọc được `/lb/gateways.json` (nginx cũ, thiếu `GATEWAYS`) | Chép lại `.env` từ `infra/env/may-<x>.env`, `make up` |
| Bảng bản sao dòng B luôn "Không liên lạc được" | Nginx không tới được `REPLICA_B` | Mở firewall máy B cổng 8000; từ máy A: `curl http://<IP máy B>:8000/health` |
| Không có ô "Các bản sao trung tâm" | Đang mở dashboard trực tiếp ở cổng 8000, không qua nginx | Mở `http://localhost/` (cổng 80) |
| Cổng 80 bị chiếm (Windows hay gặp) | IIS hoặc ứng dụng khác | Thêm `NGINX_PORT=8088` vào `.env`, mở `http://localhost:8088/` |
| Nginx lỗi khởi động, báo `Chưa đặt REPLICA_C` hoặc `Chưa đặt GATEWAYS` | File `.env` cũ, chưa có khối `REPLICA_*`, `BRANCH_*`, `GATEWAYS` | Chép lại từ `infra/env/may-<x>.env` |
| Log nginx có `replica-b could not be resolved` | Node B chưa chạy hoặc đang bị `make cut`; nginx vẫn chạy (phân giải động), đường tới B trả 502 | Không cần làm gì: node B có lại thì trong ≤ 5 giây nginx tự phân giải lại |
| Cột Gossip ghi "lỗi từ …" với một bản sao; mất broker mà không thấy "đang đối soát" | Bản sao không gọi được bản sao kia (`REPLICA_URLS`, cổng 8000) hoặc chi nhánh (`BRANCH_URL`, cổng 8001) | `curl http://<IP>:8000/api/digest`, `curl http://<IP>:8001/api/snapshot` từ máy đó; kiểm `BRANCH_URL` = IP overlay của chính máy chi nhánh; xem `sync_peers` trong `/api/digest` (trường `last_error`) |
| Sửa `db/*.sql` không thấy tác dụng | Script khởi tạo chỉ chạy khi volume trống | `make reset` trên **mọi máy** |

**Làm lại từ đầu:** chạy `make reset` trên **tất cả** các máy (cụm broker chờ đủ 3 máy rồi mới lập).

## 9. Lệnh hay dùng

Lệnh make (chạy từ gốc repo, trong Git Bash hoặc shell Linux/macOS; định nghĩa ở `Makefile`):

| Lệnh | Việc làm |
|---|---|
| `make up` | Dựng và chạy mọi container của máy này |
| `make down` | Dừng, giữ dữ liệu |
| `make reset` | Xoá dữ liệu rồi dựng lại; chạy trên MỌI máy |
| `make ps` | Liệt kê container |
| `make logs` | Log, mặc định 100 dòng cuối mọi service. `S=relay` chọn service, `N=200` đổi số dòng |
| `make test` | pytest trong container trên CSDL test. `T=tests/replica` chạy một thư mục |
| `make config` | Kiểm tra file compose với env mẫu (máy thật và 3 node một máy), không chạy container |
| `make check` | `config` + `test`; chạy trước khi báo xong một vòng |
| `make local-up`, `local-down`, `local-reset` | 3 node trên một máy (mục 3, phần "Chạy trên một máy") |
| `make cut N=b`, `make heal N=b` | Một máy: rút / cắm lại mạng node B |
| `make pause N=b S=branch_api`, `make unpause N=b S=branch_api` | Một máy: tạm dừng / chạy tiếp một container (`docker pause`: "chậm", vẫn sống), K13, K14 |
| `make kill N=b S=branch_api`, `make start N=b S=branch_api` | Một máy: giết (`docker kill`: "chết") / bật lại một container, K13, K14 |

Các lệnh `up`, `down`, `reset`, `ps`, `logs` đọc `.env` ở gốc repo; dùng file khác: `make up ENV_FILE=infra/env/may-b.env`.

```bash
docker compose ps                         # container nào đang chạy
docker compose logs -f relay              # relay gửi được không
docker compose logs -f sink               # sink đang áp sự kiện nào
docker compose exec redpanda rpk cluster health                # cụm broker: Healthy, Nodes down
docker compose exec redpanda rpk topic describe inventory.movement -p   # leader từng phân hoạch
docker compose exec redpanda rpk group list                    # các consumer group
docker compose exec redpanda rpk group describe replica-B      # bản sao B còn thiếu bao nhiêu (cột LAG)
curl -I http://localhost/api/stats        # (máy A) bản sao nào trả lời
docker compose exec branch_db psql -U app -d kho -c "SELECT branch_id, count(*) FROM inventory GROUP BY 1;"
```

Tài liệu API tự sinh: `http://localhost:8001/docs` (chi nhánh), `http://localhost:8000/docs` (bản sao).
