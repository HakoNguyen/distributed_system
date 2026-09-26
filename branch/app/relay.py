"""
relay — chuyển sự kiện từ bảng outbox của chi nhánh lên Redpanda ở trung tâm.

Vòng lặp rất đơn giản:
  1. Lấy các dòng outbox chưa gửi (sent_at IS NULL), theo thứ tự movement_id.
  2. Gửi hết lên Redpanda và CHỜ Redpanda xác nhận đã nhận.
  3. Chỉ khi mọi dòng được xác nhận mới đánh dấu sent_at.
  Lỗi ở bất kỳ bước nào (thường là mất mạng) -> không đánh dấu gì, lát thử lại.

Hệ quả: một sự kiện có thể được gửi HƠN MỘT LẦN (gửi xong nhưng chết trước khi
kịp đánh dấu), nhưng KHÔNG BAO GIỜ bị mất. Đây gọi là "at-least-once".
Việc bỏ bản trùng là trách nhiệm của bên nhận (xem hq/app/sink.py).

Trong đề tài kho đầy đủ, relay này được thay bằng Debezium đọc thẳng WAL.
Ý tưởng giữ nguyên, chỉ khác cách lấy dữ liệu ra khỏi outbox.
"""
import json
import time

from confluent_kafka import KafkaException, Producer
from confluent_kafka.admin import AdminClient, NewTopic

from config import BRANCH_ID, KAFKA_BROKERS, TOPIC
from db import open_pool, pool

BATCH = 200
TAG = f"[relay cn{BRANCH_ID}]"

producer = Producer({
    "bootstrap.servers": KAFKA_BROKERS,
    "client.id": f"relay-cn{BRANCH_ID}",
    "acks": "all",
    # Sau 8 giây mà chưa gửi được thì báo lỗi, không treo mãi
    "message.timeout.ms": 8000,
})


def ensure_topic() -> bool:
    """Tạo topic 3 phân hoạch nếu chưa có. Trả True nếu topic đã sẵn sàng."""
    admin = AdminClient({"bootstrap.servers": KAFKA_BROKERS})
    future = admin.create_topics([NewTopic(TOPIC, num_partitions=3, replication_factor=1)])[TOPIC]
    try:
        future.result(timeout=5)
        print(f"{TAG} Đã tạo topic {TOPIC}")
        return True
    except KafkaException as e:
        if "TOPIC_ALREADY_EXISTS" in str(e):
            return True
        return False
    except Exception:
        return False


def send_batch() -> int:
    """Gửi một lô sự kiện. Trả về số sự kiện đã gửi thành công."""
    with pool.connection() as conn, conn.transaction():
        rows = conn.execute(
            """SELECT event_id, payload FROM outbox
               WHERE sent_at IS NULL
               ORDER BY event_id
               LIMIT %s
               FOR UPDATE SKIP LOCKED""",
            (BATCH,),
        ).fetchall()
        if not rows:
            return 0

        errors = []

        def on_delivery(err, _msg):
            if err is not None:
                errors.append(err)

        for r in rows:
            e = r["payload"]
            producer.produce(
                TOPIC,
                # Khoá thông điệp = (chi nhánh, mã hàng): mọi sự kiện của cùng một
                # dòng tồn vào cùng một phân hoạch, nên giữ đúng thứ tự.
                key=f'{e["branch_id"]}:{e["product_id"]}',
                value=json.dumps(e, ensure_ascii=False).encode(),
                on_delivery=on_delivery,
            )

        # Chờ Redpanda xác nhận. Timeout dài hơn message.timeout.ms nên khi hàm
        # trả về, mọi thông điệp đã có kết quả (thành công hoặc lỗi).
        remaining = producer.flush(12)
        if remaining or errors:
            reason = errors[0] if errors else f"{remaining} thông điệp chưa có xác nhận"
            # Ném lỗi -> transaction rollback -> không dòng nào bị đánh dấu đã gửi
            raise RuntimeError(reason)

        conn.execute(
            "UPDATE outbox SET sent_at = now() WHERE event_id = ANY(%s)",
            ([r["event_id"] for r in rows],),
        )
        return len(rows)


def main() -> None:
    open_pool()
    print(f"{TAG} Bắt đầu. Gửi tới {KAFKA_BROKERS}, topic {TOPIC}")
    topic_ready = False
    was_failing = False
    while True:
        try:
            if not topic_ready:
                topic_ready = ensure_topic()
            n = send_batch()
            if was_failing:
                print(f"{TAG} Đã nối lại được trung tâm")
                was_failing = False
            if n:
                print(f"{TAG} Đã gửi {n} sự kiện")
            else:
                time.sleep(1)  # outbox trống, nghỉ một nhịp
        except Exception as e:
            with pool.connection() as conn:
                backlog = conn.execute(
                    "SELECT count(*) AS n FROM outbox WHERE sent_at IS NULL"
                ).fetchone()["n"]
            print(f"{TAG} Không gửi được lên Redpanda ({e}). "
                  f"{backlog} sự kiện vẫn nằm an toàn trong outbox, thử lại sau 3 giây")
            was_failing = True
            time.sleep(3)


if __name__ == "__main__":
    main()
