"""引擎层契约：续借与逾期扫必须是同一套数。

这些用例钉死开关 flag 必须如实透传——旧实现把 classify_after_renew 的
auto_renew 硬编码成 False、board_auto_flag 恒 False，会在此失败。
"""
from datetime import date, timedelta

from app.engines.borrow_rules import classify_loans, effective_due_date
from app.engines import renew_classify as rc

TODAY = "2026-10-07"


def _loan(iid, due, status="active", renewals=0):
    return {"id": iid, "item_id": iid, "title": f"物{iid}", "borrower": "甲",
            "status": status, "due_date": due, "renewals": renewals}


def test_effective_due_advances_to_today_when_on():
    assert effective_due_date("2026-10-05", TODAY, True) == TODAY


def test_effective_due_unchanged_when_off():
    assert effective_due_date("2026-10-05", TODAY, False) == "2026-10-05"


def test_boundary_due_today_not_touched():
    assert effective_due_date(TODAY, TODAY, True) == TODAY


def test_classify_switch_on_keeps_renewed_loan_active_not_overdue():
    loans = [_loan(1, "2026-10-05")]
    out = classify_loans(loans, TODAY, auto_renew=True)
    assert [x["id"] for x in out["overdue"]] == []
    assert [x["id"] for x in out["active"]] == [1]
    assert out["active"][0]["due_date"] == TODAY
    assert out["active"][0]["renewed"] is True


def test_classify_switch_off_marks_overdue_on_old_day():
    loans = [_loan(1, "2026-10-05")]
    out = classify_loans(loans, TODAY, auto_renew=False)
    assert [x["id"] for x in out["overdue"]] == [1]
    assert out["active"] == []
    # 关开关：栏里的应还日仍是跨日前的旧日子
    assert out["overdue"][0]["due_date"] == "2026-10-05"


def test_renewed_flag_follows_actual_state_not_switch():
    loans = [_loan(1, TODAY)]  # due 就在今天，开关开也不动
    out = classify_loans(loans, TODAY, auto_renew=True)
    assert out["active"][0]["renewed"] is False


# --- 接线层：rc 必须如实透传 flag，不得另立世界 ---

def test_classify_after_renew_passes_flag_through_on():
    captured = {}

    def spy(loans, today, auto_renew):
        captured["auto"] = auto_renew
        return classify_loans(loans, today, auto_renew)

    rc.classify_after_renew([_loan(1, "2026-10-05")], TODAY, spy, True)
    assert captured["auto"] is True


def test_classify_after_renew_passes_flag_through_off():
    captured = {}

    def spy(loans, today, auto_renew):
        captured["auto"] = auto_renew
        return classify_loans(loans, today, auto_renew)

    rc.classify_after_renew([_loan(1, "2026-10-05")], TODAY, spy, False)
    assert captured["auto"] is False


def test_classify_after_renew_on_yields_no_overdue():
    # 钉死旧 bug：硬编码 False 会把已续借到当天的行仍判进逾期段
    out = rc.classify_after_renew(
        [_loan(1, TODAY, renewals=1)], TODAY, classify_loans, True)
    assert out["overdue"] == []
    assert [x["id"] for x in out["active"]] == [1]


def test_board_auto_flag_is_faithful():
    assert rc.board_auto_flag(True) is True
    assert rc.board_auto_flag(False) is False


def test_renew_note_counts_actual_due_changes():
    before = [_loan(1, "2026-10-05"), _loan(2, "2026-10-05"),
              _loan(3, "2026-10-06")]
    after = [_loan(1, TODAY, renewals=1), _loan(2, TODAY, renewals=1),
             _loan(3, "2026-10-06")]
    assert rc.renew_note(before, after) == {"changed": 2}
