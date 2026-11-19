"""
sink — đọc sự kiện từ Redpanda và áp vào bảng tổng hợp của bản sao này.
Chạy: python -m workers.sink

Chống trùng và chống lệch thứ tự nằm trong services/replica.py: apply_event.
"""
import json
import signal
import sys
import time

from confluent_kafka import Consumer, KafkaError

from common.config import CONSUMER_GROUP, KAFKA_BROKERS, NODE_NAME, TOPIC
from common.db import open_pool
from common.kafka import ensure_topic
from services.replica import apply_event

TAG = f"[sink {NODE_NAME}]"


def main() -> None:
    # `docker compose stop sink` gửi SIGTERM. Đổi thành SystemExit để khối finally đóng consumer
    # và rời consumer group ngay; không thì group còn "có người" ~45 giây, `rpk group seek` (K6) bị từ chối.
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    open_pool()
    # Redpanda có thể khởi động chậm hơn sink một chút
    while not ensure_topic(TAG):
        print(f"{TAG} Chưa kết nối được Redpanda ({KAFKA_BROKERS}), thử lại sau 3 giây")
        time.sleep(3)

    consumer = Consumer({
        "bootstrap.servers": KAFKA_BROKERS,
        "group.id": CONSUMER_GROUP,
        "auto.offset.reset": "earliest",  # nhóm mới thì đọc từ sự kiện đầu tiên
        "enable.auto.commit": False,      # tự báo "đã xử lý" sau khi ghi CSDL xong
    })
    consumer.subscribe([TOPIC])
    print(f"{TAG} Đang nghe topic {TOPIC} (nhóm {CONSUMER_GROUP})")

    try:
        while True:
            msg = consumer.poll(1.0)
            if msg is None:
                continue
            if msg.error():
                if msg.error().code() != KafkaError._PARTITION_EOF:
                    print(f"{TAG} Lỗi Redpanda: {msg.error()}")
                continue

            e = json.loads(msg.value())
            result = apply_event(e, msg.partition(), msg.offset())
            label = "mới" if result == "new" else "TRÙNG, bỏ qua"
            print(f"{TAG} cn{e['branch_id']} #{e['movement_id']} {e['move_type']} "
                  f"sp{e['product_id']} {e['qty_delta']:+d} -> {e['qty_after']}  ({label})")

            # Thứ tự quan trọng: ghi CSDL xong rồi MỚI commit offset.
            # Chết ở giữa hai bước -> lần sau nhận lại sự kiện -> bị lớp chống trùng bỏ qua.
            consumer.commit(message=msg, asynchronous=False)
    finally:
        consumer.close()


if __name__ == "__main__":
    main()
