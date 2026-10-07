"""跨日自动续借 / 逾期扫 / 开关注入 / 零点叠单 的回归闸。

每条测试对应一条线上约定：
1. 跨日后续借闸把仍 active 的应还日补到当天，看板与借还记录同一套数；
2. 逾期扫带现行开关，不得按跨日前日子把已续行标进逾期段；
3. 零点抢借与归还叠单不得留下 items.on_loan 而 loans 无 active；
4. 关闭续借后不得再过夜加一天；
5. 开开关与跨日作业叠上不得只改栏不改扫；
6. 2020 样例在开关注入下与现行开关同一世界；
7. 续借设置与分栏入口还在。
"""
import os
import threading

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.db import connect
from app.engines import renew_classify as rc
from app.engines.borrow_rules import classify_loans

DAY0 = "2026-10-06"
DAY1 = "2026-10-07"
DAY2 = "2026-10-08"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("BOARD_TODAY", DAY0)
    with TestClient(app) as c:
        yield c


def set_day(monkeypatch, day):
    monkeypatch.setenv("BOARD_TODAY", day)


def _lend_one(c, title="电钻X", due=DAY0):
    iid = c.post("/api/items", json={"title": title, "owner": "老周"}).json()["id"]
    r = c.post(f"/api/items/{iid}/lend", json={"borrower": "邻居", "due_date": due})
    assert r.status_code == 200, r.text
    return iid, r.json()["loan_id"]


def _assert_board_self_consistent(b, today):
    """同一响应内：顶细条计数 == 分栏列表；在借栏 due >= today；逾期段 due < today。"""
    assert b["counts"]["available"] == len(b["available"])
    assert b["counts"]["active"] == len(b["active"])
    assert b["counts"]["overdue"] == len(b["overdue"])
    for l in b["active"]:
        assert l["due_date"] >= today, f"在借栏出现旧 due：{l}"
        assert l["overdue"] is False
    for l in b["overdue"]:
        assert l["due_date"] < today, f"逾期段出现新 due：{l}"
        assert l["overdue"] is True


def _assert_item_loan_consistent():
    """items.on_loan ⟺ 恰好一笔 active loan；available ⟺ 无 active。"""
    with connect() as c:
        assert not c.execute(
            """SELECT 1 FROM items i WHERE i.status='on_loan' AND NOT EXISTS(
                 SELECT 1 FROM loans l WHERE l.item_id=i.id AND l.status='active')"""
        ).fetchall()
        assert not c.execute(
            """SELECT 1 FROM items i WHERE i.status='available' AND EXISTS(
                 SELECT 1 FROM loans l WHERE l.item_id=i.id AND l.status='active')"""
        ).fetchall()
        assert not c.execute(
            "SELECT 1 FROM loans WHERE status='active' GROUP BY item_id HAVING COUNT(*)>1"
        ).fetchall()


# 1 + 2：跨日续借后，在借栏是新 due，逾期扫不得再按跨日前日子标逾期
def test_cross_day_board_and_scan_same_world(client, monkeypatch):
    client.post("/api/settings", json={"auto_renew": True})
    _lend_one(client, due=DAY0)

    set_day(monkeypatch, DAY1)
    b = client.get("/api/board").json()
    _assert_board_self_consistent(b, DAY1)
    assert b["counts"]["overdue"] == 0
    mine = [l for l in b["active"] if l["title"] == "电钻X"]
    assert len(mine) == 1 and mine[0]["due_date"] == DAY1
    assert mine[0]["renewed"] and mine[0]["renewals"] == 1

    # 借还记录与顶细条同走一把扫：同一行不得一边在借一边逾期
    loans = client.get("/api/loans").json()
    assert {l["id"] for l in loans["overdue"]} == {l["id"] for l in b["overdue"]}
    assert {l["id"] for l in loans["active"]} == {l["id"] for l in b["active"]}
    assert all(l["due_date"] >= DAY1 for l in loans["active"])

    set_day(monkeypatch, DAY2)
    b2 = client.get("/api/board").json()
    _assert_board_self_consistent(b2, DAY2)
    assert b2["counts"]["overdue"] == 0
    assert [l for l in b2["active"] if l["title"] == "电钻X"][0]["due_date"] == DAY2


# 4：关闭续借后不得再过夜加一天
def test_switch_off_stops_overnight_renew(client, monkeypatch):
    client.post("/api/settings", json={"auto_renew": True})
    _lend_one(client, due=DAY0)
    set_day(monkeypatch, DAY1)
    assert client.get("/api/board").json()["counts"]["overdue"] == 0  # 已续到 DAY1

    r = client.post("/api/settings", json={"auto_renew": False}).json()
    assert r["renewed"] == 0
    set_day(monkeypatch, DAY2)
    b = client.get("/api/board").json()
    _assert_board_self_consistent(b, DAY2)
    mine = [l for l in b["overdue"] if l["title"] == "电钻X"]
    assert len(mine) == 1
    assert mine[0]["due_date"] == DAY1  # 停在关开关那天，不再加
    loans = client.get("/api/loans").json()
    assert {l["id"] for l in loans["overdue"]} == {l["id"] for l in b["overdue"]}


# 5 + 6：开关注入与跨日作业同世界；2020 样例同一世界
def test_toggle_injection_same_world_as_seed_2020(client, monkeypatch):
    # 默认关：2020 样例算逾期
    b = client.get("/api/board").json()
    assert any(l["title"] == "已外借样例" for l in b["overdue"])

    # 开关注入：同一事务补续存量，响应即知笔数；栏与扫随即同世界
    r = client.post("/api/settings", json={"auto_renew": True}).json()
    assert r["settings"]["auto_renew"] == "true"
    assert r["renewed"] >= 1
    b = client.get("/api/board").json()
    _assert_board_self_consistent(b, DAY0)
    sample = [l for l in b["active"] if l["title"] == "已外借样例"]
    assert len(sample) == 1 and sample[0]["due_date"] == DAY0 and sample[0]["renewed"]
    loans = client.get("/api/loans").json()
    assert not [l for l in loans["overdue"] if l["title"] == "已外借样例"]

    # 跨日作业叠上：样例随现行开关继续续，不得落回逾期段
    set_day(monkeypatch, DAY1)
    b = client.get("/api/board").json()
    _assert_board_self_consistent(b, DAY1)
    sample = [l for l in b["active"] if l["title"] == "已外借样例"]
    assert len(sample) == 1 and sample[0]["due_date"] == DAY1


# 3：归还/借出叠单不得留下 items.on_loan 而 loans 无 active
def test_return_and_lend_are_atomic(client):
    iid, lid = _lend_one(client)
    # 重复借出同一件：被拒，且仍只有一笔 active
    r = client.post(f"/api/items/{iid}/lend", json={"borrower": "别人", "due_date": DAY0})
    assert r.status_code == 409
    # 归还：两条条件更新同生共死
    assert client.post(f"/api/loans/{lid}/return").status_code == 200
    _assert_item_loan_consistent()
    # 再还一次：不得把 available 误盖、不得留下半吊子状态
    assert client.post(f"/api/loans/{lid}/return").status_code in (400, 409)
    _assert_item_loan_consistent()
    items = {i["id"]: i for i in client.get("/api/items").json()}
    assert items[iid]["status"] == "available"


def test_midnight_lend_return_overlap(client, monkeypatch):
    client.post("/api/settings", json={"auto_renew": True})
    ids = [client.post("/api/items", json={"title": f"物{k}", "owner": "甲"}).json()["id"]
           for k in range(4)]
    failures = []

    def worker(n):
        c = TestClient(app)
        for it in range(20):
            iid = ids[(n + it) % len(ids)]
            try:
                if it % 2 == 0:
                    c.post(f"/api/items/{iid}/lend", json={"borrower": f"人{n}", "due_date": DAY1})
                else:
                    loans = c.get("/api/loans").json()
                    for l in loans["active"] + loans["overdue"]:
                        if l["item_id"] == iid:
                            c.post(f"/api/loans/{l['id']}/return")
                            break
                r = c.get("/api/board")
                if r.status_code >= 500:
                    failures.append(r.status_code)
            except Exception as e:  # 请求级异常（如锁超时）也算失败
                failures.append(repr(e))

    ts = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert not failures, failures
    _assert_item_loan_consistent()


# 5（并发版）：开开关与跨日作业叠上，每个响应都栏扫一致
def test_toggle_racing_cross_day_never_splits_column_from_scan(client, monkeypatch):
    for k in range(3):
        _lend_one(client, title=f"物{k}", due=DAY0)
    set_day(monkeypatch, DAY1)
    bad = []

    def toggler():
        c = TestClient(app)
        for i in range(10):
            c.post("/api/settings", json={"auto_renew": i % 2 == 0})

    def reader():
        c = TestClient(app)
        for _ in range(25):
            r = c.get("/api/board")
            if r.status_code != 200:
                bad.append(r.status_code)
                continue
            b = r.json()
            try:
                _assert_board_self_consistent(b, DAY1)
            except AssertionError as e:
                bad.append(str(e))

    ts = [threading.Thread(target=toggler)] + [threading.Thread(target=reader) for _ in range(3)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert not bad, bad[:3]


# 2（单元）：逾期扫必须跟现行开关，不得硬按跨日前日子
def test_scan_honors_live_switch():
    rows = [{"id": 1, "item_id": 1, "status": "active", "due_date": DAY0, "renewals": 0}]
    on = rc.classify_after_renew([dict(r) for r in rows], DAY1, classify_loans, True)
    assert not on["overdue"] and len(on["active"]) == 1
    assert on["active"][0]["due_date"] == DAY1 and on["active"][0]["renewed"]
    off = rc.classify_after_renew([dict(r) for r in rows], DAY1, classify_loans, False)
    assert not off["active"] and len(off["overdue"]) == 1
    assert rc.board_auto_flag(True) is True
    assert rc.board_auto_flag(False) is False


# 7：续借设置与分栏入口还在
def test_settings_and_sectioned_entries_still_there(client):
    s = client.get("/api/settings").json()
    assert "auto_renew" in s
    b = client.get("/api/board").json()
    for key in ("available", "active", "overdue", "counts"):
        assert key in b
    loans = client.get("/api/loans").json()
    for key in ("active", "overdue", "returned"):
        assert key in loans


# 脏数据：录错的应还日不得把整板扫名单打崩
def test_dirty_due_date_degrades_not_crashes(client):
    _lend_one(client, title="脏日子", due="2026-1O-O7")  # 字母 O 混进日期
    r = client.get("/api/board")
    assert r.status_code == 200
    b = r.json()
    assert any(l["title"] == "脏日子" for l in b["active"] + b["overdue"])
    assert client.get("/api/loans").status_code == 200
