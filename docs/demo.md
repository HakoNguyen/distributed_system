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
| A | 80 (nginx), 8000, 8001, 19092, 33145 (Redpanda) | trình duyệt, chi nhánh và broker các máy khác |
| B, C | 8000 (bản sao), 8001 (POS), 19092, 33145 (Redpanda) | nginx ở máy A, heartbeat, relay, sink và broker máy khác |

Trên Windows, mở PowerShell bằng quyền Administrator:

```powershell
# Máy A
New-NetFirewallRule -DisplayName "MiniGo" -Direction Inbound -Protocol TCP -LocalPort 80,8000,8001,19092,33145 -Action Allow
# Máy B, C
New-NetFirewallRule -DisplayName "MiniGo" -Direction Inbound -Protocol TCP -LocalPort 8000,8001,19092,33145 -Action Allow
```

Trên Linux có ufw: `sudo ufw allow 80,8000,8001,19092,33145/tcp`. macOS thường tự hỏi, bấm Allow.

## 2. Điền file env

Mỗi máy có một file mẫu trong `infra/env/`. Mở **cả ba** file `infra/env/may-a.env`, `may-b.env`, `may-c.env`, thay các IP mẫu `100.64.0.1`, `100.64.0.2`, `100.64.0.3` bằng IP overlay thật. Chúng xuất hiện ở các dòng `BROKER_SEEDS`, `KAFKA_BROKERS`, `REPLICA_A/B/C`, `BRANCH_A/B/C`, `REPLICA_URLS`, `BROKER_HOST`, `BRANCH_URL`. Khối `BROKER_SEEDS`, `KAFKA_BROKERS`, `REPLICA_A/B/C`, `BRANCH_A/B/C` phải giống nhau ở mọi file; `BROKER_HOST` là IP overlay của **chính máy đó** (broker tự giới thiệu địa chỉ này cho máy khác); `BRANCH_URL` là `http://<IP overlay chính máy đó>:8001` (chi nhánh gửi kèm heartbeat để bản sao mọi máy đối soát khi mất broker).

`REPLICA_B`, `BRANCH_B`... là địa chỉ đầy đủ `host:port` mà nginx (máy A) dùng để gọi bản sao và POS của từng máy: `100.64.0.2:8000` là bản sao máy B, `100.64.0.2:8001` là POS CN2 (cổng host).

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

Máy A phải thấy **9 container chạy** (redpanda, console, nginx, và 6 container của chi nhánh và bản sao) cộng `topic-init` đã `Exited (0)`; máy B, C mỗi máy **7 container** (thêm redpanda). Nếu thiếu redpanda, console, nginx, kiểm tra dòng `COMPOSE_PROFILES` trong `.env` (`core,broker` ở máy A, `broker` ở máy B, C).

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
POS, bản sao, broker), chỉ mất liên lạc với node khác, đúng như rút dây mạng. RAM: 23 container (3 broker, mỗi broker `--memory=512M`) đo được khoảng 1,23 GB (19/11/2026).
Đã chạy bản một broker (vòng 1)? Chạy `make local-reset` một lần: volume broker cũ là cụm một node.

```bash
make local-up        # tạo minigo-wan, dựng node C, B rồi A (23 container, cộng topic-init chạy một lần)
make cut N=b         # rút mạng node B
make heal N=b        # cắm lại, đúng IP và alias cũ
make local-down      # dừng 3 node, giữ dữ liệu
make local-reset     # xoá dữ liệu 3 node rồi dựng lại
```

| Node | POS | Dashboard bản sao | Riêng node A |
|---|---|---|---|
| A | http://localhost:8001 (CN1) | http://localhost:8000 | nginx http://localhost/, Console http://localhost:8080 |
| B | http://localhost:8011 (CN2) | http://localhost:8010 | |
| C | http://localhost:8021 (CN3) | http://localhost:8020 | |

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
| Xem gossip, đối soát | `curl localhost:8000/api/digest` (trường `sync_peers`) | `curl localhost:8010/api/digest`; log: `docker logs minigo-b-replica_api-1 \| grep gossip` |
| Xem cụm broker | `docker compose exec redpanda rpk cluster health` | `docker exec minigo-a-redpanda-1 rpk cluster health`, `... rpk topic describe inventory.movement -p` |
| Xem container, log | `make ps`, `make logs S=relay` | `docker ps --filter name=minigo-b`, `docker logs -f minigo-b-relay-1` |

**Vì sao gọi nhau bằng `replica-b` mà không bằng `replica_api`?** Compose tự thêm tên service làm alias trên mọi
network, nên trên `minigo-wan` tên `replica_api` trỏ về cả ba node. Mỗi node có alias riêng (`branch-b`,
`replica-b`, `redpanda-a`), gắn trên cả mạng riêng của node lẫn `minigo-wan`: lúc B bị rút mạng, CN2 vẫn gửi
heartbeat được cho bản sao B.

**Vì sao `heal` phải nối lại đúng IP cũ?** Nginx phân giải tên `replica-b` một lần lúc khởi động rồi nhớ IP. Cắm
lại mà IP đổi thì nginx gửi nhầm container. Broker cũng cần: kết nối RPC nó mở trước lúc rút mạng gắn với IP cũ,
IP đổi thì broker đó không gọi được broker khác nữa (thử ở vòng 2: K7a sau đó hỏng). `make cut` ghi IP và alias vào `.cut-<x>` ở gốc repo, `make heal` đọc lại.

Giới hạn của bản mô phỏng:
- Nginx (node A) chỉ khởi động được khi `replica-b`, `branch-c`... đều phân giải được, nên `make local-up` dựng C,
  B trước A. Nếu nginx khởi động lại lúc một node đang bị rút mạng, nó báo `host not found in upstream`: `make heal`
  rồi `docker restart minigo-a-nginx-1`.
- Trong lúc B bị rút mạng, đừng dựng lại container nào khác (`make local-up`): container mới có thể lấy IP cũ của
  B, `make heal` sẽ báo lỗi. Khi đó `make local-reset`.
- Sau `heal`, nếu một container khác khởi động lại trong lúc broker đang tắt, nó có thể lấy IP đã ghim của broker;
  `docker start` broker đó báo `Address already in use`. Khi đó `make local-reset`.
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

## 5. Kịch bản K1–K9, K11, K12

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

**Nói:** Người dùng chỉ biết **một địa chỉ**. Họ không biết, và không cần biết, phía sau có mấy máy, máy nào đang trả lời, CN2 nằm ở đâu. Đó là tính trong suốt vị trí. Nginx ở đây vừa là **bộ cân bằng tải** vừa là cổng vào duy nhất.

### K3. Chịu lỗi và chuyển đổi khi lỗi: rút mạng máy B

**Làm:** Tắt Wi-Fi (hoặc rút dây mạng) máy B. Trên POS máy B, bấm **Bán 20 đơn ngẫu nhiên** (mục Công cụ demo). Chờ khoảng 20 giây.

**Thấy trên dashboard máy A (qua nginx):**
- Dashboard **vẫn chạy bình thường**. Vệt served-by chỉ còn `A A A`: nginx phát hiện bản sao B không trả lời và tự chuyển hết sang A. Thỉnh thoảng một lần làm mới chậm khoảng 1 giây, vì nginx chờ B 1 giây rồi mới bỏ cuộc và thử lại (xem `proxy_connect_timeout` trong `infra/nginx/default.conf.template`).
- Ô bản sao: dòng B ghi **Không liên lạc được**.
- Sau 15 giây, thẻ CN2 tô sọc đỏ "Mất liên lạc … giây", cột CN2 chuyển xám nghiêng kèm nhãn "số cũ". CN1 vẫn chạy bình thường.
- Mở `http://localhost/cn2/`: trang báo rõ "Không liên lạc được với chi nhánh này" thay vì treo.

**Thấy trên máy B:**
- POS **vẫn bán được**. Dải trạng thái chuyển đỏ "Chưa gửi được lên trung tâm từ … giây", số sự kiện chờ trong outbox tăng dần. Chip "Bản sao máy A: mất liên lạc".
- Tab `localhost:8000` (bản sao B) vẫn mở được. Điều thú vị là **bản sao B thấy CN2 còn sống còn CN1 mất liên lạc**, ngược hẳn với bản sao A. B cũng mất broker (broker máy B một mình là thiểu số), nên sau khoảng 15 giây B **đối soát thẳng với CN2** (cùng máy): cột CN2 trên dashboard B có số mới kèm chấm cam "đối soát", trong khi CN1, CN3 đứng ở số cũ. Dashboard A lúc này vẫn thấy CN2 số cũ: hai bên mạng bị chia cắt có hai góc nhìn khác nhau.

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
- Địa chỉ nginx không vào được (cổng vào duy nhất nằm ở máy A, xem `spec.md` mục 6).
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

## 6. Câu hỏi thường gặp khi bảo vệ

| Câu hỏi | Từ khoá | Trả lời ngắn |
|---|---|---|
| Mất mạng giữa chừng thì sao? | Lỗi cục bộ, outbox | Quầy vẫn bán: sự kiện ghi vào `outbox` cùng transaction với trừ tồn, relay gửi bù khi có mạng. |
| Làm sao biết dữ liệu hai nơi giống nhau? | Nhất quán cuối, dấu vân tay | Có mạng lại thì tự đồng bộ bù; so mã băm toàn bộ snapshot giữa các bản sao. |
| Gửi lặp hai lần có trừ tồn hai lần không? | Lũy đẳng | Bản sao dùng khoá `(branch_id, movement_id)`; thấy rồi thì bỏ qua. Chi nhánh dùng `request_id`. |
| Sao người dùng không cần biết IP từng máy? | Trong suốt vị trí | Nginx là cổng vào duy nhất, tự chọn bản sao và chia tải. |
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
| Một máy: `docker start minigo-x-redpanda-1` báo `Address already in use` | Container khác lấy mất IP đã ghim sau `make heal` | `make local-reset` |
| Bảng bản sao dòng B luôn "Không liên lạc được" | Nginx không tới được `REPLICA_B` | Mở firewall máy B cổng 8000; từ máy A: `curl http://<IP máy B>:8000/health` |
| Không có ô "Các bản sao trung tâm" | Đang mở dashboard trực tiếp ở cổng 8000, không qua nginx | Mở `http://localhost/` (cổng 80) |
| Cổng 80 bị chiếm (Windows hay gặp) | IIS hoặc ứng dụng khác | Thêm `NGINX_PORT=8088` vào `.env`, mở `http://localhost:8088/` |
| Nginx lỗi khởi động, báo `Chưa đặt REPLICA_C` | File `.env` cũ, chưa có khối `REPLICA_*`, `BRANCH_*` | Chép lại từ `infra/env/may-<x>.env` |
| Một máy: nginx báo `host not found in upstream` | Node B hoặc C chưa chạy, hoặc đang bị `make cut` | `make heal N=<x>` hoặc `make local-up`, rồi `docker restart minigo-a-nginx-1` |
| Một máy: `make heal` báo `Address already in use` | Có container mới lấy IP cũ của node đang bị rút mạng | `make local-reset` |
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
