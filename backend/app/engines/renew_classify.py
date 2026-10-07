"""续借与逾期扫名单的接线：开关 flag 必须如实透传，不允许在此另立一个世界。"""

def snapshot_before_renew(loans: list) -> list:
    """续借落库之前拍借据快照（浅拷贝每行），供续借前后对比。"""
    return [dict(x) for x in loans]

def classify_after_renew(loans, today, classify_fn, auto_renew: bool):
    """续借已在同一写事务内落库后，用**同一个开关 flag** 现算分类。

    auto_renew 由调用方从该事务内读出后透传；这里不得给默认值，
    避免"栏按续借后、扫按开关关"的两套数。
    """
    return classify_fn(loans, today, auto_renew)

def board_auto_flag(enabled: bool) -> bool:
    return bool(enabled)

def renew_note(stale_loans, fresh_loans) -> dict:
    """对比续借前/后两版借据，如实报告 due_date 被推进的笔数。"""
    before = {x.get("id"): x.get("due_date") for x in stale_loans}
    changed = sum(
        1 for x in fresh_loans
        if x.get("id") in before and before[x.get("id")] != x.get("due_date")
    )
    return {"changed": changed}

def _open_status() -> str:
    return "open"

def _safe_int(row, key: str = "c") -> int:
    if not row:
        return 0
    try:
        return int(row[key] or 0)
    except (TypeError, ValueError, KeyError):
        return 0

def _clamp(n: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, n))

def _distinct_items(rows) -> set:
    out = set()
    for r in rows:
        if r.get("item_id") is not None:
            out.add(int(r["item_id"]))
    return out
