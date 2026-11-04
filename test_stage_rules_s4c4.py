# -*- coding: utf-8 -*-
"""S4-C4：6AM 导师评议（路由、权限、只追加、读取）、「已评议」规则、未测评阶段。

临时库，不触碰 data/y4_students.db。
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

import app_utils
import db as _db
import pipeline
import profiling_stages as ps
from six_am.model import load_model
from test_profiling_stages import (mk_booking, mk_minutes, mk_profile, mk_report, mk_student,
                                   world)  # noqa: F401

PASSWORD = "pw-123456"
CSRF = "csrf-test-token"
DIMS = ("A1", "A2", "A3", "A4", "A5")


@pytest.fixture()
def env(world):
    app_utils._SESSION_USER_CACHE.clear()
    app_utils._RATE_BUCKETS.clear()
    ids = SimpleNamespace(
        admin=_db.create_user("s4-admin", PASSWORD, "admin", display_name="管理员甲"),
        mine=_db.create_user("s4-mine", PASSWORD, "advisor", advisor_name="Mine",
                             display_name="顾问甲"),
        other=_db.create_user("s4-other", PASSWORD, "advisor", advisor_name="Other"),
        summary=_db.create_user("s4-sum", PASSWORD, "advisor", advisor_name="Mine",
                                detail_level="summary"),
        viewer=_db.create_user("s4-view", PASSWORD, "viewer"),
    )
    import app as app_module
    application = app_module.create_app()
    application.config["TESTING"] = True
    application.secret_key = "test"
    ids.app = application
    yield ids
    app_utils._SESSION_USER_CACHE.clear()
    app_utils._RATE_BUCKETS.clear()


def client(env, key):
    role = {"admin": "admin", "viewer": "viewer"}.get(key, "advisor")
    advisor = {"mine": "Mine", "summary": "Mine", "other": "Other"}.get(key, "")
    c = env.app.test_client()
    with c.session_transaction() as s:
        s["user_id"] = getattr(env, key)
        s["role"] = role
        s["advisor_name"] = advisor
        s["_csrf_token"] = CSRF
        s["display_name"] = "管理员甲" if key == "admin" else key
    return c


def case():
    """学生（顾问 Mine）+ 报告 + 6AM 档案。"""
    sid = mk_student("评议甲", advisor="Mine")
    rid = mk_report(sid)
    pid = mk_profile(sid, rid)
    return sid, rid, pid


def post(c, rid, **body):
    return c.post(f"/api/reports/{rid}/six-am/reviews", json=body,
                  headers={"X-CSRF-Token": CSRF})


def good(pid, **over):
    body = {"profile_id": pid, "dim": "A1", "verdict": "agree", "note": "同意"}
    body.update(over)
    return body


# ── Part B：路由校验 ──────────────────────────────────────────────────
def test_valid_states_come_from_the_model():
    from blueprints.insights import _review_states
    assert _review_states() == tuple(load_model()["levels"])


@pytest.mark.parametrize("override,message", [
    ({"profile_id": None}, "缺少有效的档案 ID"),
    ({"profile_id": "abc"}, "缺少有效的档案 ID"),
    ({"dim": "A6"}, "维度必须是 A1–A5"),
    ({"dim": ""}, "维度必须是 A1–A5"),
    ({"verdict": "maybe"}, "结论必须是 agree、adjust 或 evidence"),
    ({"verdict": "adjust"}, "调整为 X 时必须给出有效状态"),
    ({"verdict": "adjust", "adjusted_state": "At-Risk"}, "调整为 X 时必须给出有效状态"),
    ({"note": "字" * 501}, "备注最多 500 字"),
    ({"owner": "字" * 51}, "负责人最多 50 字"),
    ({"due_date": "2026/11/04"}, "截止日期格式必须是 YYYY-MM-DD"),
])
def test_bad_input_is_400(env, override, message):
    _sid, rid, pid = case()
    r = post(client(env, "admin"), rid, **good(pid, **override))
    assert r.status_code == 400 and r.get_json()["error"] == message
    assert _db.latest_six_am_reviews(pid) == {}


def test_profile_must_belong_to_the_report(env):
    sid, rid, _pid = case()
    other_rid = mk_report(sid)
    other_pid = mk_profile(sid, other_rid)
    r = post(client(env, "admin"), rid, **good(other_pid))
    assert r.status_code == 400 and r.get_json()["error"] == "档案不属于该报告"
    assert post(client(env, "admin"), rid, **good(999999)).status_code == 400


def test_adjust_accepts_each_model_level_and_stores_it(env):
    _sid, rid, pid = case()
    c = client(env, "admin")
    for level in load_model()["levels"]:
        r = post(c, rid, **good(pid, verdict="adjust", adjusted_state=level))
        assert r.status_code == 200
        assert r.get_json()["review"]["adjusted_state"] == level
    # 非 adjust 时丢弃 adjusted_state
    r = post(c, rid, **good(pid, verdict="agree", adjusted_state="风险"))
    assert r.get_json()["review"]["adjusted_state"] is None


def test_review_records_author_and_fields(env):
    _sid, rid, pid = case()
    r = post(client(env, "admin"), rid, **good(pid, owner="王老师", due_date="2026-11-30"))
    rev = r.get_json()["review"]
    assert (rev["author"], rev["owner"], rev["due_date"], rev["note"]) == (
        "管理员甲", "王老师", "2026-11-30", "同意")


# ── 权限矩阵 ──────────────────────────────────────────────────────────
@pytest.mark.parametrize("who,status", [
    ("admin", 200), ("mine", 200), ("viewer", 403), ("summary", 403), ("other", 403)])
def test_write_permission_matrix(env, who, status):
    _sid, rid, pid = case()
    r = post(client(env, who), rid, **good(pid))
    assert r.status_code == status
    assert len(_db.latest_six_am_reviews(pid)) == (1 if status == 200 else 0)


def test_signed_out_gets_401(env):
    _sid, rid, pid = case()
    c = env.app.test_client()
    assert post(c, rid, **good(pid)).status_code == 401
    assert c.get(f"/api/reports/{rid}/six-am/reviews").status_code == 401


# ── 只追加 ────────────────────────────────────────────────────────────
def test_review_is_append_only_and_does_not_touch_the_profile(env):
    sid, rid, pid = case()
    before = _db.get_six_am_profile(pid)
    n_profiles = len(_db.get_six_am_profiles_by_student(sid))
    c = client(env, "admin")
    post(c, rid, **good(pid, verdict="agree"))
    post(c, rid, **good(pid, verdict="adjust", adjusted_state="风险"))
    assert len(_db.get_six_am_profiles_by_student(sid)) == n_profiles
    assert _db.get_six_am_profile(pid) == before
    with _db.Session(_db.engine) as s:
        rows = s.query(_db.SixAmReview).filter_by(profile_id=pid, dim="A1").all()
    assert [r.verdict for r in rows] == ["agree", "adjust"]  # 旧行保留


# ── 读取 ──────────────────────────────────────────────────────────────
def test_get_returns_latest_review_per_dimension_for_latest_profile(env):
    sid, rid, old = case()
    new = mk_profile(sid, rid, version=2)
    c = client(env, "admin")
    post(c, rid, **good(old, dim="A1", verdict="agree"))  # 旧版本的评议不出现
    post(c, rid, **good(new, dim="A1", verdict="evidence"))
    post(c, rid, **good(new, dim="A1", verdict="adjust", adjusted_state="阻塞"))
    post(c, rid, **good(new, dim="A2", verdict="agree"))
    body = c.get(f"/api/reports/{rid}/six-am/reviews").get_json()
    assert body["ok"] is True and body["profile_id"] == new and body["version"] == 2
    assert set(body["reviews"]) == {"A1", "A2"}
    assert body["reviews"]["A1"]["verdict"] == "adjust"
    assert body["reviews"]["A1"]["adjusted_state"] == "阻塞"


def test_get_without_profile_and_unknown_report(env):
    sid = mk_student("无档案", advisor="Mine")
    rid = mk_report(sid)
    c = client(env, "admin")
    assert c.get(f"/api/reports/{rid}/six-am/reviews").get_json()["reviews"] == {}
    assert c.get("/api/reports/99999/six-am/reviews").status_code == 404


@pytest.mark.parametrize("who,status", [
    ("admin", 200), ("mine", 200), ("summary", 200), ("viewer", 200), ("other", 403)])
def test_read_permission_matrix_summary_accounts_may_read(env, who, status):
    _sid, rid, pid = case()
    post(client(env, "admin"), rid, **good(pid))
    r = client(env, who).get(f"/api/reports/{rid}/six-am/reviews")
    assert r.status_code == status
    if status == 200:
        assert r.get_json()["reviews"]["A1"]["verdict"] == "agree"


# ── 「已评议」规则 ────────────────────────────────────────────────────
def test_reviewed_rule_through_the_route(env, monkeypatch):
    monkeypatch.setattr(ps, "SIX_AM_DONE", "reviewed")
    sid, rid, pid = case()
    mk_booking(sid)
    mk_minutes(sid, rid)
    c = client(env, "admin")
    for dim in DIMS:
        post(c, rid, **good(pid, dim=dim, verdict="evidence"))
    assert ps.progress_for_student(sid)["done"] is False
    for i, dim in enumerate(DIMS):
        if i % 2:
            post(c, rid, **good(pid, dim=dim, verdict="adjust", adjusted_state="关注"))
        else:
            post(c, rid, **good(pid, dim=dim, verdict="agree"))
    assert ps.progress_for_student(sid)["done"] is True
    post(c, rid, **good(pid, dim="A3", verdict="evidence"))
    assert ps.progress_for_student(sid)["done"] is False


# ── 页面：评议面板的显示权限 ───────────────────────────────────────────
def test_page_flags_review_controls_by_account(env):
    flag = re.compile(r'data-can-review="(true|false)"')
    got = {}
    for who in ("admin", "mine", "summary", "viewer"):
        html = client(env, who).get("/insights/six-am").get_data(as_text=True)
        got[who] = flag.search(html).group(1)
    assert got == {"admin": "true", "mine": "true", "summary": "false", "viewer": "false"}


def test_student_js_carries_the_review_panel_with_old_wording():
    js = (Path(__file__).parent / "static/js/six_am/student.js").read_text(encoding="utf-8")
    for text in ("团队结论", "同意", "调整状态", "证据不足，需追问", "调整为", "理由与跟进",
                 "保存结论", "尚无团队结论。", "已记录团队结论", "记录："):
        assert text in js
    assert "/six-am/reviews" in js and "data-can-review" in js


# ── Part C：未测评 ────────────────────────────────────────────────────
def test_not_started_stage_metadata():
    booked = pipeline.stage_meta("booked")
    for meta in (pipeline.stage_meta("not_started"), pipeline.progress_stage_meta("not_started")):
        assert meta["key"] == "not_started" and meta["label"] == "未测评"
        assert (meta["badge"], meta["color"]) == (booked["badge"], booked["color"])
    assert "not_started" in pipeline.STAGE_KEYS and "not_started" in pipeline.PROGRESS_STAGE_KEYS
    assert pipeline.PROGRESS_STAGE_KEYS[0] == "not_started"
    assert pipeline.STAGE_KEYS[-1] == "ready"


def test_student_with_nothing_is_not_started_in_both_views(world):
    sid = mk_student("什么都没有")
    assert pipeline.compute_stages()[sid]["stage"] == "not_started"
    assert pipeline.compute_progress(sid)["stage"] == "not_started"
    counts = pipeline.stage_counts(pipeline.compute_stages())
    assert counts["not_started"] == 1 and counts["ready"] == 0


def test_old_booking_outside_the_window_is_still_ready_not_not_started(world):
    sid = mk_student("旧预约")
    mk_booking(sid, when=datetime(2026, 1, 5))  # 超出 30 天窗口：原本就是 ready
    assert pipeline.compute_stages()[sid]["stage"] == "ready"
    mk_booking(mk_student("已取消"), status="cancelled")
    cancelled = [i for i, v in pipeline.compute_stages().items() if v["stage"] == "not_started"]
    assert len(cancelled) == 1


def test_other_cases_are_unchanged_in_both_views(world):
    booked = mk_student("已预约")
    mk_booking(booked, when=datetime.utcnow())
    reported = mk_student("有报告")
    mk_report(reported)
    st = pipeline.compute_stages()
    assert st[booked]["stage"] == "booked"
    assert pipeline.compute_progress(booked)["stage"] == "booked"
    assert st[reported]["stage"] == "reported"
    assert pipeline.compute_progress(reported)["stage"] == "minutes"
