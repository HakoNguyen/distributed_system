"""Cấu hình của MỘT bản sao trung tâm, đọc từ biến môi trường (file .env ở thư mục gốc)."""
import os

# Tên máy đang chạy bản sao này: "A", "B", "C". Hiện lên dashboard để biết
# nginx vừa chuyển yêu cầu tới bản sao nào.
NODE_NAME = os.environ.get("NODE_NAME", "?")

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://app:app@replica_db:5432/kho")

# Redpanda ở máy A. Trên máy A là "redpanda:9092", máy khác là "<IP máy A>:19092".
KAFKA_BROKERS = os.environ.get("KAFKA_BROKERS", "redpanda:9092")

TOPIC = "inventory.movement"
# Mỗi bản sao một consumer group riêng -> mỗi bản sao nhận ĐỦ mọi sự kiện
# và tự dựng bảng tổng hợp của riêng nó.
CONSUMER_GROUP = f"replica-{NODE_NAME}"

# Quá bấy nhiêu giây không nhận heartbeat thì coi chi nhánh là mất liên lạc
NODE_TIMEOUT_S = 15
