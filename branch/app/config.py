"""Cấu hình của node chi nhánh, đọc từ biến môi trường (file .env ở thư mục gốc)."""
import os

BRANCH_ID = int(os.environ["BRANCH_ID"])
BRANCH_NAME = os.environ.get("BRANCH_NAME") or f"Chi nhánh {BRANCH_ID}"

# CSDL của CHÍNH chi nhánh này ("branch_db" là tên service trong docker-compose)
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://app:app@branch_db:5432/kho")

# Redpanda ở máy A. Trên máy A là "redpanda:9092", máy khác là "<IP máy A>:19092".
KAFKA_BROKERS = os.environ.get("KAFKA_BROKERS", "")


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


# Mọi bản sao trung tâm. Chi nhánh gửi heartbeat tới TẤT CẢ, mỗi bản sao tự
# phán đoán "chi nhánh này còn sống không" theo những gì nó nghe được.
REPLICAS = _parse_replicas(os.environ.get("REPLICA_URLS", ""))

TOPIC = "inventory.movement"
HEARTBEAT_EVERY_S = 5
# Sự kiện nằm trong outbox lâu hơn chừng này mà chưa gửi được thì POS báo đỏ
STUCK_AFTER_S = 5
