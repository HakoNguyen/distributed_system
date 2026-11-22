"""
Nghiệp vụ của MỘT chi nhánh: tồn kho, sổ cái, outbox.

Nguyên tắc quan trọng nhất: chỉ nói chuyện với CSDL của chính chi nhánh mình
(chạy trên cùng máy). Vì vậy khi mất mạng tới trung tâm, quầy vẫn bán hàng
bình thường. Việc báo lên trung tâm là việc của relay (workers/relay.py),
chạy riêng và không làm chậm việc bán.
"""
import random
from collections.abc import Callable

from fastapi import HTTPException
from psycopg.errors import UniqueViolation
from psycopg.types.json import Jsonb

from common.config import BRANCH_ID
from common.db import pool


# ---------------------------------------------------------------------------
# 1. Khởi tạo dữ liệu lần đầu
# ---------------------------------------------------------------------------
def seed_if_empty() -> None:
    """Lần chạy đầu tiên: tạo tồn kho ban đầu cho chi nhánh này.

    Mỗi dòng tồn ban đầu cũng được ghi thành một biến động loại INIT và
    đưa vào outbox. Nhờ vậy trung tâm nhận được số tồn ban đầu qua đúng
    con đường sự kiện như mọi lần bán sau này, không cần cơ chế riêng.
    """
    with pool.connection() as conn, conn.transaction():
        if conn.execute("SELECT 1 FROM inventory LIMIT 1").fetchone():
            return
        products = conn.execute("SELECT product_id FROM product ORDER BY product_id").fetchall()
        for p in products:
            pid = p["product_id"]
            # Số tồn giả lập, khác nhau giữa các chi nhánh nhưng cố định giữa các lần chạy
            qty = 40 + (pid * 37 * BRANCH_ID) % 120
            conn.execute(
                "INSERT INTO inventory (product_id, branch_id, qty_on_hand) VALUES (%s, %s, %s)",
                (pid, BRANCH_ID, qty),
            )
            record_movement(conn, pid, "INIT", qty, qty, None)
    print(f"[api cn{BRANCH_ID}] Đã tạo tồn kho ban đầu cho {len(products)} mã hàng")


def record_movement(conn, product_id, move_type, qty_delta, qty_after, request_id):
    """Ghi một dòng vào sổ cái stock_movement VÀ một dòng vào outbox.

    Hàm này luôn được gọi BÊN TRONG transaction của nghiệp vụ. Hoặc cả ba
    việc (sửa tồn, ghi sổ cái, ghi outbox) cùng thành công, hoặc không việc
    nào xảy ra. Đây là toàn bộ ý tưởng của outbox pattern.
    """
    m = conn.execute(
        """INSERT INTO stock_movement (product_id, move_type, qty_delta, qty_after, request_id)
           VALUES (%s, %s, %s, %s, %s)
           RETURNING movement_id, created_at""",
        (product_id, move_type, qty_delta, qty_after, request_id),
    ).fetchone()

    event = {
        "branch_id": BRANCH_ID,
        "movement_id": m["movement_id"],
        "product_id": product_id,
        "move_type": move_type,
        "qty_delta": qty_delta,
        "qty_after": qty_after,
        "node_time": m["created_at"].isoformat(),  # giờ theo đồng hồ chi nhánh
    }
    conn.execute(
        "INSERT INTO outbox (event_id, payload) VALUES (%s, %s)",
        (m["movement_id"], Jsonb(event)),
    )
    return m["movement_id"]


# ---------------------------------------------------------------------------
# 2. Bán và nhập hàng
# ---------------------------------------------------------------------------
def change_stock(product_id: int, delta: int, move_type: str,
                 expected_version: int | None, request_id: str | None) -> dict:
    try:
        return _change_stock(product_id, delta, move_type, expected_version, request_id)
    except UniqueViolation:
        # Hai yêu cầu cùng request_id tới gần như cùng lúc: yêu cầu sau
        # đụng ràng buộc UNIQUE. Trả kết quả của yêu cầu trước.
        with pool.connection() as conn:
            return _replayed_result(conn, request_id)


def _replayed_result(conn, request_id):
    m = conn.execute(
        "SELECT movement_id, product_id, qty_after FROM stock_movement WHERE request_id = %s",
        (request_id,),
    ).fetchone()
    return {"movement_id": m["movement_id"], "product_id": m["product_id"],
            "qty_on_hand": m["qty_after"], "replayed": True}


def _change_stock(product_id, delta, move_type, expected_version, request_id):
    with pool.connection() as conn, conn.transaction():
        # (a) Yêu cầu này đã xử lý rồi? Thì trả lại kết quả cũ.
        if request_id and conn.execute(
            "SELECT 1 FROM stock_movement WHERE request_id = %s", (request_id,)
        ).fetchone():
            return _replayed_result(conn, request_id)

        # (b) Sửa tồn bằng MỘT câu UPDATE có điều kiện.
        #     Postgres khoá dòng trong lúc sửa, nên hai quầy cùng bán một mã
        #     hàng sẽ xếp hàng lần lượt, không bao giờ bán lố tồn.
        sql = """UPDATE inventory
                 SET qty_on_hand = qty_on_hand + %(delta)s,
                     version = version + 1,
                     updated_at = now()
                 WHERE product_id = %(pid)s
                   AND qty_on_hand + %(delta)s >= 0"""
        if expected_version is not None:
            sql += " AND version = %(ver)s"
        row = conn.execute(
            sql + " RETURNING qty_on_hand, version",
            {"delta": delta, "pid": product_id, "ver": expected_version},
        ).fetchone()

        # (c) Không dòng nào được sửa: tìm lý do để trả mã lỗi đúng.
        if row is None:
            cur = conn.execute(
                "SELECT qty_on_hand, version FROM inventory WHERE product_id = %s", (product_id,)
            ).fetchone()
            if cur is None:
                raise HTTPException(404, {"error": "product_not_found"})
            if expected_version is not None and cur["version"] != expected_version:
                raise HTTPException(409, {"error": "version_conflict",
                                          "current_version": cur["version"]})
            raise HTTPException(422, {"error": "insufficient_stock",
                                      "qty_on_hand": cur["qty_on_hand"]})

        # (d) Ghi sổ cái + outbox trong CÙNG transaction.
        movement_id = record_movement(conn, product_id, move_type, delta,
                                      row["qty_on_hand"], request_id)

    return {"movement_id": movement_id, "product_id": product_id,
            "qty_on_hand": row["qty_on_hand"], "version": row["version"]}


def random_sales(count: int) -> dict:
    """Bán nhanh `count` đơn ngẫu nhiên, mỗi đơn 1–3 đơn vị. Dùng khi demo."""
    with pool.connection() as conn:
        pids = [r["product_id"] for r in conn.execute("SELECT product_id FROM inventory").fetchall()]
    done, skipped = 0, 0
    for _ in range(count):
        try:
            change_stock(random.choice(pids), -random.randint(1, 3), "SALE", None, None)
            done += 1
        except HTTPException:  # hết hàng mã đó thì bỏ qua
            skipped += 1
    return {"sold": done, "skipped_out_of_stock": skipped}


# ---------------------------------------------------------------------------
# 3. Truy vấn
# ---------------------------------------------------------------------------
def list_inventory() -> list[dict]:
    with pool.connection() as conn:
        return conn.execute(
            """SELECT i.product_id, p.name, p.unit, p.reorder_point,
                      i.qty_on_hand, i.version, i.updated_at
               FROM inventory i JOIN product p USING (product_id)
               ORDER BY i.product_id"""
        ).fetchall()


def snapshot() -> dict:
    """Tồn kèm biến động mới nhất từng mã, cho bản sao đối soát khi mất broker. Chỉ đọc (PT-07).

    MỘT câu lệnh nên tồn và movement_id đọc cùng một thời điểm; PT-02 bảo đảm hai giá trị luôn đổi cùng nhau.
    """
    with pool.connection() as conn:
        cells = conn.execute(
            """SELECT i.product_id, i.qty_on_hand,
                      m.movement_id AS last_movement, m.created_at AS node_time
               FROM inventory i
               JOIN LATERAL (SELECT movement_id, created_at FROM stock_movement s
                             WHERE s.product_id = i.product_id
                             ORDER BY movement_id DESC LIMIT 1) m ON true
               ORDER BY i.product_id"""
        ).fetchall()
    return {"branch_id": BRANCH_ID, "cells": cells}


def outbox_backlog() -> dict:
    """Số sự kiện chưa gửi và tuổi của sự kiện cũ nhất (giây)."""
    with pool.connection() as conn:
        return conn.execute(
            """SELECT count(*) AS n,
                      extract(epoch FROM now() - min(created_at)) AS oldest_s
               FROM outbox WHERE sent_at IS NULL"""
        ).fetchone()


# ---------------------------------------------------------------------------
# 4. Relay (workers/relay.py gọi): gửi outbox và ghi trạng thái gửi
# ---------------------------------------------------------------------------
def relay_batch(send: Callable[[list[dict]], None], limit: int = 200) -> int:
    """Gửi một lô outbox chưa gửi bằng `send`, rồi mới đánh dấu sent_at (PT-03). Trả số sự kiện đã gửi.

    `send` nhận các payload theo thứ tự event_id và ném lỗi nếu Redpanda chưa xác nhận đủ cả lô.
    Lời gọi mạng nằm NGOÀI transaction: đọc lô, gửi, rồi mới mở transaction mới để đánh dấu đúng
    các event_id của lô. Lỗi giữa chừng -> không đánh dấu gì, lần sau gửi lại (at-least-once).
    Mỗi chi nhánh chỉ có một relay nên không cần khoá dòng.
    """
    with pool.connection() as conn:
        rows = conn.execute(
            "SELECT event_id, payload FROM outbox WHERE sent_at IS NULL ORDER BY event_id LIMIT %s",
            (limit,),
        ).fetchall()
    if not rows:
        return 0
    send([r["payload"] for r in rows])
    with pool.connection() as conn:
        conn.execute("UPDATE outbox SET sent_at = now() WHERE event_id = ANY(%s)",
                     ([r["event_id"] for r in rows],))
    return len(rows)


def record_relay_result(error: str | None) -> None:
    """Ghi kết quả một lần gửi: None = Redpanda đã xác nhận cả lô; chuỗi = lỗi.
    failing_since giữ mốc lỗi ĐẦU TIÊN của đợt lỗi, để POS hiện "lỗi từ HH:MM:SS"."""
    with pool.connection() as conn:
        if error is None:
            conn.execute("UPDATE relay_status SET last_ok_at = now(), failing_since = NULL")
        else:
            conn.execute(
                "UPDATE relay_status SET last_error = %s, failing_since = coalesce(failing_since, now())",
                (error,),
            )


def relay_status() -> dict:
    with pool.connection() as conn:
        return conn.execute("SELECT last_ok_at, failing_since, last_error FROM relay_status").fetchone()
