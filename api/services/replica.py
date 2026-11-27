"""
Nghiệp vụ của MỘT bản sao trung tâm: áp sự kiện, ghi heartbeat, truy vấn dashboard.

Bản sao KHÔNG giữ bản chính của tồn kho và KHÔNG gọi thẳng CSDL của chi nhánh.
Nó chỉ đọc/ghi CSDL của chính mình: bảng tổng hợp dựng lại từ sự kiện.
"""
from datetime import datetime, timezone

from fastapi import HTTPException
from psycopg.types.json import Jsonb

from common.config import (NODE_NAME, NODE_TIMEOUT_S, RECONCILE_AFTER_S, REPLICA_NAMES, SINK_STALE_S,
                           SUSPECT_AFTER_S, VIEW_STALE_S)
from common.db import pool
from common.models import BranchView, HandoffAck, HandoffSale, Heartbeat, SnapshotCell


# ---------------------------------------------------------------------------
# 1. Áp sự kiện (sink gọi)
# ---------------------------------------------------------------------------
def apply_event(e: dict, partition: int | None = None, offset: int | None = None,
                kafka_ts: datetime | None = None) -> str:
    """Áp một sự kiện vào CSDL trung tâm. Trả 'new' hoặc 'duplicate'.

    Chịu được hai chuyện chắc chắn xảy ra trong hệ phân tán:
      1. NHẬN TRÙNG: khoá chính (branch_id, movement_id) của event_log.
      2. NHẬN LỆCH THỨ TỰ: chỉ ghi đè snapshot khi movement_id MỚI HƠN.
    Nhờ vậy phát lại toàn bộ sự kiện từ đầu cũng không làm sai số liệu.
    """
    with pool.connection() as conn, conn.transaction():
        inserted = conn.execute(
            """INSERT INTO event_log (branch_id, movement_id, product_id, move_type,
                                      qty_delta, qty_after, node_time,
                                      kafka_partition, kafka_offset, kafka_ts)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (branch_id, movement_id) DO NOTHING""",
            (e["branch_id"], e["movement_id"], e["product_id"], e["move_type"],
             e["qty_delta"], e["qty_after"], e["node_time"], partition, offset, kafka_ts),
        ).rowcount

        if inserted == 0:  # lớp chống trùng thứ nhất
            conn.execute("UPDATE sink_stats SET duplicates = duplicates + 1")
            return "duplicate"

        # Lớp thứ hai: cùng luật merge với gossip và đối soát (PT-10)
        merge_cells(conn, [{"branch_id": e["branch_id"], "product_id": e["product_id"],
                            "qty_on_hand": e["qty_after"], "last_movement": e["movement_id"],
                            "node_time": e["node_time"]}], "kafka")
        conn.execute("UPDATE sink_stats SET processed = processed + 1, last_event_at = now()")
        return "new"


def merge_cells(conn, rows: list[dict], source: str) -> int:
    """Luật merge DUY NHẤT cho mọi kênh cập nhật snapshot (PT-10): sink ('kafka'), gossip, đối soát.

    Mỗi ô (chi nhánh, mã hàng) chỉ bị ghi đè khi movement_id MỚI HƠN cái đang có. So bằng movement_id
    chứ KHÔNG bằng node_time: đồng hồ các máy lệch nhau, còn movement_id do chính chi nhánh tăng dần.
    Luật này giao hoán, kết hợp, lũy đẳng: nhận theo thứ tự nào, nhận trùng, từ kênh nào cũng hội tụ.
    Gọi bên trong transaction của người gọi. Trả số ô thực sự được ghi (mới hoặc vá).
    """
    if not rows:
        return 0
    return conn.execute(
        """INSERT INTO inventory_snapshot (branch_id, product_id, qty_on_hand, last_movement,
                                           node_time, source, updated_at)
           SELECT branch_id, product_id, qty_on_hand, last_movement, node_time, %s, now()
           FROM jsonb_to_recordset(%s) AS r(branch_id int, product_id int, qty_on_hand int,
                                           last_movement bigint, node_time timestamptz)
           ON CONFLICT (branch_id, product_id) DO UPDATE
           SET qty_on_hand   = EXCLUDED.qty_on_hand,
               last_movement = EXCLUDED.last_movement,
               node_time     = EXCLUDED.node_time,
               source        = EXCLUDED.source,
               updated_at    = now()
           WHERE inventory_snapshot.last_movement < EXCLUDED.last_movement""",
        (source, Jsonb(rows)),
    ).rowcount


# ---------------------------------------------------------------------------
# 1b. Kênh trực tiếp (vòng 3). workers/gossip.py gọi mạng TRƯỚC, rồi đưa dữ liệu đã lấy về vào đây.
# ---------------------------------------------------------------------------
def query_snapshot(conn) -> list[dict]:
    """Mọi ô của bảng tổng hợp kèm last_movement, cho bản sao khác gossip (GET /api/snapshot)."""
    return conn.execute(
        """SELECT branch_id, product_id, qty_on_hand, last_movement, node_time
           FROM inventory_snapshot ORDER BY branch_id, product_id"""
    ).fetchall()


def pick_stale(remote: list[dict], local: list[dict],
               pending: dict[tuple[int, int], int]) -> tuple[list[dict], dict[tuple[int, int], int]]:
    """Gossip: chọn ô cần vá từ snapshot của bản sao khác. Hàm thuần, không gọi mạng, không chạm CSDL.

    pending = các ô bản sao kia đi trước ở LẦN KIỂM TRƯỚC (10 giây trước) -> movement_id lúc đó.
    Chỉ vá ô mà bản sao này VẪN chưa tới movement_id đó: sink (kênh chính) đã có cả một vòng để giao mà
    không giao, tức là thật sự thiếu. Sink chậm vài giây (K1) thì không bao giờ bị vá.
    Trả (ô cần vá, kèm giá trị mới nhất của bản sao kia; pending cho lần kiểm sau).
    """
    mine = {(c["branch_id"], c["product_id"]): c["last_movement"] for c in local}
    patch, ahead = [], {}
    for c in remote:
        key = (c["branch_id"], c["product_id"])
        have = mine.get(key, 0)
        if c["last_movement"] <= have:
            continue
        if have < pending.get(key, 0):
            patch.append(c)
        else:
            ahead[key] = c["last_movement"]
    return patch, ahead


def _record_peer_ok(conn, peer: str, channel: str, patched: int) -> None:
    conn.execute(
        """INSERT INTO sync_peer (peer, channel, last_ok_at, cells_patched) VALUES (%s, %s, now(), %s)
           ON CONFLICT (peer) DO UPDATE
           SET last_ok_at = now(), failing_since = NULL,
               cells_patched = sync_peer.cells_patched + EXCLUDED.cells_patched""",
        (peer, channel, patched),
    )


def merge_replica_snapshot(peer: str, rows: list[dict]) -> int:
    """Gossip: merge các ô đã chọn từ bản sao `peer` và ghi lần trao đổi, trong MỘT transaction.
    rows = [] vẫn ghi last_ok_at (hai bên đã khớp). Dữ liệu từ node khác được kiểm trước khi ghi."""
    cells = [SnapshotCell.model_validate(c).model_dump(mode="json") for c in rows]
    with pool.connection() as conn, conn.transaction():
        n = merge_cells(conn, cells, "gossip")
        _record_peer_ok(conn, peer, "gossip", n)
    return n


def merge_branch_snapshot(branch_id: int, payload: dict) -> int:
    """Đối soát: merge snapshot đọc thẳng từ chi nhánh (nguồn sự thật) qua GET /api/snapshot (PT-07)."""
    if payload.get("branch_id") != branch_id:
        raise ValueError(f"gọi CN{branch_id} mà nhận số của CN{payload.get('branch_id')}")
    cells = [SnapshotCell.model_validate({**c, "branch_id": branch_id}).model_dump(mode="json")
             for c in payload["cells"]]
    with pool.connection() as conn, conn.transaction():
        n = merge_cells(conn, cells, "reconcile")
        _record_peer_ok(conn, f"CN{branch_id}", "reconcile", n)
    return n


def record_peer_error(peer: str, channel: str, error: str) -> None:
    """Gọi node khác lỗi: giữ mốc lỗi đầu tiên của đợt và lần được cuối."""
    with pool.connection() as conn:
        conn.execute(
            """INSERT INTO sync_peer (peer, channel, failing_since, last_error) VALUES (%s, %s, now(), %s)
               ON CONFLICT (peer) DO UPDATE
               SET failing_since = coalesce(sync_peer.failing_since, now()), last_error = EXCLUDED.last_error""",
            (peer, channel, error),
        )


def reconcile_targets(conn) -> list[dict]:
    """Chi nhánh cần đối soát NGAY BÂY GIỜ; rỗng nếu chưa tới lúc.

    Chỉ khi sink báo mất broker quá RECONCILE_AFTER_S giây VÀ sink vẫn còn kiểm (chết thì gossip lo),
    và chỉ chi nhánh có heartbeat trong NODE_TIMEOUT_S giây. Mọi mốc so bằng now() của replica_db
    (cùng một đồng hồ); đây là đếm thời gian chờ, không phải so thứ tự sự kiện.
    """
    return conn.execute(
        """SELECT n.branch_id, n.branch_url
           FROM node_status n CROSS JOIN sink_stats s
           WHERE s.broker_ok = false
             AND s.broker_lost_at    < now() - make_interval(secs => %(after)s)
             AND s.broker_checked_at > now() - make_interval(secs => %(stale)s)
             AND n.last_seen         > now() - make_interval(secs => %(alive)s)
             AND n.branch_url IS NOT NULL
           ORDER BY n.branch_id""",
        {"after": RECONCILE_AFTER_S, "stale": SINK_STALE_S, "alive": NODE_TIMEOUT_S},
    ).fetchall()


# ---------------------------------------------------------------------------
# 2. Heartbeat từ các chi nhánh
# ---------------------------------------------------------------------------
def record_heartbeat(hb: Heartbeat) -> None:
    node_time = datetime.fromtimestamp(hb.node_time_ms / 1000, tz=timezone.utc)
    with pool.connection() as conn:
        conn.execute(
            """INSERT INTO node_status (branch_id, branch_name, last_seen, node_time,
                                        outbox_backlog, rtt_ms, branch_url, recovering)
               VALUES (%s, %s, now(), %s, %s, %s, %s, %s)
               ON CONFLICT (branch_id) DO UPDATE
               SET branch_name = EXCLUDED.branch_name, last_seen = now(),
                   node_time = EXCLUDED.node_time, outbox_backlog = EXCLUDED.outbox_backlog,
                   rtt_ms = EXCLUDED.rtt_ms, branch_url = EXCLUDED.branch_url, recovering = EXCLUDED.recovering""",
            (hb.branch_id, hb.branch_name, node_time, hb.outbox_backlog, hb.rtt_ms, hb.branch_url, hb.recovering),
        )


# ---------------------------------------------------------------------------
# 2b. Bộ phát hiện lỗi (vòng 5, PT-13): trạng thái theo tuổi heartbeat, kết luận theo đa số bản sao
# ---------------------------------------------------------------------------
def branch_state(age_s: float) -> str:
    """Tuổi heartbeat (giây) -> ONLINE / SUSPECT / OFFLINE. Timeout không phân biệt được chậm với chết (K14)."""
    if age_s < SUSPECT_AFTER_S:
        return "ONLINE"
    return "SUSPECT" if age_s < NODE_TIMEOUT_S else "OFFLINE"


def majority_state(states: list[str | None], total: int) -> str:
    """Kết luận từ góc nhìn của các bản sao (None = thiếu hoặc cũ). Đa số tính trên TỔNG số bản sao cấu hình, không
    trên số còn trả lời: bản sao bị cô lập (1/1 còn trả lời) không được tự kết luận chi nhánh khác đã chết."""
    quorum = total // 2 + 1
    for s in ("OFFLINE", "ONLINE"):
        if states.count(s) >= quorum:
            return s
    return "SUSPECT"


def record_peer_view(peer: str, payload: dict) -> None:
    """Lưu góc nhìn bản sao `peer` vừa trả qua GET /api/views (view_loop gọi mạng xong rồi mới gọi hàm này).
    Kiểm mọi dòng trước khi ghi: một dòng hỏng thì không ghi dòng nào. Ghi trong MỘT transaction."""
    if payload.get("node") != peer:
        raise ValueError(f"gọi bản sao {peer} mà nhận góc nhìn của {payload.get('node')}")
    views = [BranchView.model_validate(b) for b in payload["branches"]]
    with pool.connection() as conn, conn.transaction(), conn.cursor() as cur:
        cur.executemany(
            """INSERT INTO peer_view (peer, branch_id, state, seconds_since_seen, received_at)
               VALUES (%s, %s, %s, %s, now())
               ON CONFLICT (peer, branch_id) DO UPDATE
               SET state = EXCLUDED.state, seconds_since_seen = EXCLUDED.seconds_since_seen, received_at = now()""",
            [(peer, v.branch_id, v.state, v.seconds_since_seen) for v in views],
        )


# ---------------------------------------------------------------------------
# 2c. Ghi hộ (vòng 6, PT-14): nhận lượt bán khi đa số kết luận chi nhánh OFFLINE; chi nhánh tự kéo về và báo kết quả.
#     Bản sao không ghi vào CSDL chi nhánh (PT-07), chỉ sửa bảng handoff của chính nó.
# ---------------------------------------------------------------------------
def _verdict(conn, branch_id: int) -> str | None:
    """Kết luận đa số (PT-13) của bản sao này về một chi nhánh; None nếu chưa từng nhận heartbeat của nó."""
    return next((n["verdict"] for n in query_nodes(conn) if n["branch_id"] == branch_id), None)


def _pending_qty(conn, branch_id: int, product_id: int) -> int:
    return conn.execute(
        """SELECT coalesce(sum(qty), 0)::int AS q FROM handoff
           WHERE branch_id = %s AND product_id = %s AND status = 'PENDING'""",
        (branch_id, product_id),
    ).fetchone()["q"]


def store_handoff(req: HandoffSale) -> dict:
    """Lưu một lượt ghi hộ, trong MỘT transaction. Khoá ô snapshot trước (FOR UPDATE): hai lượt cùng mã xếp hàng lần
    lượt, nên tồn tạm tính không bị hai lượt cùng đọc một số (như PT-09). Gửi lại cùng request_id trả lượt cũ."""
    with pool.connection() as conn, conn.transaction():
        cell = conn.execute(
            "SELECT qty_on_hand FROM inventory_snapshot WHERE branch_id = %s AND product_id = %s FOR UPDATE",
            (req.branch_id, req.product_id),
        ).fetchone()
        old = conn.execute(
            """SELECT handoff_id, branch_id, product_id, qty, status FROM handoff
               WHERE branch_id = %s AND request_id = %s""",
            (req.branch_id, req.request_id),
        ).fetchone()
        if old is None and _verdict(conn, req.branch_id) != "OFFLINE":
            raise HTTPException(409, {"error": "branch_not_offline"})
        if cell is None:
            raise HTTPException(404, {"error": "product_not_found"})
        provisional = cell["qty_on_hand"] - _pending_qty(conn, req.branch_id, req.product_id)
        if old:
            return {"node": NODE_NAME, **old, "qty_on_hand": provisional, "replayed": True}
        if provisional < req.qty:
            raise HTTPException(422, {"error": "insufficient_stock", "qty_on_hand": provisional})
        row = conn.execute(
            """INSERT INTO handoff (branch_id, request_id, product_id, qty) VALUES (%s, %s, %s, %s)
               RETURNING handoff_id, branch_id, product_id, qty, status""",
            (req.branch_id, req.request_id, req.product_id, req.qty),
        ).fetchone()
    return {"node": NODE_NAME, **row, "qty_on_hand": provisional - req.qty}


def query_handoff(conn, branch_id: int) -> dict:
    """Ghi hộ của một chi nhánh ở bản sao này (GET /api/handoff). Chỉ đọc.
    accepting = còn nhận ghi hộ (kết luận đa số OFFLINE): chi nhánh chưa được ONLINE khi còn bản sao như vậy."""
    pending = conn.execute(
        """SELECT handoff_id, request_id, product_id, qty FROM handoff
           WHERE branch_id = %s AND status = 'PENDING' ORDER BY handoff_id""",
        (branch_id,),
    ).fetchall()
    counts = conn.execute(
        """SELECT count(*) FILTER (WHERE status = 'PENDING')::int  AS pending,
                  count(*) FILTER (WHERE status = 'APPLIED')::int  AS applied,
                  count(*) FILTER (WHERE status = 'REJECTED')::int AS rejected
           FROM handoff WHERE branch_id = %s""",
        (branch_id,),
    ).fetchone()
    # Cùng dạng GET /api/inventory của chi nhánh, để POS dùng chung bảng hàng; qty_on_hand = tồn tạm tính
    stock = conn.execute(
        """SELECT p.product_id, p.name, p.unit, p.reorder_point,
                  s.qty_on_hand - coalesce(h.q, 0)::int AS qty_on_hand, NULL::int AS version
           FROM inventory_snapshot s JOIN product p USING (product_id)
           LEFT JOIN (SELECT product_id, sum(qty) AS q FROM handoff
                      WHERE branch_id = %(b)s AND status = 'PENDING' GROUP BY product_id) h USING (product_id)
           WHERE s.branch_id = %(b)s ORDER BY p.product_id""",
        {"b": branch_id},
    ).fetchall()
    return {"node": NODE_NAME, "branch_id": branch_id, "accepting": _verdict(conn, branch_id) == "OFFLINE",
            "counts": counts, "pending": pending, "stock": stock}


def record_handoff_ack(ack: HandoffAck) -> int:
    """Chi nhánh báo kết quả áp (sau khi đã commit). MỘT câu UPDATE, chỉ đổi lượt còn PENDING của đúng chi nhánh đó:
    ack trùng hay ack muộn không đổi lượt đã chốt. Trả số lượt được đổi."""
    rows = [r.model_dump() for r in ack.results]
    if not rows:
        return 0
    with pool.connection() as conn:
        return conn.execute(
            """UPDATE handoff h
               SET status = r.status, movement_id = r.movement_id, reason = r.reason, decided_at = now()
               FROM jsonb_to_recordset(%s) AS r(handoff_id bigint, status text, movement_id bigint, reason text)
               WHERE h.handoff_id = r.handoff_id AND h.branch_id = %s AND h.status = 'PENDING'""",
            (Jsonb(rows), ack.branch_id),
        ).rowcount


# ---------------------------------------------------------------------------
# 3. Truy vấn cho dashboard. Mọi hàm nhận `conn` để /api/overview gom vào một kết nối.
# ---------------------------------------------------------------------------
def query_nodes(conn):
    """Chi nhánh nào còn sống. Mỗi bản sao tự phán đoán theo heartbeat nó nhận được (`state`, `alive`), nên lúc mạng
    bị chia cắt, hai bản sao có thể thấy khác nhau; `views` ghép góc nhìn của mọi bản sao, `verdict` là kết luận theo
    đa số (PT-13)."""
    rows = conn.execute(
        """SELECT n.branch_id, n.branch_name, n.outbox_backlog, n.rtt_ms, n.last_seen, n.recovering,
                  n.last_seen > now() - make_interval(secs => %s)      AS alive,
                  round(extract(epoch FROM now() - n.last_seen))::int  AS seconds_since_seen,
                  extract(epoch FROM now() - n.last_seen)::float       AS age_s,
                  -- giờ chi nhánh trừ giờ bản sao lúc nhận heartbeat.
                  -- Gồm cả lệch đồng hồ lẫn thời gian gói tin đi trên mạng.
                  round(extract(epoch FROM n.node_time - n.last_seen) * 1000)::int AS clock_offset_ms,
                  s.snapshot_updated_at, s.last_movement
           FROM node_status n
           LEFT JOIN (SELECT branch_id, max(updated_at) AS snapshot_updated_at,
                             max(last_movement) AS last_movement
                      FROM inventory_snapshot GROUP BY branch_id) s USING (branch_id)
           ORDER BY n.branch_id""",
        (NODE_TIMEOUT_S,),
    ).fetchall()
    # Góc nhìn của bản sao khác còn mới (cùng đồng hồ replica_db: đo thời gian chờ, không so thứ tự sự kiện)
    peers = {(r["peer"], r["branch_id"]): r["state"] for r in conn.execute(
        "SELECT peer, branch_id, state FROM peer_view WHERE received_at > now() - make_interval(secs => %s)",
        (VIEW_STALE_S,),
    ).fetchall()}
    names = REPLICA_NAMES or [NODE_NAME]
    for n in rows:
        n["state"] = branch_state(n.pop("age_s"))
        n["views"] = {name: n["state"] if name == NODE_NAME else peers.get((name, n["branch_id"])) for name in names}
        n["verdict"] = majority_state(list(n["views"].values()), len(names))
    return rows


def query_views(conn) -> dict:
    """Góc nhìn của CHÍNH bản sao này về từng chi nhánh, cho bản sao khác kéo (GET /api/views, PT-13). Chỉ đọc."""
    rows = conn.execute(
        """SELECT branch_id, extract(epoch FROM now() - last_seen)::float AS age_s
           FROM node_status ORDER BY branch_id"""
    ).fetchall()
    return {"node": NODE_NAME, "branches": [
        {"branch_id": r["branch_id"], "state": branch_state(r["age_s"]),
         "seconds_since_seen": max(0, round(r["age_s"]))} for r in rows]}


def query_inventory(conn):
    """Tồn toàn chuỗi. Người xem thấy MỘT bảng, không cần biết số đến từ máy nào."""
    rows = conn.execute(
        """SELECT p.product_id, p.name, p.unit, p.reorder_point,
                  s.branch_id, s.qty_on_hand, s.updated_at, s.source, s.last_movement
           FROM product p
           LEFT JOIN inventory_snapshot s USING (product_id)
           ORDER BY p.product_id, s.branch_id"""
    ).fetchall()
    products: dict[int, dict] = {}
    for r in rows:
        p = products.setdefault(r["product_id"], {
            "product_id": r["product_id"], "name": r["name"], "unit": r["unit"],
            "reorder_point": r["reorder_point"], "total": 0, "by_branch": {},
        })
        if r["branch_id"] is not None:
            p["by_branch"][r["branch_id"]] = {
                "qty": r["qty_on_hand"],
                "below_reorder": r["qty_on_hand"] < r["reorder_point"],
                "updated_at": r["updated_at"],
                "source": r["source"],  # 'reconcile' -> dashboard gắn nhãn "qua đối soát"
                "last_movement": r["last_movement"],  # phiên bản của ô, để dashboard đọc đơn điệu
            }
            p["total"] += r["qty_on_hand"]
    return list(products.values())


def query_events(conn, limit=30):
    return conn.execute(
        """SELECT e.*, p.name AS product_name,
                  -- trễ từ lúc chi nhánh ghi nhận tới lúc bản sao này nhận được
                  round(extract(epoch FROM e.received_at - e.node_time) * 1000)::int AS lag_ms
           FROM event_log e JOIN product p USING (product_id)
           WHERE e.move_type <> 'INIT'
           ORDER BY e.received_at DESC, e.movement_id DESC
           LIMIT %s""",
        (min(limit, 200),),
    ).fetchall()


def query_digest(conn):
    """Bản tóm tắt để SO SÁNH các bản sao với nhau.

    fingerprint = mã băm của toàn bộ bảng tổng hợp. Hai bản sao có cùng
    fingerprint nghĩa là chúng giữ ĐÚNG cùng một số liệu, đến từng ô.
    """
    d = conn.execute(
        """SELECT coalesce(sum(qty_on_hand), 0)::int AS total_qty,
                  count(*)::int AS rows,
                  md5(coalesce(string_agg(branch_id || ':' || product_id || ':' || qty_on_hand,
                                          ',' ORDER BY branch_id, product_id), '')) AS fingerprint
           FROM inventory_snapshot"""
    ).fetchone()
    d["last_movement_by_branch"] = {
        r["branch_id"]: r["m"] for r in conn.execute(
            "SELECT branch_id, max(last_movement) AS m FROM inventory_snapshot GROUP BY branch_id"
        ).fetchall()
    }
    d.update(query_stats(conn))
    # Lần trao đổi trực tiếp cuối với từng bản sao (gossip) và chi nhánh (đối soát)
    d["sync_peers"] = conn.execute(
        """SELECT peer, channel, last_ok_at, failing_since, last_error, cells_patched
           FROM sync_peer ORDER BY channel, peer"""
    ).fetchall()
    # Ghi hộ ở bản sao này theo chi nhánh (vòng 6), để dashboard cộng qua các bản sao
    d["handoff"] = {r.pop("branch_id"): r for r in conn.execute(
        """SELECT branch_id, count(*) FILTER (WHERE status = 'PENDING')::int  AS pending,
                             count(*) FILTER (WHERE status = 'APPLIED')::int  AS applied,
                             count(*) FILTER (WHERE status = 'REJECTED')::int AS rejected
           FROM handoff GROUP BY branch_id ORDER BY branch_id"""
    ).fetchall()}
    d["node"] = NODE_NAME
    d["fingerprint"] = d["fingerprint"][:8]  # 8 ký tự đầu là đủ để so bằng mắt
    return d


def query_stats(conn):
    return conn.execute(
        """SELECT processed, duplicates, last_event_at,
                  broker_ok, broker_lost_at, lag, broker_checked_at, brokers_up
           FROM sink_stats"""
    ).fetchone()


def query_trace(conn, branch_id: int, movement_id: int, product_id: int) -> dict:
    """Bản sao này biết sự kiện (branch_id, movement_id) bằng đường nào (GET /api/trace). Chỉ đọc.

    Ô vá bằng gossip hoặc đối soát không có dòng event_log, nên khi thiếu nhật ký thì suy ra từ ô snapshot:
    ô đã tới movement_id thì sự kiện đã nằm trong số tồn (qua kênh ghi ô), chưa tới thì bản sao chưa biết.
    """
    event = conn.execute(
        """SELECT move_type, qty_delta, qty_after, node_time, received_at,
                  kafka_partition, kafka_offset, kafka_ts
           FROM event_log WHERE branch_id = %s AND movement_id = %s""",
        (branch_id, movement_id),
    ).fetchone()
    cell = conn.execute(
        """SELECT qty_on_hand, last_movement, source, updated_at
           FROM inventory_snapshot WHERE branch_id = %s AND product_id = %s""",
        (branch_id, product_id),
    ).fetchone()
    if event:
        via = "kafka"
    elif cell is None or cell["last_movement"] < movement_id:
        via = "missing"
    else:  # sink chỉ ghi ô kèm dòng nhật ký, nên ô 'kafka' mà thiếu nhật ký nghĩa là sự kiện bị bỏ qua
        via = "superseded" if cell["source"] == "kafka" else cell["source"]
    return {"node": NODE_NAME, "branch_id": branch_id, "movement_id": movement_id,
            "product_id": product_id, "event": event, "cell": cell, "via": via}


# ---------------------------------------------------------------------------
# 4. Trạng thái đường đọc Redpanda (sink gọi mỗi 5 giây, SAU khi đã hỏi Redpanda xong)
# ---------------------------------------------------------------------------
def record_broker_check(ok: bool, lag: int | None, brokers_up: list[int] | None = None) -> None:
    """ok=False: giữ mốc mất broker đầu tiên của đợt này và giữ lag cũ.
    ok=True: xoá mốc mất, ghi lag mới. Dashboard dựa vào đây để báo "Đồng bộ dừng từ HH:MM:SS".
    brokers_up: broker còn sống theo metadata vừa hỏi; None = không hỏi được. Luôn ghi đè, không giữ số cũ."""
    with pool.connection() as conn:
        conn.execute(
            """UPDATE sink_stats
               SET broker_ok = %(ok)s,
                   broker_checked_at = now(),
                   broker_lost_at = CASE WHEN %(ok)s THEN NULL ELSE coalesce(broker_lost_at, now()) END,
                   lag = coalesce(%(lag)s::bigint, lag),
                   brokers_up = %(up)s""",
            {"ok": ok, "lag": lag, "up": brokers_up},
        )
