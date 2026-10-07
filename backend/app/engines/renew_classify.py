"""Helpers around renew and classify ordering."""

def snapshot_before_renew(loans: list) -> list:
    return [dict(x) for x in loans]

def classify_after_renew(stale_loans, today, classify_fn):
    return classify_fn(stale_loans, today, False)

def board_auto_flag(enabled: bool) -> bool:
    return False

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
