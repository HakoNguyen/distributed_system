"""Cấu hình đọc từ biến môi trường. Compose lấy giá trị từ file .env ở gốc repo."""
import os

# "branch" = quầy chi nhánh (api + relay), "replica" = bản sao trung tâm (api + sink).
# api/main.py dựa vào đây để chọn router.
ROLE = os.environ["ROLE"]

# CSDL của CHÍNH tiến trình này: branch_db hoặc replica_db (tên service trong compose)
DATABASE_URL = os.environ["DATABASE_URL"]

# Redpanda ở máy A. Trên máy A là "redpanda:9092", máy khác là "<IP máy A>:19092".
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
# Sự kiện nằm trong outbox lâu hơn chừng này mà chưa gửi được thì POS báo đỏ
STUCK_AFTER_S = 5

# ---------------- Bản sao trung tâm ----------------
# Tên máy chạy bản sao này: "A", "B", "C". Hiện lên dashboard để biết
# nginx vừa chuyển yêu cầu tới bản sao nào.
NODE_NAME = os.environ.get("NODE_NAME", "?")
# Mỗi bản sao một consumer group riêng -> mỗi bản sao nhận ĐỦ mọi sự kiện
# và tự dựng bảng tổng hợp của riêng nó.
CONSUMER_GROUP = f"replica-{NODE_NAME}"
# Quá bấy nhiêu giây không nhận heartbeat thì coi chi nhánh là mất liên lạc
NODE_TIMEOUT_S = 15
