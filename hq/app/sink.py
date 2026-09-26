"""
sink — đọc sự kiện từ Redpanda và cập nhật bảng tổng hợp tồn kho ở trung tâm.

Sink phải chịu được hai chuyện chắc chắn sẽ xảy ra trong hệ phân tán:

  1. NHẬN TRÙNG. Relay gửi at-least-once, và chính sink cũng có thể chết
     sau khi ghi CSDL nhưng trước khi báo Redpanda "đã đọc tới đây". Khi đó
     Redpanda sẽ giao lại. -> Chống bằng khoá chính (branch_id, movement_id)
     của event_log: sự kiện đã thấy thì INSERT không vào, bỏ qua.

  2. NHẬN LỆCH THỨ TỰ (sự kiện cũ tới sau sự kiện mới). -> Chống bằng điều
     kiện `last_movement < EXCLUDED.last_movement` khi cập nhật snapshot:
     chỉ số mới hơn mới được ghi đè số cũ.

Nhờ hai lớp này, chạy lại toàn bộ sự kiện từ đầu (replay) cũng không làm sai
số liệu. Kịch bản "phát lại toàn bộ sự kiện" trong README chứng minh điều đó.
"""
import json
import time

from confluent_kafka import Consumer, KafkaError, KafkaException
from confluent_kafka.admin import AdminClient, NewTopic

from config import CONSUMER_GROUP, KAFKA_BROKERS, NODE_NAME, TOPIC
from db import open_pool, pool


def apply_event(e: dict, partition: int | None = None, offset: int | None = None) -> str:
    """Áp một sự kiện vào CSDL trung tâm. Trả 'new' hoặc 'duplicate'."""
    with pool.connection() as conn, conn.transaction():
        inserted = conn.execute(
            """INSERT INTO event_log (branch_id, movement_id, product_id, move_type,
                                      qty_delta, qty_after, node_time,
                                      kafka_partition, kafka_offset)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (branch_id, movement_id) DO NOTHING""",
            (e["branch_id"], e["movement_id"], e["product_id"], e["move_type"],
             e["qty_delta"], e["qty_after"], e["node_time"], partition, offset),
        ).rowcount

        if inserted == 0:  # lớp chống trùng thứ nhất
            conn.execute("UPDATE sink_stats SET duplicates = duplicates + 1")
            return "duplicate"

        # Lớp thứ hai: chỉ ghi đè khi sự kiện này MỚI HƠN cái đang có.
        # Lưu ý: so sánh bằng movement_id chứ KHÔNG bằng node_time — đồng hồ
        # các máy lệch nhau nên không tin được, còn movement_id thì do chính
        # chi nhánh tăng dần.
        conn.execute(
            """INSERT INTO inventory_snapshot (branch_id, product_id, qty_on_hand,
                                               last_movement, node_time, updated_at)
               VALUES (%s, %s, %s, %s, %s, now())
               ON CONFLICT (branch_id, product_id) DO UPDATE
               SET qty_on_hand   = EXCLUDED.qty_on_hand,
                   last_movement = EXCLUDED.last_movement,
                   node_time     = EXCLUDED.node_time,
                   updated_at    = now()
               WHERE inventory_snapshot.last_movement < EXCLUDED.last_movement""",
            (e["branch_id"], e["product_id"], e["qty_after"], e["movement_id"], e["node_time"]),
        )
        conn.execute("UPDATE sink_stats SET processed = processed + 1, last_event_at = now()")
        return "new"


def ensure_topic() -> None:
    admin = AdminClient({"bootstrap.servers": KAFKA_BROKERS})
    f = admin.create_topics([NewTopic(TOPIC, num_partitions=3, replication_factor=1)])[TOPIC]
    try:
        f.result(timeout=10)
        print(f"[sink {NODE_NAME}] Đã tạo topic {TOPIC}")
    except KafkaException as e:
        if "TOPIC_ALREADY_EXISTS" not in str(e):
            raise


def main() -> None:
    open_pool()
    while True:  # Redpanda có thể khởi động chậm hơn sink một chút
        try:
            ensure_topic()
            break
        except Exception as e:
            print(f"[sink {NODE_NAME}] Chưa kết nối được Redpanda ({e}), thử lại sau 3 giây")
            time.sleep(3)

    consumer = Consumer({
        "bootstrap.servers": KAFKA_BROKERS,
        "group.id": CONSUMER_GROUP,
        "auto.offset.reset": "earliest",  # nhóm mới thì đọc từ sự kiện đầu tiên
        "enable.auto.commit": False,      # tự báo "đã xử lý" sau khi ghi CSDL xong
    })
    consumer.subscribe([TOPIC])
    print(f"[sink {NODE_NAME}] Đang nghe topic {TOPIC} (nhóm {CONSUMER_GROUP})")

    try:
        while True:
            msg = consumer.poll(1.0)
            if msg is None:
                continue
            if msg.error():
                if msg.error().code() != KafkaError._PARTITION_EOF:
                    print(f"[sink {NODE_NAME}] Lỗi Redpanda: {msg.error()}")
                continue

            e = json.loads(msg.value())
            result = apply_event(e, msg.partition(), msg.offset())
            label = "mới" if result == "new" else "TRÙNG, bỏ qua"
            print(f"[sink {NODE_NAME}] cn{e['branch_id']} #{e['movement_id']} {e['move_type']} "
                  f"sp{e['product_id']} {e['qty_delta']:+d} -> {e['qty_after']}  ({label})")

            # Thứ tự quan trọng: ghi CSDL xong rồi MỚI commit offset.
            # Chết ở giữa hai bước -> lần sau nhận lại sự kiện -> bị lớp chống trùng bỏ qua.
            consumer.commit(message=msg, asynchronous=False)
    finally:
        consumer.close()


if __name__ == "__main__":
    main()
