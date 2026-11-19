"""Pool kết nối tới CSDL của tiến trình này. Dùng chung cho api, relay, sink."""
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from common.config import DATABASE_URL

# row_factory=dict_row: mỗi dòng trả về là dict, đọc row["qty_on_hand"] cho dễ hiểu
pool = ConnectionPool(
    DATABASE_URL,
    min_size=1,
    max_size=5,
    kwargs={"row_factory": dict_row},
    open=False,
)


def open_pool() -> None:
    pool.open()
    pool.wait(timeout=60)  # chờ Postgres sẵn sàng rồi mới chạy tiếp
