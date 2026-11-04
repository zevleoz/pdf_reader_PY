# -*- coding: utf-8 -*-
"""S4-C5a：GET /api/profiling/students/<code>（学生档案页主数据；临时库，不触碰 data/y4_students.db）。"""
from __future__ import annotations

import json
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


# ── S4-C5b：GET /api/profiling/students/<code>/y4 ────────────────────────
Y4_ITEMS = [
    {"code": "002", "label": "认知能力百分位", "value": "90", "source_pdf": "a"},
    {"code": "003", "label": "认知能力-空间能力百分位", "value": "40", "source_pdf": "a"},
    {"code": "011", "label": "情绪稳定性-自尊得分", "value": "3", "source_pdf": "a"},
    {"code": "012", "label": "情绪稳定性-抑郁愉快得分", "value": "12", "source_pdf": "a"},
    {"code": "013", "label": "情绪稳定性-焦虑安详得分", "value": "8", "source_pdf": "a"},
    {"code": "041", "label": "体质健康-BMI", "value": "22", "source_pdf": "b"},
    {"code": "080", "label": "职业兴趣-研究型得分", "value": "7", "source_pdf": "c"},
    {"code": "095", "label": "职业价值观-美的追求得分", "value": "5", "source_pdf": "c"},
]


def mk_y4_report(sid, when, name="虚构甲", items=None):
    data = {"student": {"name": name}, "schema_124": Y4_ITEMS if items is None else items}
    return _db.add_report(sid, when, "x.pdf", json.dumps(data, ensure_ascii=False))


def fetch_y4(c, sid):
    return c.get(f"/api/profiling/students/{code_of(sid)}/y4")


def test_y4_signed_out_gets_401(env):
    sid = mk_student("未登录")
    assert env.app.test_client().get(f"/api/profiling/students/{code_of(sid)}/y4").status_code == 401


def test_y4_scope_and_404s(env):
    mine = mk_student("我的", advisor="Mine")
    other = mk_student("别人的", advisor="Other")
    c = client(env, env.mine, "advisor", "Mine")
    assert fetch_y4(c, mine).status_code == 200
    r = fetch_y4(c, other)
    assert r.status_code == 404 and r.get_json() == {"ok": False, "error": "学生不存在"}
    r = c.get("/api/profiling/students/Y4-9999/y4")
    assert r.status_code == 404 and r.get_json() == {"ok": False, "error": "学生不存在"}
    assert fetch_y4(admin(env), other).status_code == 200


def test_y4_without_report_is_empty(env):
    sid = mk_student("没报告")
    body = fetch_y4(admin(env), sid).get_json()
    assert body == {"ok": True, "report": None, "dims": [], "signals": None, "items": []}


def test_y4_dims_signals_and_items(env):
    sid = mk_student("虚构甲")
    mk_y4_report(sid, date(2026, 9, 1), items=[])        # 更早的空报告
    rid = mk_y4_report(sid, date(2026, 10, 2))
    c = admin(env)
    body = fetch_y4(c, sid).get_json()
    assert body["ok"] is True
    assert body["report"] == {"id": rid, "report_date": "2026-10-02"}

    assert [d["name"] for d in body["dims"]] == ["心力", "精力", "学习力", "生涯力"]
    assert all(set(d) == {"name", "healthy", "weak_count", "total"} for d in body["dims"])
    mine = [p for p in _db.get_student_profiles()
            if p["student_name"] == "虚构甲" and p["report_date"] == "2026-10-02"]
    assert len(mine) == 1
    for d in body["dims"]:
        assert {k: d[k] for k in ("healthy", "weak_count", "total")} == mine[0]["dimensions"][d["name"]]
    assert next(d for d in body["dims"] if d["name"] == "心力")["weak_count"] == 2

    lists = c.get(f"/api/reports/{rid}/y4-signals").get_json()["result"]["lists"]
    assert set(body["signals"]) == {"强干预", "弱干预", "强潜能", "弱潜能"}
    assert set(lists) == set(body["signals"])
    for name in body["signals"]:
        assert body["signals"][name] == len(lists[name])

    by_code = {it["code"]: it for it in body["items"]}
    assert "095" not in by_code                      # 隐藏的原始职业价值观得分
    assert set(by_code["011"]) == {"code", "label", "value", "dimension", "eval"}
    assert by_code["011"]["eval"] == "需特殊关注" and by_code["011"]["dimension"] == "心力"
    assert by_code["011"]["value"] == "3"


def test_get_student_profiles_output_unchanged(world):
    sid = mk_student("基线甲")
    mk_y4_report(sid, date(2026, 10, 2), name="基线甲")
    _db.add_report(sid, date(2026, 9, 1), "x.pdf", "{}")
    # 期望值取自重构前（HEAD 的 db.get_student_profiles）在同一份虚构数据上的输出
    zero = {"healthy": 100.0, "total": 0, "weak_count": 0}
    assert _db.get_student_profiles() == [
        {"student_name": "基线甲", "grade": "", "school": "示例中学", "gender": "",
         "report_date": "2026-10-02",
         "dimensions": {"心力": {"healthy": 33.3, "total": 3, "weak_count": 2},
                        "精力": {"healthy": 100.0, "total": 1, "weak_count": 0},
                        "学习力": {"healthy": 50.0, "total": 2, "weak_count": 1},
                        "生涯力": {"healthy": 100.0, "total": 2, "weak_count": 0}},
         "overall_health": 70.8, "is_healthiest": True, "is_needs_attention": False},
        {"student_name": "基线甲", "grade": "", "school": "示例中学", "gender": "",
         "report_date": "2026-09-01",
         "dimensions": {"心力": zero, "精力": zero, "学习力": zero, "生涯力": zero},
         "overall_health": 0, "is_healthiest": False, "is_needs_attention": True},
    ]
