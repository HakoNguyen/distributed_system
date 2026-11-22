"""
sink — đọc sự kiện từ Redpanda và áp vào bảng tổng hợp của bản sao này.
Chạy: python -m workers.sink

Chống trùng và chống lệch thứ tự nằm trong services/replica.py: apply_event.
Mỗi 5 giây sink tự kiểm đường đọc Redpanda và ghi vào sink_stats (broker_ok, broker_lost_at, lag),
để dashboard tách "đồng bộ dừng" khỏi "chi nhánh còn sống" (heartbeat đi HTTP thẳng, không qua broker).
"""
import json
import signal
import sys
import time
from datetime import datetime, timezone

from confluent_kafka import TIMESTAMP_NOT_AVAILABLE, Consumer, KafkaError, KafkaException, TopicPartition

from common.config import BROKER_CHECK_EVERY_S, CONSUMER_GROUP, KAFKA_BROKERS, NODE_NAME, TOPIC
from common.db import open_pool
from services.replica import apply_event, record_broker_check

TAG = f"[sink {NODE_NAME}]"


def broker_lag(consumer: Consumer, md) -> int:
    """Hỏi Redpanda: số sự kiện bản sao này chưa áp = Σ(high watermark − vị trí đã áp).
    `md` = metadata vừa hỏi (list_topics). Ném lỗi nếu topic chưa có hoặc không hỏi được leader của mọi
    phân hoạch (mất broker, mất đa số).

    Vị trí đã áp lấy từ position() (consumer tự biết, sự kiện poll trả về đều đã ghi CSDL), không hỏi
    offset đã commit: lời hỏi đó phụ thuộc coordinator của group và hay timeout lúc một broker bị cắt
    (K7c) dù việc đọc vẫn chạy. Chỉ khi chưa có vị trí (mới khởi động) mới hỏi committed()."""
    t = md.topics.get(TOPIC)
    if t is None or t.error is not None:
        raise KafkaException(t.error if t else KafkaError(KafkaError.UNKNOWN_TOPIC_OR_PART))
    tps = [TopicPartition(TOPIC, p) for p in t.partitions]
    assigned = consumer.assignment()
    pos = {tp.partition: tp.offset for tp in (consumer.position(assigned) if assigned else [])}
    unknown = [tp for tp in tps if pos.get(tp.partition, -1) < 0]
    if unknown:
        pos.update({tp.partition: tp.offset for tp in consumer.committed(unknown, timeout=3)})
    lag = 0
    for tp in tps:
        marks = consumer.get_watermark_offsets(tp, timeout=3, cached=False)
        if marks is None:
            raise KafkaException(KafkaError(KafkaError._TIMED_OUT, f"phân hoạch {tp.partition}"))
        low, high = marks
        lag += high - (pos[tp.partition] if pos[tp.partition] >= 0 else low)
    return lag


def check_broker(consumer: Consumer, was_ok: bool | None) -> bool:
    """Gọi Redpanda trước (ngoài transaction), rồi mới ghi kết quả vào CSDL."""
    up = None  # broker còn sống theo metadata (đã kiểm: broker dừng thì biến khỏi danh sách; ISR thì không)
    try:
        md = consumer.list_topics(TOPIC, timeout=3)
        up = sorted(md.brokers)
        lag, ok = broker_lag(consumer, md), True
    except Exception as e:
        lag, ok = None, False
        if was_ok is not False:
            print(f"{TAG} Mất đường đọc Redpanda ({e}). Đồng bộ dừng; tự đọc tiếp khi có lại")
    if ok and was_ok is False:
        print(f"{TAG} Có lại đường đọc Redpanda, còn {lag} sự kiện chưa áp")
    record_broker_check(ok, lag, up)
    return ok


def main() -> None:
    # `docker compose stop sink` gửi SIGTERM. Đổi thành SystemExit để khối finally đóng consumer
    # và rời consumer group ngay; không thì group còn "có người" ~45 giây, `rpk group seek` (K6) bị từ chối.
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    open_pool()

    consumer = Consumer({
        "bootstrap.servers": KAFKA_BROKERS,  # cả ba broker
        # Broker leader chết (K7a): hỏi lại ai là leader mới sau ≤ 5 giây (mặc định 5 phút)
        "topic.metadata.refresh.interval.ms": 5000,
        # Broker bị rút mạng (K7c) không trả RST: yêu cầu đang chờ nó treo tới hết hạn này rồi mới bỏ
        # kết nối và đọc từ leader mới (mặc định 60 giây)
        "socket.timeout.ms": 10000,
        "group.id": CONSUMER_GROUP,
        "auto.offset.reset": "earliest",  # nhóm mới thì đọc từ sự kiện đầu tiên
        "enable.auto.commit": False,      # tự báo "đã xử lý" sau khi ghi CSDL xong
    })
    try:
        # Topic do topic-init (node A) tạo khi cụm đủ broker; chờ tới khi có
        ok = None
        while not (ok := check_broker(consumer, ok)):
            print(f"{TAG} Chưa đọc được topic {TOPIC} ({KAFKA_BROKERS}), thử lại sau 3 giây")
            time.sleep(3)

        consumer.subscribe([TOPIC])
        print(f"{TAG} Đang nghe topic {TOPIC} (nhóm {CONSUMER_GROUP})")
        next_check = time.monotonic() + BROKER_CHECK_EVERY_S
        uncommitted = False
        while True:
            if time.monotonic() >= next_check:
                if uncommitted and commit(consumer):
                    uncommitted = False
                ok = check_broker(consumer, ok)
                next_check = time.monotonic() + BROKER_CHECK_EVERY_S

            msg = consumer.poll(1.0)
            if msg is None:
                continue
            if msg.error():
                if msg.error().code() != KafkaError._PARTITION_EOF:
                    print(f"{TAG} Lỗi Redpanda: {msg.error()}")
                continue

            e = json.loads(msg.value())
            ts_type, ts_ms = msg.timestamp()  # topic LogAppendTime: giờ broker leader ghi
            kafka_ts = None if ts_type == TIMESTAMP_NOT_AVAILABLE else datetime.fromtimestamp(ts_ms / 1000, timezone.utc)
            result = apply_event(e, msg.partition(), msg.offset(), kafka_ts)
            label = "mới" if result == "new" else "TRÙNG, bỏ qua"
            print(f"{TAG} cn{e['branch_id']} #{e['movement_id']} {e['move_type']} "
                  f"sp{e['product_id']} {e['qty_delta']:+d} -> {e['qty_after']}  ({label})")

            # Thứ tự quan trọng: ghi CSDL xong rồi MỚI commit offset (PT-06).
            # Chết ở giữa hai bước -> lần sau nhận lại sự kiện -> bị lớp chống trùng bỏ qua.
            if not commit(consumer, msg):
                uncommitted = True
    finally:
        consumer.close()


def commit(consumer: Consumer, msg=None) -> bool:
    """Commit offset đã áp (msg=None: mọi sự kiện poll đã trả về, đều đã ghi CSDL). Trả False nếu lỗi.
    Broker giữ vai coordinator của group vừa chết (K7a) thì commit lỗi vài giây: không để sink chết,
    lần kiểm broker sau commit lại. Nhận lại sự kiện chưa commit thì apply_event bỏ qua bản trùng."""
    try:
        if msg is None:
            consumer.commit(asynchronous=False)
        else:
            consumer.commit(message=msg, asynchronous=False)
        return True
    except KafkaException as e:
        if e.args[0].code() != KafkaError._NO_OFFSET:
            print(f"{TAG} Chưa commit được offset ({e}), thử lại ở lần kiểm broker sau")
            return False
        return True


if __name__ == "__main__":
    main()
