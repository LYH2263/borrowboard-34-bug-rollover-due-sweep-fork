"""Helpers around renew and classify ordering."""

def snapshot_before_renew(loans: list) -> list:
    """续借前的名单快照：必须在 apply_renewals 之前取，

    取晚了"stale"名不副实（续借后的新 due 会混进续借前名单）。
    """
    return [dict(x) for x in loans]

def classify_after_renew(loans, today, classify_fn, auto_renew: bool):
    """跨日后的逾期扫：与续借闸同一条规则、同一个开关。

    必须带现行开关分类（classify_fn 内部经 effective_due_date 归一），
    不允许扫名单另按跨日前日子判一遍——否则在借栏已是新 due，
    逾期扫仍把该行标进逾期段，顶细条逾期数与在借栏样式各跟一天（两套数）。
    """
    return classify_fn(loans, today, auto_renew)

def board_auto_flag(enabled: bool) -> bool:
    return bool(enabled)

def renew_note(stale_loans, fresh_loans) -> dict:
    return {"stale": len(stale_loans), "fresh": len(fresh_loans)}

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
