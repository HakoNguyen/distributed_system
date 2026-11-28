"""Pool kết nối tới CSDL của tiến trình này. Dùng chung cho api, relay, sink."""
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from common.config import DATABASE_URL

# row_factory=dict_row: mỗi dòng trả về là dict, đọc row["qty_on_hand"] cho dễ hiểu
# check: thử kết nối lúc lấy ra pool; kết nối tới primary cũ đã chết (sau promote, vòng 7) bị bỏ và thay bằng kết nối
# mới (chuỗi nhiều host tự tìm primary), thay vì làm hỏng lượt bán kế tiếp
pool = ConnectionPool(
    DATABASE_URL,
    min_size=1,
    max_size=5,
    kwargs={"row_factory": dict_row},
    check=ConnectionPool.check_connection,
    open=False,
)


def open_pool() -> None:
    pool.open()
    pool.wait(timeout=60)  # chờ Postgres sẵn sàng rồi mới chạy tiếp
