"""真并发风暴：httpx ASGITransport 走 FastAPI 线程池，今天与开关可在飞行中改。

不依赖外部观察开关状态的单响应不变量（固定日期 D 时，无论开关）：
  counts == 列表长度；同一行不同时进两栏；
  逾期行 due < D；在借行 due >= D  —— 即"栏与扫跟同一天"。
另查库：on_loan 恰有一笔 active；available 无 active。
"""
import asyncio, os, tempfile, sqlite3, random, threading
import pytest

day = {"v": "2020-06-02"}
sw = {"v": True}

@pytest.fixture()
def world(monkeypatch):
    d = tempfile.mkdtemp()
    monkeypatch.setenv("DATA_DIR", d)
    from app import main as M
    from app.db import db_path
    monkeypatch.setattr(M, "today_iso", lambda: day["v"])
    # 让开关也能在飞行中翻：settings 表为持久真源，这里只做初始写
    from fastapi.testclient import TestClient
    with TestClient(M.app) as c:
        c.post("/api/settings", json={"auto_renew": True})
        for i in range(8):
            c.post("/api/items", json={"title": f"物{i}", "owner": "主"})
        for it in c.get("/api/items").json()[::2]:
            c.post(f"/api/items/{it['id']}/lend",
                   json={"borrower": "甲", "due_date": "2020-06-01"})
    yield M, db_path()

def test_concurrent_cross_midnight(world):
    M, path = world
    import httpx
    violations = []
    vlock = threading.Lock()

    async def run():
        transport = httpx.ASGITransport(app=M.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
            rnd = random.Random(42)

            async def board_check():
                r = await c.get("/api/board")
                D = day["v"]
                b = r.json()
                if b["counts"]["active"] != len(b["active"]) or \
                   b["counts"]["overdue"] != len(b["overdue"]):
                    with vlock: violations.append(("counts", b["counts"], len(b["active"]), len(b["overdue"])))
                ids = [x["id"] for x in b["active"]] + [x["id"] for x in b["overdue"]]
                if len(ids) != len(set(ids)):
                    with vlock: violations.append(("dup row", ids))
                for x in b["overdue"]:
                    if not (x["due_date"] and x["due_date"] < D):
                        with vlock: violations.append(("overdue due>=D", D, x["id"], x["due_date"]))
                for x in b["active"]:
                    if x["due_date"] < D:
                        with vlock: violations.append(("active due<D", D, x["id"], x["due_date"]))

            async def loans_check():
                r = await c.get("/api/loans")
                D = day["v"]
                l = r.json()
                for x in l["overdue"]:
                    if not (x["due_date"] and x["due_date"] < D):
                        with vlock: violations.append(("loans overdue due>=D", D, x["id"], x["due_date"]))
                for x in l["active"]:
                    if x["due_date"] < D:
                        with vlock: violations.append(("loans active due<D", D, x["id"], x["due_date"]))

            async def lend_one():
                its = (await c.get("/api/items")).json()
                av = [i for i in its if i["status"] == "available"]
                if av:
                    await c.post(f"/api/items/{rnd.choice(av)['id']}/lend",
                                 json={"borrower": "w", "due_date": "2020-06-20"})

            async def return_one():
                act = (await c.get("/api/loans")).json()["active"]
                if act:
                    await c.post(f"/api/loans/{rnd.choice(act)['id']}/return", json={})

            async def toggle():
                sw["v"] = not sw["v"]
                await c.post("/api/settings", json={"auto_renew": sw["v"]})

            async def cross_day():
                day["v"] = {"2020-06-02": "2020-06-03", "2020-06-03": "2020-06-04",
                            "2020-06-04": "2020-06-02"}[day["v"]]

            fns = [board_check, loans_check, lend_one, return_one, toggle, cross_day]
            for _ in range(60):
                batch = [fns[rnd.randrange(len(fns))]() for _ in range(rnd.randrange(3, 8))]
                await asyncio.gather(*batch, return_exceptions=True)

    asyncio.run(run())

    con = sqlite3.connect(path)
    orphan = con.execute(
        "SELECT i.id FROM items i WHERE i.status='on_loan' AND NOT EXISTS "
        "(SELECT 1 FROM loans l WHERE l.item_id=i.id AND l.status='active')").fetchall()
    ghost = con.execute(
        "SELECT i.id FROM items i WHERE i.status='available' AND EXISTS "
        "(SELECT 1 FROM loans l WHERE l.item_id=i.id AND l.status='active')").fetchall()
    double = con.execute(
        "SELECT item_id FROM loans WHERE status='active' GROUP BY item_id HAVING COUNT(*)>1"
    ).fetchall()

    assert not orphan, f"on_loan 无 active: {orphan}"
    assert not ghost, f"available 却有 active: {ghost}"
    assert not double, f"同一物多笔 active: {double}"
    assert not violations, f"响应不自洽 {violations[:10]} (共{len(violations)})"
