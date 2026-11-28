"""
relay — chuyển sự kiện từ bảng outbox của chi nhánh lên cụm Redpanda.
Chạy: python -m workers.relay

Vòng lặp rất đơn giản (services/branch.py: relay_batch):
  1. Lấy các dòng outbox chưa gửi (sent_at IS NULL), theo thứ tự movement_id.
  2. Gửi hết lên Redpanda và CHỜ Redpanda xác nhận đã nhận (acks=all: đa số broker đã ghi đĩa).
  3. Chỉ khi mọi dòng được xác nhận mới đánh dấu sent_at.
  Lỗi ở bất kỳ bước nào (thường là mất mạng, mất đa số broker) -> không đánh dấu gì, lát thử lại.
Mỗi lần gửi, relay ghi kết quả vào relay_status để POS hiện "Gửi lên Redpanda: lỗi từ HH:MM:SS".

Hệ quả: một sự kiện có thể được gửi HƠN MỘT LẦN (gửi xong nhưng chết trước khi
kịp đánh dấu), nhưng KHÔNG BAO GIỜ bị mất. Đây gọi là "at-least-once".
Việc bỏ bản trùng là trách nhiệm của bên nhận (services/replica.py: apply_event).

Trong đề tài kho đầy đủ, relay này được thay bằng Debezium đọc thẳng WAL.
Ý tưởng giữ nguyên, chỉ khác cách lấy dữ liệu ra khỏi outbox.
"""
import json
import sys
import time
from pathlib import Path

from confluent_kafka import Producer

from common.config import BRANCH_ID, KAFKA_BROKERS, TOPIC
from common.db import open_pool
from services.branch import outbox_backlog, record_relay_result, relay_batch

TAG = f"[relay cn{BRANCH_ID}]"
# Healthcheck (vòng 7): mỗi lượt vòng lặp chạm file này; lỗi Redpanda vẫn chạy hết lượt nên vẫn "sống", chỉ treo mới hỏng
ALIVE = Path("/tmp/alive")

producer = Producer({
    "bootstrap.servers": KAFKA_BROKERS,  # cả ba broker: mất một broker vẫn tìm được leader mới
    "client.id": f"relay-cn{BRANCH_ID}",
    "acks": "all",
    # Gửi lại bên trong thư viện không tạo bản trùng, không đảo thứ tự trong một phân hoạch
    "enable.idempotence": True,
    # Sau 8 giây mà chưa gửi được thì báo lỗi, không treo mãi
    "message.timeout.ms": 8000,
    # Broker leader chết (K7a): hỏi lại ai là leader mới sau ≤ 5 giây (mặc định 5 phút)
    "topic.metadata.refresh.interval.ms": 5000,
    # Broker bị rút mạng (K7c) không trả RST: yêu cầu đang chờ nó (kể cả hỏi metadata) treo tới hết
    # hạn này rồi mới bỏ kết nối và gửi qua broker khác (mặc định 60 giây)
    "socket.timeout.ms": 10000,
})


def send(payloads: list[dict]) -> None:
    """Gửi cả lô lên Redpanda; ném lỗi nếu có thông điệp chưa được xác nhận."""
    errors = []

    def on_delivery(err, _msg):
        if err is not None:
            errors.append(err)

    for e in payloads:
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
    fatal = next((e for e in errors if e.fatal()), None)
    if fatal:
        # Producer idempotent hỏng hẳn thì không dùng lại được: thoát để Docker khởi động lại relay
        print(f"{TAG} Lỗi không phục hồi được ({fatal}), khởi động lại relay")
        sys.exit(1)
    if remaining or errors:
        raise RuntimeError(errors[0] if errors else f"{remaining} thông điệp chưa có xác nhận")


def main() -> None:
    open_pool()
    print(f"{TAG} Bắt đầu. Gửi tới {KAFKA_BROKERS}, topic {TOPIC}")
    was_failing = False
    while True:
        ALIVE.touch()
        try:
            n = relay_batch(send)
            if n:
                record_relay_result(None)
                print(f"{TAG} Đã gửi {n} sự kiện")
                if was_failing:
                    print(f"{TAG} Đã nối lại được Redpanda")
                    was_failing = False
            else:
                time.sleep(1)  # outbox trống, nghỉ một nhịp
        except Exception as e:
            print(f"{TAG} Không gửi được lên Redpanda ({e}). "
                  f"{outbox_backlog()['n']} sự kiện vẫn nằm an toàn trong outbox, thử lại sau 3 giây")
            record_relay_result(str(e))
            was_failing = True
            time.sleep(3)


if __name__ == "__main__":
    main()
