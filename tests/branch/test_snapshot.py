"""Chi nhánh cho bản sao đọc snapshot để đối soát khi mất broker (vòng 3)."""
from fixtures import count, seed_branch

from common.db import pool


def test_branch_snapshot_matches_inventory_and_ledger(branch_client):
    """PT-07, PT-02: snapshot khớp inventory; last_movement là biến động mới nhất của mã, qty bằng qty_after của nó."""
    stock = seed_branch()
    branch_client.post("/api/sale", json={"product_id": 1, "qty": 2})
    branch_client.post("/api/receipt", json={"product_id": 1, "qty": 5})
    branch_client.post("/api/sale", json={"product_id": 3, "qty": 1})

    r = branch_client.get("/api/snapshot")

    assert r.status_code == 200
    body = r.json()
    assert body["branch_id"] == 1
    with pool.connection() as conn:
        inv = {r["product_id"]: r["qty_on_hand"]
               for r in conn.execute("SELECT product_id, qty_on_hand FROM inventory").fetchall()}
        last = {r["product_id"]: (r["movement_id"], r["qty_after"]) for r in conn.execute(
            """SELECT DISTINCT ON (product_id) product_id, movement_id, qty_after
               FROM stock_movement ORDER BY product_id, movement_id DESC""").fetchall()}
    cells = {c["product_id"]: c for c in body["cells"]}
    assert cells.keys() == inv.keys()
    for pid, c in cells.items():
        assert c["qty_on_hand"] == inv[pid] == last[pid][1]
        assert c["last_movement"] == last[pid][0]
        assert c["node_time"] is not None
    assert cells[1]["qty_on_hand"] == stock[1] + 3


def test_branch_snapshot_writes_nothing(branch_client):
    """PT-07: bản sao đọc chi nhánh qua API, lời gọi đó không ghi gì vào CSDL chi nhánh."""
    seed_branch()
    before = (count("stock_movement"), count("outbox"))
    with pool.connection() as conn:
        versions = conn.execute("SELECT sum(version) AS v FROM inventory").fetchone()["v"]

    assert branch_client.get("/api/snapshot").status_code == 200

    assert (count("stock_movement"), count("outbox")) == before
    with pool.connection() as conn:
        assert conn.execute("SELECT sum(version) AS v FROM inventory").fetchone()["v"] == versions
