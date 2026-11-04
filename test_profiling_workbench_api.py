# -*- coding: utf-8 -*-
"""S4-C6a：GET /api/profiling/workbench（工作台队列；临时库，只用虚构数据）。"""
from __future__ import annotations

import json
from datetime import datetime, timedelta

from sqlalchemy import insert

import app_utils
import db as _db
import profiling_stages as ps
import questionnaire_store as qs
from test_profiling_api import admin, client, env, finish  # noqa: F401
from test_profiling_stages import (code_of, mk_assignment, mk_booking, mk_copilot,  # noqa: F401
                                   mk_profile, mk_questionnaire, mk_report, mk_review,
                                   mk_student, world)

URL = "/api/profiling/workbench"


def fetch(c):
    r = c.get(URL)
    assert r.status_code == 200
    return r.get_json()


def mk_flag(sid, qid, title_code="QF", reviewed=False):
    """造一份带安全提醒的已提交答卷（直接写表）。"""
    aid = mk_assignment(sid, qid, status="submitted", submitted_at=datetime(2026, 10, 3, 9, 0))
    result = {"flags": [{"id": "q9", "label": "第 9 题", "answer": "几乎每天"}]}
    with _db.Session(_db.engine) as s:
        rid = s.execute(insert(qs.Response).values(
            assignment_id=aid, student_id=sid, questionnaire_id=qid,
            answers_json="{}", submitted_via="account")).lastrowid
        s.execute(insert(qs.QuestionnaireScore).values(
            response_id=rid, assignment_id=aid, student_id=sid, questionnaire_id=qid,
            scoring_version=1, result_json=json.dumps(result, ensure_ascii=False), flagged=1,
            reviewed_at=datetime(2026, 10, 4) if reviewed else None))
        s.commit()
    return aid


def mk_pending(sid, qid, source="auto", created=None):
    aid = mk_assignment(sid, qid, status="pending")
    with _db.Session(_db.engine) as s:
        s.execute(qs.Assignment.__table__.update().where(qs.Assignment.id == aid)
                  .values(source=source, reason="规则原因甲",
                          created_at=created or datetime(2026, 10, 2)))
        s.commit()
    return aid


def mk_future_booking(sid, hours, advisor="Mine", status="pending", name="预约者"):
    when = datetime.now() + timedelta(hours=hours)
    bid = _db.add_booking(name, when, student_id=sid, advisor_name=advisor)
    with _db.Session(_db.engine) as s:
        s.execute(_db.Booking.__table__.update().where(_db.Booking.id == bid)
                  .values(status=status))
        s.commit()
    return bid


def kinds(body):
    return [i["kind"] for i in body["queue"]]


def test_signed_out_gets_401(env):
    assert env.app.test_client().get(URL).status_code == 401


def test_scope_own_advisor_sees_only_own_students(env):
    mine = mk_student("我的", advisor="Mine")
    other = mk_student("别人的", advisor="Other")
    qid = mk_questionnaire()
    mk_pending(mine, qid)
    mk_pending(other, qid)
    mk_flag(mine, mk_questionnaire("QA"))
    mk_flag(other, mk_questionnaire("QB"))
    mk_future_booking(mine, 5, advisor="Mine")
    mk_future_booking(other, 6, advisor="Other")
    c = client(env, env.mine, "advisor", "Mine")
    body = fetch(c)
    assert {i["student"]["id"] for i in body["queue"]} == {mine}
    assert sum(body["counts"].values()) == 1
    assert [u["student_name"] for u in body["upcoming"]] == ["预约者"]
    assert len(body["upcoming"]) == 1
    everyone = fetch(admin(env))
    assert sum(everyone["counts"].values()) == 2 and len(everyone["upcoming"]) == 2
    assert {i["student"]["id"] for i in everyone["queue"]} == {mine, other}


def test_summary_account_gets_no_flags_or_reasons(env):
    sid = mk_student("概要生", advisor="Mine")
    mk_flag(sid, mk_questionnaire("QF"))
    mk_pending(sid, mk_questionnaire("QP"))
    uid = _db.create_user("c6-sum", "pw-123456", "advisor", advisor_name="Mine",
                          detail_level="summary")
    app_utils._SESSION_USER_CACHE.clear()
    r = client(env, uid, "advisor", "Mine").get(URL)
    body = r.get_json()
    text = r.get_data(as_text=True)
    assert body["permissions"]["full"] is False
    assert "flag" not in kinds(body)
    assert "reason" not in text and "规则原因甲" not in text and "几乎每天" not in text
    full = fetch(admin(env))
    assert "flag" in kinds(full)
    flag = next(i for i in full["queue"] if i["kind"] == "flag")
    assert flag["flags"] == [{"label": "第 9 题", "answer": "几乎每天"}]
    assert "规则原因甲" not in json.dumps(full, ensure_ascii=False)


def test_order_flag_confirm_six_am_first_touch_booking(env):
    q = mk_questionnaire()
    b = mk_student("预约甲")                       # booking
    f = mk_student("触点乙")                       # first_touch 开始、6AM 未评议、next=booking
    mk_copilot(f)
    c_ = mk_student("确认丙")
    mk_pending(c_, q)
    s6 = mk_student("六点丁")
    mk_booking(s6)
    rid = mk_report(s6)
    from test_profiling_stages import mk_minutes
    mk_minutes(s6, rid)
    mk_profile(s6, rid)
    fl = mk_student("提醒戊")
    mk_flag(fl, mk_questionnaire("QF"))
    body = fetch(admin(env))
    order = {"flag": 0, "confirm": 1, "six_am": 2, "first_touch": 3, "booking": 4}
    ranks = [order[k] for k in kinds(body)]
    assert ranks == sorted(ranks)
    assert set(kinds(body)) == set(order)
    assert any(i["student"]["id"] == b and i["kind"] == "booking" for i in body["queue"])


def test_confirm_groups_two_tasks_per_student(env):
    sid = mk_student("两份")
    mk_pending(sid, mk_questionnaire("QA"), source="auto", created=datetime(2026, 10, 5))
    mk_pending(sid, mk_questionnaire("QB"), source="manual", created=datetime(2026, 10, 2))
    other = mk_student("一份")
    mk_pending(other, mk_questionnaire("QC"), created=datetime(2026, 10, 1))
    body = fetch(admin(env))
    items = [i for i in body["queue"] if i["kind"] == "confirm"]
    assert len(items) == 2
    assert items[0]["student"]["id"] == other                  # 组内最早创建的在前
    two = items[1]
    assert two["student"]["id"] == sid and len(two["assignments"]) == 2
    assert two["created_at"].startswith("2026-10-02")
    assert set(two["assignments"][0]) == {"id", "questionnaire_title", "source"}
    assert {a["source"] for a in two["assignments"]} == {"auto", "manual"}


def test_six_am_reviewed_counts_latest_agree_or_adjust(env):
    dims = ps.six_am_dimension_ids()
    s_no = mk_student("无档案")
    mk_booking(s_no)
    rid0 = mk_report(s_no)
    from test_profiling_stages import mk_minutes
    mk_minutes(s_no, rid0)
    s_part = mk_student("部分")
    mk_booking(s_part)
    rid = mk_report(s_part)
    mk_minutes(s_part, rid)
    pid = mk_profile(s_part, rid)
    mk_review(pid, rid, dims[0], "agree")
    mk_review(pid, rid, dims[1], "adjust")
    mk_review(pid, rid, dims[2], "evidence")
    mk_review(pid, rid, dims[3], "agree")
    mk_review(pid, rid, dims[3], "evidence")                   # 最新一条为 evidence：不算
    body = fetch(admin(env))
    six = {i["student"]["id"]: i for i in body["queue"] if i["kind"] == "six_am"}
    assert six[s_part]["reviewed"] == 2 and six[s_part]["report_id"] == rid
    assert six[s_no]["reviewed"] is None and six[s_no]["report_id"] == rid0


def test_upcoming_filters_sorts_and_caps(env):
    sid = mk_student("有档案")
    mk_future_booking(sid, -3, name="过去")
    mk_future_booking(sid, 4, status="completed", name="已完成")
    mk_future_booking(sid, 5, status="cancelled", name="已取消")
    for h, n in ((30, "g"), (10, "c"), (20, "e"), (12, "d"), (40, "h"), (8, "b"), (6, "a")):
        mk_future_booking(None, h, name=n)
    mk_future_booking(sid, 7, name="带编号")
    body = fetch(admin(env))
    names = [u["student_name"] for u in body["upcoming"]]
    assert names == ["a", "带编号", "b", "c", "d"]
    times = [u["appointment_time"] for u in body["upcoming"]]
    assert times == sorted(times)
    by_name = {u["student_name"]: u for u in body["upcoming"]}
    assert by_name["带编号"]["student_code"] == code_of(sid)
    assert by_name["a"]["student_code"] is None
    assert set(by_name["a"]) == {"booking_id", "student_name", "student_code",
                                 "appointment_time", "advisor_name"}


def test_counts_equal_students_endpoint_counts(env):
    for i in range(4):
        sid = mk_student(f"学生{i}")
        if i == 0:
            finish(sid)
        elif i == 1:
            mk_booking(sid)
        elif i == 2:
            rid = mk_report(sid)
            mk_profile(sid, rid)
    c = admin(env)
    full = c.get("/api/profiling/students").get_json()["counts"]
    body = fetch(c)
    assert set(body["counts"]) == {"booking", "y4_report", "interpretation", "six_am", "done"}
    assert body["counts"] == {k: full[k] for k in body["counts"]}
    assert body["counts"]["done"] == 1


def test_job_null_for_viewer(env):
    mk_student("任意")
    body = fetch(client(env, env.viewer, "viewer"))
    assert body["job"] is None
    assert body["permissions"] == {"can_write": False, "full": False}
    assert fetch(admin(env))["permissions"]["can_write"] is True


def test_workbench_page_serves_spa(env):
    r = admin(env).get("/app/workbench")
    assert r.status_code == 200
    assert '<div id="root">' in r.get_data(as_text=True)


def test_upcoming_cutoff_uses_beijing_wall_clock(env):
    from zoneinfo import ZoneInfo
    now = datetime.now(ZoneInfo("Asia/Shanghai")).replace(tzinfo=None)
    for delta, name in ((-1, "一小时前"), (1, "一小时后")):
        _db.add_booking(name, now + timedelta(hours=delta), advisor_name="Mine")
    names = [u["student_name"] for u in fetch(admin(env))["upcoming"]]
    assert names == ["一小时后"]
