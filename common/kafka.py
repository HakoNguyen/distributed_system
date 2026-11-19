"""Phần dùng chung khi nói chuyện với Redpanda (relay và sink đều cần)."""
from confluent_kafka import KafkaException
from confluent_kafka.admin import AdminClient, NewTopic

from common.config import KAFKA_BROKERS, TOPIC


def ensure_topic(tag: str) -> bool:
    """Tạo topic 3 phân hoạch nếu chưa có. Trả True khi topic đã sẵn sàng,
    False khi chưa nói chuyện được với Redpanda (bên gọi tự thử lại)."""
    admin = AdminClient({"bootstrap.servers": KAFKA_BROKERS})
    future = admin.create_topics([NewTopic(TOPIC, num_partitions=3, replication_factor=1)])[TOPIC]
    try:
        future.result(timeout=5)
        print(f"{tag} Đã tạo topic {TOPIC}")
        return True
    except KafkaException as e:
        return "TOPIC_ALREADY_EXISTS" in str(e)
    except Exception:
        return False
