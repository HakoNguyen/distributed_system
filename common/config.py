"""Cấu hình đọc từ biến môi trường. Compose lấy giá trị từ file .env ở gốc repo."""
import os

# "branch" = quầy chi nhánh (api + relay), "replica" = bản sao trung tâm (api + sink).
# api/main.py dựa vào đây để chọn router.
ROLE = os.environ["ROLE"]

# CSDL của CHÍNH tiến trình này: branch_db hoặc replica_db (tên service trong compose)
DATABASE_URL = os.environ["DATABASE_URL"]

# Cụm Redpanda, mỗi máy một broker: liệt kê cả ba "<host>:19092", giống nhau ở mọi máy.
# Topic do service topic-init tạo (infra/compose.yml), relay và sink không tự tạo.
KAFKA_BROKERS = os.environ.get("KAFKA_BROKERS", "")
TOPIC = "inventory.movement"


def _parse_replicas(raw: str) -> list[tuple[str, str]]:
    """'A=http://x:8000,B=http://y:8000' -> [('A','http://x:8000'), ('B','http://y:8000')]"""
    out = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        name, _, url = part.partition("=")
        out.append((name.strip(), url.strip().rstrip("/")))
    return out


# ---------------- Chi nhánh ----------------
BRANCH_ID = int(os.environ["BRANCH_ID"]) if ROLE == "branch" else 0
BRANCH_NAME = os.environ.get("BRANCH_NAME") or f"Chi nhánh {BRANCH_ID}"
# Mọi bản sao trung tâm. Chi nhánh gửi heartbeat tới TẤT CẢ, mỗi bản sao tự
# phán đoán "chi nhánh này còn sống không" theo những gì nó nghe được.
REPLICAS = _parse_replicas(os.environ.get("REPLICA_URLS", ""))
HEARTBEAT_EVERY_S = 5
# Địa chỉ POS của chính chi nhánh này nhìn từ máy khác; gửi kèm heartbeat để bản sao đối soát khi mất broker
BRANCH_URL = os.environ.get("BRANCH_URL") or None
# Sự kiện nằm trong outbox lâu hơn chừng này mà chưa gửi được thì POS báo đỏ
STUCK_AFTER_S = 5

# ---------------- Bản sao trung tâm ----------------
# Tên máy chạy bản sao này: "A", "B", "C". Hiện lên dashboard để biết
# nginx vừa chuyển yêu cầu tới bản sao nào.
NODE_NAME = os.environ.get("NODE_NAME", "?")
# Mỗi bản sao một consumer group riêng -> mỗi bản sao nhận ĐỦ mọi sự kiện
# và tự dựng bảng tổng hợp của riêng nó.
CONSUMER_GROUP = f"replica-{NODE_NAME}"
# Bộ phát hiện lỗi (vòng 5, PT-13), theo tuổi heartbeat (nhịp 5 giây): dưới SUSPECT_AFTER_S là ONLINE,
# từ đó tới dưới NODE_TIMEOUT_S là SUSPECT, từ NODE_TIMEOUT_S là OFFLINE (= mất liên lạc như trước vòng 5).
SUSPECT_AFTER_S = 8
NODE_TIMEOUT_S = 15
# Kéo góc nhìn của bản sao khác (GET /api/views) mỗi bấy nhiêu giây; góc nhìn nhận cũ hơn VIEW_STALE_S thì bỏ
VIEWS_EVERY_S = 5
VIEW_STALE_S = 15
# Mọi bản sao cấu hình (kể cả chính mình): đa số tính trên tổng số này, không trên số bản sao còn trả lời
REPLICA_NAMES = [name for name, _ in REPLICAS]
# Sink tự kiểm đường đọc Redpanda (broker_ok, lag trong sink_stats) mỗi bấy nhiêu giây
BROKER_CHECK_EVERY_S = 5

# ---------------- Kênh trực tiếp giữa các bản sao (vòng 3) ----------------
# Các bản sao KHÁC để gossip: REPLICA_URLS bỏ dòng trùng tên chính mình
PEERS = [(name, url) for name, url in REPLICAS if name != NODE_NAME]
GOSSIP_EVERY_S = 10
# Đối soát với chi nhánh: kiểm mỗi 5 giây; chỉ bật khi mất broker quá 15 giây và sink vẫn còn kiểm
# (lần kiểm cuối mới hơn 15 giây). Mọi mốc tính bằng now() của replica_db.
RECONCILE_EVERY_S = 5
RECONCILE_AFTER_S = 15
SINK_STALE_S = 15
# Gọi bản sao hoặc chi nhánh khác: quá chừng này thì bỏ, để một node chết không làm treo vòng gossip
PEER_TIMEOUT_S = 2
