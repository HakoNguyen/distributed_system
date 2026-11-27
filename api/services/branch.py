"""
Nghiệp vụ của MỘT chi nhánh: tồn kho, sổ cái, outbox.

Nguyên tắc quan trọng nhất: chỉ nói chuyện với CSDL của chính chi nhánh mình
(chạy trên cùng máy). Vì vậy khi mất mạng tới trung tâm, quầy vẫn bán hàng
bình thường. Việc báo lên trung tâm là việc của relay (workers/relay.py),
chạy riêng và không làm chậm việc bán.
"""
import random
import time
from collections.abc import Callable
from datetime import datetime, timezone

from fastapi import HTTPException
from psycopg.errors import UniqueViolation
from psycopg.types.json import Jsonb

from common.config import BRANCH_ID, RECOVERY_STALE_S, RECOVERY_TIMEOUT_S
from common.db import pool
from common.models import HandoffItem

# Trạng thái phục hồi của chi nhánh (vòng 6, PT-14), trong bộ nhớ branch_api. Khởi động luôn ở RECOVERING: chưa nhận
# bán cho tới khi luồng phục hồi (workers/recovery.py) đã kéo và áp xong ghi hộ ở mọi bản sao (docs/spec.md mục 4).
# started, checked_at: time.monotonic() (đo thời gian chờ trong tiến trình, không so thứ tự sự kiện).
recovery: dict = {
    "state": "RECOVERING", "since": datetime.now(timezone.utc), "started": time.monotonic(), "checked_at": None,
    "last_run_at": None, "last_error": None, "incomplete": False, "unreachable": [],
    "pending": 0, "applied": 0, "rejected": 0,
}


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


def movement(movement_id: int) -> dict:
    """Một dòng sổ cái kèm lúc relay gửi xong (outbox.sent_at), cho dashboard truy vết. Chỉ đọc (PT-07)."""
    with pool.connection() as conn:
        row = conn.execute(
            """SELECT m.movement_id, m.product_id, m.move_type, m.qty_delta, m.qty_after,
                      m.created_at AS node_time, o.sent_at
               FROM stock_movement m LEFT JOIN outbox o ON o.event_id = m.movement_id
               WHERE m.movement_id = %s""",
            (movement_id,),
        ).fetchone()
    if row is None:
        raise HTTPException(404, {"error": "movement_not_found"})
    return {"branch_id": BRANCH_ID, **row}


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


# ---------------------------------------------------------------------------
# 5. Ghi hộ (vòng 6, PT-14): tự kéo ghi hộ từ các bản sao, áp theo thứ tự, rồi mới nhận bán mới.
#    workers/recovery.py gọi mạng; ở đây nhận hàm `pull`, `ack` như relay_batch nhận `send`.
# ---------------------------------------------------------------------------
def require_online() -> None:
    """Router gọi trước mọi lệnh ghi (bán, nhập). RECOVERING, hoặc luồng phục hồi chưa chạy trong RECOVERY_STALE_S giây
    (vừa docker unpause, chưa kịp hỏi bản sao có ghi hộ không) thì 503: chưa ghi gì, quầy thử lại sau."""
    stale = recovery["checked_at"] is None or time.monotonic() - recovery["checked_at"] > RECOVERY_STALE_S
    if recovery["state"] != "ONLINE" or stale:
        raise HTTPException(503, {"error": "branch_recovering", "stale": stale})


def next_recovery_state(state: str, incomplete: bool, pulls: dict[str, dict | None],
                        elapsed_s: float) -> tuple[str, bool]:
    """Trạng thái kế tiếp từ kết quả kéo của mọi bản sao (None = không gọi được). Hàm thuần (docs/spec.md mục 4).

    - Bản sao gọi được còn lượt PENDING, hoặc còn nhận ghi hộ (kết luận của nó vẫn OFFLINE): RECOVERING.
    - Mọi bản sao trả lời và sạch: ONLINE, hết cảnh báo.
    - Còn bản sao không gọi được: đang ONLINE thì giữ ONLINE (K3: quầy bị cô lập vẫn bán tại chỗ); đang RECOVERING thì
      chờ, quá RECOVERY_TIMEOUT_S giây thì ONLINE kèm incomplete (ngoại lệ của PT-14).
    """
    reached = [p for p in pulls.values() if p is not None]
    if any(p["pending"] or p["accepting"] for p in reached):
        return "RECOVERING", incomplete
    if len(reached) == len(pulls):
        return "ONLINE", False
    if state == "ONLINE":
        return "ONLINE", incomplete
    if elapsed_s >= RECOVERY_TIMEOUT_S:
        return "ONLINE", True
    return "RECOVERING", incomplete


def collect_handoffs(pulls: dict[str, dict | None]) -> list[dict]:
    """Gộp lượt PENDING của mọi bản sao theo thứ tự áp: thứ tự bản sao trong `pulls` (= REPLICA_URLS), rồi handoff_id.
    Không dùng đồng hồ (PT-05). Cùng request_id ở hai bản sao (POS chuyển bản sao giữa chừng) là MỘT lượt; `holders`
    nhớ mọi (bản sao, handoff_id) đang giữ nó để báo đủ."""
    items: dict[str, dict] = {}
    for name, p in pulls.items():
        for h in sorted(p["pending"] if p else [], key=lambda h: h["handoff_id"]):
            item = items.setdefault(h["request_id"], {"request_id": h["request_id"], "product_id": h["product_id"],
                                                      "qty": h["qty"], "holders": []})
            item["holders"].append((name, h["handoff_id"]))
    return list(items.values())


def _apply_one(item: dict) -> dict:
    with pool.connection() as conn:
        old = conn.execute("SELECT reason FROM handoff_rejected WHERE request_id = %s", (item["request_id"],)).fetchone()
    if old:  # đã từ chối ở lần trước (ack bị mất): giữ nguyên quyết định
        return {"status": "REJECTED", "movement_id": None, "reason": old["reason"], "new": False}
    try:
        # Đúng đường bán hàng: một transaction (PT-02); request_id đã có thì trả kết quả cũ, không trừ lần hai (PT-08)
        r = change_stock(item["product_id"], -item["qty"], "SALE", None, item["request_id"])
        return {"status": "APPLIED", "movement_id": r["movement_id"], "reason": None, "new": not r.get("replayed")}
    except HTTPException as e:  # 422 insufficient_stock, 404 product_not_found: tồn, sổ cái không đổi
        reason = e.detail["error"]
        with pool.connection() as conn:
            n = conn.execute(
                """INSERT INTO handoff_rejected (request_id, product_id, qty, reason, qty_on_hand)
                   VALUES (%s, %s, %s, %s, %s) ON CONFLICT (request_id) DO NOTHING""",
                (item["request_id"], item["product_id"], item["qty"], reason, e.detail.get("qty_on_hand")),
            ).rowcount
        return {"status": "REJECTED", "movement_id": None, "reason": reason, "new": n == 1}


def apply_handoffs(items: list[dict]) -> tuple[list[dict], str | None]:
    """Áp từng lượt theo đúng thứ tự; mỗi lượt tự commit. Lỗi bất ngờ (mất CSDL) thì dừng, không áp các lượt sau (giữ
    thứ tự); trả (kết quả các lượt đã xong, lỗi hoặc None)."""
    results = []
    for item in items:
        try:
            results.append({**item, **_apply_one(item)})
        except Exception as e:
            return results, f"{type(e).__name__}: {e}"[:200]
    return results, None


def _valid_pull(payload: dict) -> dict:
    """Dữ liệu nhận từ bản sao: kiểm trước khi áp. Sai thì ném lỗi (coi như không gọi được bản sao đó)."""
    if payload.get("branch_id") != BRANCH_ID or not isinstance(payload.get("accepting"), bool):
        raise ValueError("phản hồi ghi hộ sai chi nhánh hoặc thiếu accepting")
    return {"accepting": payload["accepting"],
            "pending": [HandoffItem.model_validate(h).model_dump() for h in payload["pending"]]}


def recovery_once(pull: Callable[[str], dict], ack: Callable[[str, dict], None], replicas: list[str]) -> None:
    """Một vòng phục hồi: kéo mọi bản sao, áp, báo kết quả (chỉ sau khi đã commit), đổi trạng thái.
    Bắt MỌI lỗi và ghi vào last_error: một lần lỗi không làm luồng dừng, nên chốt RECOVERY_STALE_S không chặn quầy."""
    errors = []
    try:
        pulls: dict[str, dict | None] = {}
        for name in replicas:
            try:
                pulls[name] = _valid_pull(pull(name))
            except Exception:
                pulls[name] = None  # không gọi được hoặc dữ liệu hỏng
        items = collect_handoffs(pulls)
        results, error = apply_handoffs(items)
        if error:
            errors.append(error)
        # Các lượt trong `results` đã commit: giờ mới báo mọi bản sao đang giữ chúng (PT-07: bản sao tự sửa bảng mình)
        by_replica: dict[str, list[dict]] = {}
        for r in results:
            for name, handoff_id in r["holders"]:
                by_replica.setdefault(name, []).append({"handoff_id": handoff_id, "status": r["status"],
                                                        "movement_id": r["movement_id"], "reason": r["reason"]})
        for name, res in by_replica.items():
            try:
                ack(name, {"branch_id": BRANCH_ID, "results": res})
            except Exception as e:  # ack mất thì lần sau lượt đó còn PENDING, áp lại không trừ thêm, báo lại
                errors.append(f"ack {name}: {type(e).__name__}: {e}")
        recovery["applied"] += sum(r["status"] == "APPLIED" and r["new"] for r in results)
        recovery["rejected"] += sum(r["status"] == "REJECTED" and r["new"] for r in results)
        state, incomplete = next_recovery_state(recovery["state"], recovery["incomplete"], pulls,
                                                time.monotonic() - recovery["started"])
        if state != recovery["state"]:
            recovery.update(state=state, since=datetime.now(timezone.utc), started=time.monotonic())
        recovery.update(incomplete=incomplete, pending=len(items),
                        unreachable=[name for name, p in pulls.items() if p is None])
    except Exception as e:
        errors.append(f"{type(e).__name__}: {e}")
    recovery.update(last_error="; ".join(errors)[:300] or None, last_run_at=datetime.now(timezone.utc),
                    checked_at=time.monotonic())


def recovery_status() -> dict:
    """Trạng thái phục hồi cho POS, dashboard (GET /api/status): cả các lượt ghi hộ đã từ chối, để không mất lặng lẽ."""
    with pool.connection() as conn:
        rejected = conn.execute(
            """SELECT request_id, product_id, qty, reason, qty_on_hand, rejected_at
               FROM handoff_rejected ORDER BY rejected_at DESC, request_id LIMIT 20"""
        ).fetchall()
    keys = ("state", "since", "pending", "applied", "rejected", "incomplete", "unreachable", "last_run_at", "last_error")
    return {**{k: recovery[k] for k in keys}, "rejected_items": rejected}
