import os
from datetime import date, datetime, timezone
from contextlib import closing
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from app import seed
from app.db import connect, write_tx
from app.engines.borrow_rules import can_lend, classify_loans, effective_due_date
from app.engines import renew_classify as rc

app = FastAPI(title="Borrowboard", version="0.2.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

@app.on_event("startup")
def _startup(): seed.init_db()

@app.get("/api/health")
def health(): return {"ok": True, "project": "borrowboard"}

def today_iso() -> str:
    # 测试可经 BOARD_TODAY 把时钟拨到跨日边界；缺省走系统当天
    return os.environ.get("BOARD_TODAY") or date.today().isoformat()

def _auto_renew_on(c) -> bool:
    row = c.execute("SELECT value FROM settings WHERE key='auto_renew'").fetchone()
    return bool(row) and row["value"] == "true"

def apply_renewals(c, today: str) -> int:
    """在已持有的写事务内补续。规则直接复用 effective_due_date，

    与 classify_loans 逾期扫名单是同一条规则（不允许两套数）。
    任何异常由外层 write_tx 回滚：due_date 停在失败前。
    返回被续借的借据笔数。
    """
    if not _auto_renew_on(c):
        return 0
    n = 0
    rows = c.execute(
        "SELECT id, due_date FROM loans WHERE status='active' AND due_date < ?",
        (today,)).fetchall()
    for r in rows:
        new_due = effective_due_date(r["due_date"], today, True)
        if new_due != r["due_date"]:
            c.execute("UPDATE loans SET due_date=?, renewals=renewals+1 WHERE id=?",
                      (new_due, r["id"]))
            n += 1
    return n

@app.get("/api/items")
def items():
    with closing(connect()) as c:
        return [dict(r) for r in c.execute("SELECT * FROM items")]

@app.get("/api/board")
def board():
    today = today_iso()
    # 续借与读取在同一个写事务内完成：顶细条拿到的分类一定是续借后的同一套数，
    # 不会先标逾期再改回来；写锁也挡住零点的借出/归还。
    with write_tx() as c:
        # 续借前的名单快照必须在补续之前取，stale 才名符其实
        stale_loans = rc.snapshot_before_renew([dict(r) for r in c.execute(
            """SELECT loans.*, items.title FROM loans JOIN items ON items.id=loans.item_id
               WHERE loans.status='active'""")])
        apply_renewals(c, today)
        auto = _auto_renew_on(c)
        available = [dict(r) for r in c.execute("SELECT * FROM items WHERE status='available'")]
        loans = [dict(r) for r in c.execute(
            """SELECT loans.*, items.title FROM loans JOIN items ON items.id=loans.item_id
               WHERE loans.status='active'""")]
        renew_meta = rc.renew_note(stale_loans, loans)
    # 逾期扫带现行开关：与续借闸同一条规则，栏与扫同一世界
    cls = rc.classify_after_renew(loans, today, classify_loans, auto)
    return {
        "available": available,
        "active": cls["active"],
        "overdue": cls["overdue"],
        "counts": {"available": len(available), "active": len(cls["active"]), "overdue": len(cls["overdue"])},
        "renew_meta": renew_meta,
    }

class ItemIn(BaseModel):
    title: str
    owner: str

@app.post("/api/items")
def add_item(body: ItemIn):
    with write_tx() as c:
        cur = c.execute("INSERT INTO items(title,owner,status,data_quality) VALUES (?,?,?,?)",
                        (body.title, body.owner, "available", "clean"))
        iid = cur.lastrowid
    return {"id": iid}

class LendIn(BaseModel):
    borrower: str
    due_date: str

@app.post("/api/items/{iid}/lend")
def lend(iid: int, body: LendIn):
    today = today_iso()
    with write_tx() as c:
        # 写锁内复检，挡住自动续借/归还事务的中间状态
        apply_renewals(c, today)
        item = c.execute("SELECT * FROM items WHERE id=?", (iid,)).fetchone()
        if not item: raise HTTPException(404, "item")
        active_n = c.execute(
            "SELECT COUNT(*) c FROM loans WHERE item_id=? AND status='active'", (iid,)).fetchone()["c"]
        check = can_lend(item["status"], active_n)
        if not check["ok"]:
            raise HTTPException(409, check["reason"])
        cur = c.execute(
            "INSERT INTO loans(item_id,borrower,status,due_date,lent_at,renewals) VALUES (?,?,?,?,?,0)",
            (iid, body.borrower, "active", body.due_date, datetime.now(timezone.utc).isoformat()))
        # 条件更新兜底：只有仍是 available 才落 on_loan，杜绝同一物两笔 active
        upd = c.execute("UPDATE items SET status='on_loan' WHERE id=? AND status='available'", (iid,))
        if upd.rowcount != 1:
            raise HTTPException(409, "item_not_available")
        lid = cur.lastrowid
    return {"loan_id": lid}

@app.post("/api/loans/{lid}/return")
def return_loan(lid: int):
    with write_tx() as c:
        loan = c.execute("SELECT * FROM loans WHERE id=?", (lid,)).fetchone()
        if not loan: raise HTTPException(404, "loan")
        if loan["status"] != "active":
            raise HTTPException(400, "not_active")
        # 两条条件更新同生共死：借据置 returned 与物品回 available 原子提交，
        # 不会留下 on_loan 配空 loans、也不会把 available 误盖。
        u1 = c.execute(
            "UPDATE loans SET status='returned', returned_at=? WHERE id=? AND status='active'",
            (datetime.now(timezone.utc).isoformat(), lid))
        u2 = c.execute(
            "UPDATE items SET status='available' WHERE id=? AND status='on_loan'",
            (loan["item_id"],))
        if u1.rowcount != 1 or u2.rowcount != 1:
            raise HTTPException(409, "state_changed")
    return {"ok": True}

@app.get("/api/loans")
def loans():
    today = today_iso()
    with write_tx() as c:
        apply_renewals(c, today)
        auto = _auto_renew_on(c)
        rows = [dict(r) for r in c.execute(
            "SELECT loans.*, items.title FROM loans JOIN items ON items.id=loans.item_id ORDER BY loans.id DESC")]
    # 与 /api/board 同一把扫：续借后的名单 + 现行开关，两个出口不得两套数
    return rc.classify_after_renew(rows, today, classify_loans, auto)

@app.get("/api/settings")
def get_settings():
    with closing(connect()) as c:
        return {r["key"]: r["value"] for r in c.execute("SELECT * FROM settings")}

class SettingsIn(BaseModel):
    auto_renew: bool

@app.post("/api/settings")
def update_settings(body: SettingsIn):
    today = today_iso()
    # 注入规则写进开关提交本身：upsert 开关与对存量借据补续在同一事务，
    # 2020 样例在开关打开的同一刻续到当天；失败整体回滚，开关与 due_date 都不动。
    with write_tx() as c:
        c.execute(
            "INSERT INTO settings(key,value) VALUES('auto_renew',?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            ("true" if body.auto_renew else "false",))
        renewed = apply_renewals(c, today)
        out = {r["key"]: r["value"] for r in c.execute("SELECT * FROM settings")}
    return {"settings": out, "renewed": renewed}
