"""One active loan per item + overdue detection.

单一事实源：应还日是否需要自动续借、借据是否逾期，全部由
``effective_due_date`` 决定。持久化续借（main.apply_renewals）与逾期分类
（classify_loans）调用同一个函数，不允许各自再算一遍（"两套数"）。
"""
from datetime import date as _date

def _parse(s: str):
    # 脏数据（自由文本录错的日子）按"无日期"降级，不得让整板扫名单崩掉
    if not s:
        return None
    try:
        return _date.fromisoformat(s)
    except (ValueError, TypeError):
        return None

def effective_due_date(due_date: str, today: str, auto_renew: bool) -> str | None:
    """开关打开且已过应还日的 active 借据：越过几个午夜就补几天，

    结果恰好停在 today（跨日边界当天 due==today 不动；due+1 补成 due+1）。
    开关关闭时原样返回，逾期仍由 is_overdue 现算。
    """
    due = _parse(due_date)
    if due is None:
        return due_date or None
    now = _parse(today)
    if auto_renew and due < now:
        return (due + (now - due)).isoformat()
    return due_date

def can_lend(item_status: str, active_loans: int) -> dict:
    if item_status != "available":
        return {"ok": False, "reason": "item_not_available"}
    if active_loans > 0:
        return {"ok": False, "reason": "already_on_loan"}
    return {"ok": True, "reason": ""}

def is_overdue(due_date: str, today: str, loan_status: str) -> bool:
    if loan_status != "active":
        return False
    return bool(due_date) and due_date < today

def classify_loans(loans: list[dict], today: str, auto_renew: bool = False) -> dict:
    """按同一规则分类。auto_renew 打开时，借据上的 due_date 先经

    effective_due_date 归一（并标 renewed=True），之后只判一次，
    不存在"先标逾期再改回来"的中间状态。
    """
    active, overdue, returned = [], [], []
    for L in loans:
        st = L.get("status")
        if st == "returned":
            returned.append(L)
            continue
        due = L.get("due_date")
        eff = effective_due_date(due, today, auto_renew) if st == "active" else due
        # renewals>0 表示此前零点已持久续借过；eff!=due 表示本次扫名单当场归一
        renewed = bool((L.get("renewals") or 0) > 0 or (eff and eff != due))
        row = {**L, "due_date": eff, "renewed": renewed}
        if is_overdue(eff, today, st):
            overdue.append({**row, "overdue": True})
        elif st == "active":
            active.append({**row, "overdue": False})
    return {"active": active, "overdue": overdue, "returned": returned}
