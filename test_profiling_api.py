# -*- coding: utf-8 -*-
"""C2：/api/profiling/* 学生档案数据接口（临时库，不触碰 data/y4_students.db）。"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy import event

import app_utils
import db as _db
import profiling_stages as ps
from test_profiling_stages import (code_of, mk_booking, mk_minutes, mk_profile, mk_report,
                                   mk_review, mk_student, world)  # noqa: F401

PASSWORD = "pw-123456"


@pytest.fixture()
def env(world):
    app_utils._SESSION_USER_CACHE.clear()
    app_utils._RATE_BUCKETS.clear()
    ids = SimpleNamespace(
        admin=_db.create_user("c2-admin", PASSWORD, "admin"),
        mine=_db.create_user("c2-mine", PASSWORD, "advisor", advisor_name="Mine"),
        viewer=_db.create_user("c2-view", PASSWORD, "viewer"),
    )
    import app as app_module
    application = app_module.create_app()
    application.config["TESTING"] = True
    application.secret_key = "test"
    ids.app = application
    yield ids
    app_utils._SESSION_USER_CACHE.clear()
    app_utils._RATE_BUCKETS.clear()


def client(env, user_id, role, advisor=""):
    c = env.app.test_client()
    with c.session_transaction() as s:
        s["user_id"] = user_id
        s["role"] = role
        s["advisor_name"] = advisor
    return c


def admin(env):
    return client(env, env.admin, "admin")


def get(c, **params):
    r = c.get("/api/profiling/students", query_string=params)
    return r.status_code, r.get_json()


def finish(sid):
    """让学生完成全部必需阶段（默认 6AM 规则 = 每个维度都有评议）。"""
    mk_booking(sid)
    rid = mk_report(sid)
    mk_minutes(sid, rid)
    pid = mk_profile(sid, rid)
    for d in ps.six_am_dimension_ids():
        mk_review(pid, rid, d)


# ── 登录与分页 ────────────────────────────────────────────────────────
def test_signed_out_gets_401(env):
    c = env.app.test_client()
    assert c.get("/api/profiling/students").status_code == 401
    assert c.get("/api/profiling/students/Y4-0001/progress").status_code == 401


def test_paging_and_per_page_cap(env):
    for i in range(7):
        mk_student(f"学生{i}")
    st, body = get(admin(env), per_page=3, page=2)
    assert st == 200 and body["ok"] is True
    assert (body["total"], body["page"], body["per_page"]) == (7, 2, 3)
    assert len(body["rows"]) == 3
    _, last = get(admin(env), per_page=3, page=3)
    assert len(last["rows"]) == 1
    _, big = get(admin(env), per_page=9999)
    assert big["per_page"] == 200
    _, dflt = get(admin(env))
    assert dflt["per_page"] == 50 and dflt["page"] == 1


def test_row_shape_and_sort(env):
    a, b = mk_student("甲"), mk_student("乙")
    from datetime import datetime, timedelta
    mk_booking(b, when=datetime.utcnow() + timedelta(days=1))
    _, body = get(admin(env))
    row = body["rows"][0]
    assert set(row) == {"code", "name", "school", "advisor_name", "progress", "updated_at"}
    assert row["name"] == "乙"  # 有预约时间，更新更晚，排前
    _, by_name = get(admin(env), sort="name")
    assert [r["name"] for r in by_name["rows"]] == sorted(
        [r["name"] for r in by_name["rows"]], key=lambda n: ps._pinyin_forms(n)[0])


# ── 阶段过滤与计数 ────────────────────────────────────────────────────
def test_stage_filter_and_counts_ignore_stage(env):
    nothing = mk_student("无进度")
    booked = mk_student("已预约")
    mk_booking(booked)
    done = mk_student("已完成者")
    finish(done)
    _, all_ = get(admin(env))
    assert all_["counts"]["booking"] == 1 and all_["counts"]["y4_report"] == 1
    assert all_["counts"]["done"] == 1 and all_["counts"]["six_am"] == 0
    _, f = get(admin(env), stage="y4_report")
    assert [r["name"] for r in f["rows"]] == ["已预约"] and f["total"] == 1
    assert f["counts"] == all_["counts"]  # 计数不受 stage 影响
    _, d = get(admin(env), stage="done")
    assert [r["name"] for r in d["rows"]] == ["已完成者"]
    assert d["rows"][0]["progress"]["label"] == "已完成"
    st, bad = get(admin(env), stage="nope")
    assert st == 400 and bad["ok"] is False


def test_counts_respect_q_and_advisor_but_not_stage(env):
    mk_student("沈若曦", advisor="Mine")
    mk_student("别人", advisor="Other")
    _, body = get(admin(env), advisor="Other", stage="done")
    assert body["total"] == 0 and body["counts"]["booking"] == 1
    _, body = get(admin(env), q="沈")
    assert sum(body["counts"].values()) == 1


# ── 可见范围 ──────────────────────────────────────────────────────────
def test_own_scope_advisor_sees_only_own_students(env):
    mine = mk_student("我的", advisor="Mine")
    mk_student("别人的", advisor="Other")
    c = client(env, env.mine, "advisor", "Mine")
    _, body = get(c)
    assert [r["name"] for r in body["rows"]] == ["我的"]
    assert body["total"] == 1 and sum(body["counts"].values()) == 1
    _, other = get(c, advisor="Other")  # 想用 advisor 参数越权也看不到
    assert other["total"] == 0


def test_viewer_rows_have_no_contact_or_content_fields(env):
    sid = _db.create_student("敏感", school="示例中学", phone="13800000000",
                             advisor_name="Mine")
    with _db.Session(_db.engine) as s:
        s.execute(_db.Student.__table__.update().where(_db.Student.id == sid)
                  .values(email="secret@example.com"))
        s.commit()
    for c in (client(env, env.viewer, "viewer"), admin(env)):
        r = c.get("/api/profiling/students")
        text = r.get_data(as_text=True)
        assert "13800000000" not in text and "secret@example.com" not in text
        row = r.get_json()["rows"][0]
        assert not ({"phone", "email", "grade", "birthday", "score", "scores"} & set(row))


def test_progress_route_and_404s(env):
    mine = mk_student("我的", advisor="Mine")
    other = mk_student("别人的", advisor="Other")
    mk_booking(mine)
    c = client(env, env.mine, "advisor", "Mine")
    r = c.get(f"/api/profiling/students/{code_of(mine)}/progress")
    assert r.status_code == 200
    assert r.get_json()["progress"]["next"]["key"] == "y4_report"
    assert c.get(f"/api/profiling/students/{code_of(other)}/progress").status_code == 404
    assert c.get("/api/profiling/students/Y4-9999/progress").status_code == 404
    assert admin(env).get(
        f"/api/profiling/students/{code_of(other)}/progress").status_code == 200


# ── 搜索 ──────────────────────────────────────────────────────────────
def test_search_chinese_pinyin_initials_and_code(env):
    sid = mk_student("沈若曦", school="示例中学", advisor="林老师")
    mk_student("别的学生", school="另一学校", advisor="王老师")
    c = admin(env)
    for q in ("沈", "shenruoxi", "srx", "SRX", "Shen Ruo", code_of(sid), code_of(sid).lower(),
              "示例", "shilizhongxue", "lls", "林老师"):
        _, body = get(c, q=q)
        names = [r["name"] for r in body["rows"]]
        assert "沈若曦" in names, q
        assert "别的学生" not in names, q
    _, none = get(c, q="zzzz")
    assert none["total"] == 0


# ── 批量取数不按学生数增长 ────────────────────────────────────────────
def test_listing_30_students_runs_bounded_queries(env, world):
    for i in range(30):
        sid = mk_student(f"学生{i}")
        mk_booking(sid)
        if i % 2:
            finish(sid)
    statements = []

    @event.listens_for(world, "before_cursor_execute")
    def _count(conn, cursor, statement, params, context, executemany):
        statements.append(statement)

    c = admin(env)
    st, body = get(c, per_page=200)
    event.remove(world, "before_cursor_execute", _count)
    assert st == 200 and body["total"] == 30
    selects = [s for s in statements if s.lstrip().upper().startswith("SELECT")]
    print("query count for 30 students:", len(selects), "of", len(statements))
    assert len(selects) <= 20
