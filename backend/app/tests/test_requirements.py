"""把用户的六句话逐句翻成断言。"""
import os, sqlite3, tempfile
import pytest

@pytest.fixture()
def client(monkeypatch):
    d = tempfile.mkdtemp()
    monkeypatch.setenv("DATA_DIR", d)
    monkeypatch.setenv("BOARD_TODAY", "2020-06-02")
    from fastapi.testclient import TestClient
    from app.main import app
    from app.db import db_path
    with TestClient(app) as c:
        yield c, db_path()

def db(db_path):
    con = sqlite3.connect(db_path); con.row_factory = sqlite3.Row
    return con

# 句1: 跨日之后，开关打开，在借栏是新 due；逾期扫不得再按跨日前日子标逾期；顶细条数同步
def test_cross_midnight_renew_then_no_overdue(client):
    c, p = client
    r = c.post("/api/settings", json={"auto_renew": True}).json()
    assert r["renewed"] == 1                      # 2020 样例被注入续借
    b = c.get("/api/board").json()
    assert b["counts"] == {"available": 3, "active": 1, "overdue": 0}
    assert len(b["active"]) == 1 and b["active"][0]["due_date"] == "2020-06-02"
    assert b["overdue"] == []
    l = c.get("/api/loans").json()
    assert [x["due_date"] for x in l["active"]] == ["2020-06-02"]
    assert l["overdue"] == []

# 句1b: 不经过 settings，仅跨日后首次打开看板也须续借并同世界
def test_cross_midnight_via_board_only(client):
    c, p = client
    c.post("/api/settings", json={"auto_renew": True})
    os.environ["BOARD_TODAY"] = "2020-06-03"
    b = c.get("/api/board").json()
    assert b["counts"]["overdue"] == 0
    assert b["active"][0]["due_date"] == "2020-06-03"

# 句3: 关闭续借后不得再过夜加一天；逾期按现算
def test_off_does_not_advance(client):
    c, p = client
    c.post("/api/settings", json={"auto_renew": True})   # 续到 06-02
    c.post("/api/settings", json={"auto_renew": False})
    os.environ["BOARD_TODAY"] = "2020-06-03"
    c.get("/api/board")
    row = db(p).execute("SELECT due_date,renewals FROM loans WHERE id=1").fetchone()
    assert row["due_date"] == "2020-06-02"               # 不得再加一天
    assert row["renewals"] == 1
    b = c.get("/api/board").json()
    assert b["counts"] == {"available": 3, "active": 0, "overdue": 1}
    assert b["overdue"][0]["due_date"] == "2020-06-02"

# 句2: 并发抢借同一物，不得 items=on_loan 而无 active loan；不得两笔 active
def test_concurrent_lend(client):
    import threading
    c, p = client
    iid = db(p).execute("SELECT id FROM items WHERE title='电钻'").fetchone()[0]
    results = []
    def lend(who):
        from fastapi.testclient import TestClient
        from app.main import app
        cc = TestClient(app)
        r = cc.post(f"/api/items/{iid}/lend",
                    json={"borrower": who, "due_date": "2020-06-10"})
        results.append(r.status_code)
        cc.close()
    ts = [threading.Thread(target=lend, args=(w,)) for w in "甲乙丙丁"]
    for t in ts: t.start()
    for t in ts: t.join()
    con = db(p)
    n = con.execute("SELECT COUNT(*) c FROM loans WHERE item_id=? AND status='active'",
                    (iid,)).fetchone()["c"]
    st = con.execute("SELECT status FROM items WHERE id=?", (iid,)).fetchone()[0]
    assert sorted(results).count(200) == 1
    assert n == 1 and st == "on_loan"

# 句2b: 并发借出与归还叠单，不留 on_loan 配空 active
def test_concurrent_lend_return(client):
    import threading, random
    c, p = client
    errors = []
    def cycle(wid):
        from fastapi.testclient import TestClient
        from app.main import app
        cc = TestClient(app); rnd = random.Random(wid)
        for _ in range(30):
            try:
                con0 = db(p)
                iid = rnd.choice([r[0] for r in con0.execute("SELECT id FROM items")])
                st = con0.execute("SELECT status FROM items WHERE id=?", (iid,)).fetchone()[0]
                if st == "available":
                    cc.post(f"/api/items/{iid}/lend",
                            json={"borrower": "x", "due_date": "2020-06-10"})
                else:
                    lid = con0.execute(
                        "SELECT id FROM loans WHERE item_id=? AND status='active' LIMIT 1",
                        (iid,)).fetchone()
                    if lid:
                        cc.post(f"/api/loans/{lid[0]}/return", json={})
            except Exception as e:
                errors.append(e)
        cc.close()
    ts = [threading.Thread(target=cycle, args=(i,)) for i in range(6)]
    for t in ts: t.start()
    for t in ts: t.join()
    con = db(p)
    orphan = con.execute(
        "SELECT i.id FROM items i WHERE i.status='on_loan' AND NOT EXISTS "
        "(SELECT 1 FROM loans l WHERE l.item_id=i.id AND l.status='active')").fetchall()
    double = con.execute(
        "SELECT item_id FROM loans WHERE status='active' GROUP BY item_id HAVING COUNT(*)>1"
    ).fetchall()
    assert orphan == [] and double == []

# 句4/句5: 开关 ON 时每次响应 active 行 due>=today；开关与扫同一世界
def test_switch_and_sweep_same_world(client):
    c, p = client
    c.post("/api/settings", json={"auto_renew": True})
    for day in ("2020-06-03", "2020-06-04", "2020-06-10"):
        os.environ["BOARD_TODAY"] = day
        b = c.get("/api/board").json()
        assert b["counts"]["overdue"] == 0, day
        assert all(x["due_date"] == day for x in b["active"]), day
        l = c.get("/api/loans").json()
        assert {x["id"] for x in l["overdue"]} == set()
        assert {x["id"] for x in l["active"]} == {x["id"] for x in b["active"]}
