# -*- coding: utf-8 -*-
"""S4-C5a：GET /api/profiling/students/<code>（学生档案页主数据；临时库，不触碰 data/y4_students.db）。"""
from __future__ import annotations

from datetime import date

import app_utils
import db as _db
from test_profiling_api import admin, client, env  # noqa: F401
from test_profiling_stages import (code_of, mk_booking, mk_profile, mk_report, mk_student,  # noqa: F401
                                   world)

KEYS = {"ok", "student", "permissions", "progress", "latest_report", "six_am",
        "first_touch", "questionnaire_flags"}
STUDENT_KEYS = {"id", "code", "name", "grade", "gender", "birthday", "school",
                "advisor_name", "email", "phone"}
PERM_KEYS = {"can_write", "is_admin", "full", "can_review", "m1_access"}


def mk_contact_student(name="联系人", advisor="Mine"):
    sid = _db.create_student(name, school="示例中学", phone="13800000000", advisor_name=advisor)
    with _db.Session(_db.engine) as s:
        s.execute(_db.Student.__table__.update().where(_db.Student.id == sid)
                  .values(email="someone@example.com"))
        s.commit()
    return sid


def fetch(c, sid):
    return c.get(f"/api/profiling/students/{code_of(sid)}")


def test_signed_out_gets_401(env):
    sid = mk_student("未登录")
    assert env.app.test_client().get(f"/api/profiling/students/{code_of(sid)}").status_code == 401


def test_admin_full_detail(env):
    sid = mk_contact_student()
    r = fetch(admin(env), sid)
    assert r.status_code == 200
    body = r.get_json()
    assert set(body) == KEYS and body["ok"] is True
    assert set(body["student"]) == STUDENT_KEYS
    assert set(body["permissions"]) == PERM_KEYS
    assert body["student"]["id"] == sid and body["student"]["code"] == code_of(sid)
    assert body["student"]["email"] == "someone@example.com"
    assert body["student"]["phone"] == "13800000000"
    perms = body["permissions"]
    assert perms["can_write"] and perms["is_admin"] and perms["full"] and perms["can_review"]
    assert perms["m1_access"] is True
    assert body["latest_report"] is None and body["six_am"] is None
    assert not body["first_touch"].get("restricted")
    assert isinstance(body["questionnaire_flags"], list)


def test_summary_account_gets_no_contact_or_content(env):
    sid = mk_contact_student()
    uid = _db.create_user("c5-sum", "pw-123456", "advisor", advisor_name="Mine",
                          detail_level="summary")
    app_utils._SESSION_USER_CACHE.clear()
    r = fetch(client(env, uid, "advisor", "Mine"), sid)
    assert r.status_code == 200
    text = r.get_data(as_text=True)
    assert "someone@example.com" not in text and "13800000000" not in text
    body = r.get_json()
    assert body["student"]["email"] == "" and body["student"]["phone"] == ""
    assert body["questionnaire_flags"] == []
    assert body["first_touch"]["restricted"] is True
    assert body["permissions"]["full"] is False
    assert body["permissions"]["can_review"] is False


def test_viewer_is_read_only(env):
    sid = mk_contact_student()
    r = fetch(client(env, env.viewer, "viewer"), sid)
    assert r.status_code == 200
    perms = r.get_json()["permissions"]
    assert perms["can_write"] is False and perms["can_review"] is False
    assert perms["is_admin"] is False


def test_own_scope_advisor_and_404s(env):
    mine = mk_student("我的", advisor="Mine")
    other = mk_student("别人的", advisor="Other")
    c = client(env, env.mine, "advisor", "Mine")
    assert fetch(c, mine).status_code == 200
    r = fetch(c, other)
    assert r.status_code == 404 and r.get_json() == {"ok": False, "error": "学生不存在"}
    r = c.get("/api/profiling/students/Y4-9999")
    assert r.status_code == 404 and r.get_json() == {"ok": False, "error": "学生不存在"}


def test_latest_report_six_am_and_progress(env):
    sid = mk_student("两份报告")
    mk_booking(sid)
    later = mk_report(sid, date(2026, 10, 2))      # 日期更晚，但 id 更小
    earlier = mk_report(sid, date(2026, 9, 1))
    mk_profile(sid, later, version=1)
    newest = mk_profile(sid, later, version=2)
    mk_profile(sid, earlier, version=5)            # 别的报告的档案不算
    c = admin(env)
    body = fetch(c, sid).get_json()
    assert body["latest_report"] == {"id": later, "report_date": "2026-10-02"}
    assert body["six_am"] == {"report_id": later, "profile_id": newest, "version": 2}
    prog = c.get(f"/api/profiling/students/{code_of(sid)}/progress").get_json()["progress"]
    assert body["progress"] == prog


def test_spa_route_serves_page(env):
    sid = mk_student("单页")
    r = admin(env).get(f"/app/students/{code_of(sid)}")
    assert r.status_code == 200
    assert '<div id="root">' in r.get_data(as_text=True)
