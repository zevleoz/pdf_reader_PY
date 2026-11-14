"""DP1：发展计划 API（权限、文件、§7 校验、导出前置条件）。"""
from __future__ import annotations

import copy
import io
from pathlib import Path

import pytest
from flask import Flask

import m1.plan_store as pstore
from app_utils import BASE_DIR
from test_m1_pipeline import _login
from test_m1_store import m1db  # noqa: F401  pytest fixture
from test_m1dp_store import _create, _drafted_prep, _goal, _published_prep


@pytest.fixture()
def plan_client(m1db, tmp_path, monkeypatch):  # noqa: F811
    import app_utils
    from blueprints import m1 as m1_api
    from blueprints import m1_plan

    pstore.ensure_tables(m1db.engine)
    monkeypatch.setattr(pstore, "_UPLOAD_ROOT", tmp_path / "m1_plans")
    monkeypatch.setattr(app_utils, "is_authenticated", lambda: True)
    app = Flask(__name__, template_folder=str(BASE_DIR / "templates"))
    app.secret_key = "test-secret"
    app.register_blueprint(m1_api.bp)
    app.register_blueprint(m1_plan.bp)
    return app.test_client()


def _field(text):
    return {"text": text, "src": "ai"}


def _internal_doc(code="R2.2"):
    doc = {"overview": _field("Block Overview"), "mentor_notes": _field(""), "sessions": []}
    for n in (1, 2, 3):
        activity = {"id": "s%da1" % n, "name": _field("活动"),
                    "minutes": 15, "steps": _field("步骤"),
                    "questions": _field("问题"), "materials": _field("材料"),
                    "source": {"type": "ai_original"}, "block_review": False}
        if n == 3:
            activity["block_review"] = True
        doc["sessions"].append({
            "n": n,
            "title": _field("第 %d 课" % n),
            "review": [] if n == 1 else [_field("回顾一"), _field("回顾二")],
            "focus": {"primary": code, "supporting": None, "text": _field("重点")},
            "content": {"mindsets": _field("心态"), "skills": _field("技能"),
                        "techniques": _field("技巧")},
            "activities": [activity],
            "evidence": _field("表现"),
            "practice": [{"id": "s%dp1" % n, "code": code, "name": _field("练习"),
                          "task": _field("任务"), "frequency": _field("每天"),
                          "platform": "StoryMap", "evidence": _field("证据")}],
            "next_prep": None if n == 3 else _field("下次准备"),
        })
    return doc


def _parent_doc(plan, code="R2.2"):
    return {
        "intro": _field("开场"),
        "goals": [{"code": code, "text": _field("目标说明")}],
        "sessions": [{"n": n, "title": _field("第 %d 课" % n),
                      "summary": _field("摘要")} for n in (1, 2, 3)],
        "transition": _field("过渡"),
        "practice_options": [{"ref": "s1p1", "title": _field("练习"),
                              "text": _field("说明"), "frequency": _field("每天"),
                              "platform": "StoryMap"}],
        "practice": ["s1p1"],
        "family": [_field("建议一"), _field("建议二")],
        "family_seen": [True, True],
        "review": [{"label": _field("观察一"), "text": _field("记录一")},
                   {"label": _field("观察二"), "text": _field("记录二")}],
    }


def _new_plan_with_version(db, doc=None):
    prep, report = _published_prep(db)
    plan = _create(db, prep, report)
    plan = pstore.save_goals(plan["id"], plan["rev"], [_goal()])
    doc = doc or _internal_doc()
    version = pstore.add_version(plan["id"], part="internal", kind="ai_draft",
                                 ai_doc=doc, doc=doc, checks=[])
    pstore.finish_generation(plan["id"], "internal", version_id=version["id"])
    return pstore.get_plan(plan["id"]), doc


def _confirmed_plan(db):
    plan, doc = _new_plan_with_version(db)
    pstore.approve(plan["id"], db.alice_id)
    plan = pstore.get_plan(plan["id"])
    parent = _parent_doc(plan)
    pstore.add_version(plan["id"], part="parent", kind="ai_draft",
                       ai_doc=parent, doc=parent, checks=[],
                       source_version_id=plan["current_version_id"])
    pstore.finish_generation(plan["id"], "parent")
    plan = pstore.get_plan(plan["id"])
    pstore.confirm_parent(plan["id"], db.alice_id)
    return pstore.get_plan(plan["id"]), parent


def _multipart(filename, data):
    return {"file": (io.BytesIO(data), filename)}


# ---------------------------------------------------------------------------
# 列表 / 可新建 / 新建
# ---------------------------------------------------------------------------
def test_list_and_eligible_include_ready_reports(plan_client, m1db):
    prep, _report = _published_prep(m1db)
    _create(m1db, prep, _report)
    _login(plan_client, m1db.alice_id, "advisor", "Alice")

    eligible = plan_client.get("/api/m1/plans/eligible").get_json()["students"]
    assert [row["prep_id"] for row in eligible] == [prep["id"]]
    assert eligible[0]["next_block"] == 2

    body = plan_client.get("/api/m1/plans?scope=mine").get_json()
    assert body["ok"] and len(body["plans"]) == 1
    assert body["plans"][0]["status_label"] == "资料与目标"
    assert body["plans"][0]["next"]["label"] == "继续发展计划"
    assert plan_client.get("/api/m1/plans?scope=all").get_json()["plans"]


def test_eligible_and_create_accept_ai_draft_report(plan_client, m1db):
    prep, report = _drafted_prep(m1db)
    _login(plan_client, m1db.alice_id, "advisor", "Alice")

    eligible = plan_client.get("/api/m1/plans/eligible").get_json()["students"]
    assert [row["prep_id"] for row in eligible] == [prep["id"]]

    payload = {"student_id": m1db.student_id, "prep_id": prep["id"], "block_no": 1,
               "period_start": "2026-11-17", "period_end": "2026-12-15",
               "wb_grade": 9}
    res = plan_client.post("/api/m1/plans", json=payload)
    assert res.status_code == 201, res.get_json()
    assert res.get_json()["plan"]["report_version_id"] == report["current_version_id"]
    assert plan_client.post("/api/m1/plans", json=payload).status_code == 400


def test_create_rejects_report_without_draft(plan_client, m1db):
    import m1.report_store as rstore
    prep = m1db.prep()
    rstore.get_or_create_report(prep["id"], m1db.alice_id)
    _login(plan_client, m1db.alice_id, "advisor", "Alice")
    payload = {"student_id": m1db.student_id, "prep_id": prep["id"], "block_no": 1,
               "period_start": "2026-11-17", "period_end": "2026-12-15",
               "wb_grade": 9}
    res = plan_client.post("/api/m1/plans", json=payload)
    assert res.status_code == 409
    assert "还没有生成 AI 草稿" in res.get_json()["error"]


def test_create_without_a_reference_grade_is_allowed(plan_client, m1db, monkeypatch):
    prep, _report = _published_prep(m1db)
    monkeypatch.setattr(pstore, "parse_wb_grade", lambda text: None)
    _login(plan_client, m1db.alice_id, "advisor", "Alice")
    payload = {"student_id": m1db.student_id, "prep_id": prep["id"], "block_no": 1,
               "period_start": "2026-11-17", "period_end": "2026-12-15"}
    # 学生没有年级、导师也没选：参考年级可以空着
    res = plan_client.post("/api/m1/plans", json=payload)
    assert res.status_code == 201, res.get_json()
    assert res.get_json()["plan"]["wb_grade"] is None


def test_create_refuses_a_grade_outside_g5_to_g9(plan_client, m1db):
    _login(plan_client, m1db.alice_id, "advisor", "Alice")
    for grade in (4, 10):
        prep, _report = _published_prep(m1db)
        payload = {"student_id": m1db.student_id, "prep_id": prep["id"], "block_no": 1,
                   "period_start": "2026-11-17", "period_end": "2026-12-15",
                   "wb_grade": grade}
        assert plan_client.post("/api/m1/plans", json=payload).status_code == 400


def test_wb_candidates_without_a_grade_fall_back_to_g9(monkeypatch):
    from blueprints import m1_plan
    from m1 import wb

    monkeypatch.setenv("M1_WB_DIR",
                       str(BASE_DIR / "tests" / "fixtures" / "wb_mini"))
    goals = [{"code": "R4.9"}]
    assert pstore.wb_grade_or_default({"wb_grade": None}) == 9
    assert pstore.wb_grade_or_default({"wb_grade": 7}) == 7
    assert m1_plan._wb_candidates({"wb_grade": None, "goals": goals}) == \
        m1_plan._wb_candidates({"wb_grade": 9, "goals": goals})
    assert m1_plan._wb_candidates({"wb_grade": None, "goals": goals})["R4.9"] == \
        wb.candidates("R4.9", 9)


# ---------------------------------------------------------------------------
# 权限
# ---------------------------------------------------------------------------
def test_non_mentor_can_read_but_not_write(plan_client, m1db, monkeypatch):
    import m1.store as store
    prep, report = _published_prep(m1db)
    plan = _create(m1db, prep, report)
    monkeypatch.setattr(store, "_sees_all_students", lambda user: True)
    _login(plan_client, m1db.bob_id, "advisor", "Bob")

    assert plan_client.get("/api/m1/plans/%d" % plan["id"]).status_code == 200
    assert plan_client.get("/api/m1/plans/%d/versions" % plan["id"]).status_code == 200

    path = "/api/m1/plans/%d" % plan["id"]
    assert plan_client.patch(path, json={"rev": plan["rev"], "credits": "4"}).status_code == 403
    assert plan_client.put(path + "/goals",
                           json={"rev": plan["rev"], "goals": []}).status_code == 403
    assert plan_client.put(path + "/inputs",
                           json={"rev": plan["rev"], "strengths": "x"}).status_code == 403
    assert plan_client.put(path + "/personal",
                           json={"rev": plan["rev"], "notes": "x"}).status_code == 403
    assert plan_client.post(path + "/files",
                            data=_multipart("a.txt", b"x")).status_code == 403
    assert plan_client.put(path + "/internal",
                           json={"rev": plan["rev"], "doc": _internal_doc()}).status_code == 403
    assert plan_client.post(path + "/approve").status_code == 403
    assert plan_client.post(path + "/reopen").status_code == 403
    assert plan_client.put(path + "/parent",
                           json={"rev": plan["rev"], "doc": {}}).status_code == 403
    assert plan_client.post(path + "/parent/confirm").status_code == 403
    assert plan_client.post(path + "/parent/export", json={"fits": True}).status_code == 403


def test_other_advisor_gets_404(plan_client, m1db):
    prep, report = _published_prep(m1db)
    plan = _create(m1db, prep, report)
    _login(plan_client, m1db.bob_id, "advisor", "Bob")
    assert plan_client.get("/api/m1/plans/%d" % plan["id"]).status_code == 404


def test_admin_can_write(plan_client, m1db):
    prep, report = _published_prep(m1db)
    plan = _create(m1db, prep, report)
    _login(plan_client, m1db.admin_id, "admin")
    res = plan_client.patch("/api/m1/plans/%d" % plan["id"],
                            json={"rev": plan["rev"], "credits": "5"})
    assert res.status_code == 200
    assert res.get_json()["plan"]["credits"] == "5"


# ---------------------------------------------------------------------------
# 目标 / 资料 / 个性化需求 / 表头
# ---------------------------------------------------------------------------
def test_goals_inputs_personal_and_header_writes(plan_client, m1db):
    prep, report = _published_prep(m1db)
    plan = _create(m1db, prep, report)
    _login(plan_client, m1db.alice_id, "advisor", "Alice")
    path = "/api/m1/plans/%d" % plan["id"]

    res = plan_client.put(path + "/goals", json={"rev": plan["rev"], "goals": [_goal()]})
    assert res.status_code == 200
    assert res.get_json()["goals"][0]["name"] == "反刍思维管理"

    res = plan_client.put(path + "/inputs",
                          json={"rev": res.get_json()["plan"]["rev"], "strengths": "愿意开口"})
    assert res.status_code == 200, res.get_json()
    assert res.get_json()["plan"]["inputs"]["strengths"] == {
        "text": "愿意开口", "src": "edited"}

    res = plan_client.put(path + "/personal",
                          json={"rev": res.get_json()["plan"]["rev"], "notes": "家长希望多练习"})
    assert res.status_code == 200
    assert res.get_json()["plan"]["personal"]["notes"] == "家长希望多练习"

    res = plan_client.put(path + "/personal",
                          json={"rev": res.get_json()["plan"]["rev"],
                                "summary": "导师改写的需求总结"})
    assert res.status_code == 200, res.get_json()
    personal = res.get_json()["plan"]["personal"]
    assert personal["summary"] == {"text": "导师改写的需求总结", "src": "edited"}
    assert personal["notes"] == "家长希望多练习"
    stale = plan_client.put(path + "/personal",
                            json={"rev": plan["rev"], "summary": "过期版本"})
    assert stale.status_code == 409

    res = plan_client.patch(path, json={"rev": res.get_json()["plan"]["rev"],
                                        "block_no": 2, "credits": "4"})
    assert res.status_code == 200
    assert res.get_json()["plan"]["block_no"] == 2


# ---------------------------------------------------------------------------
# 文件
# ---------------------------------------------------------------------------
def test_file_rules_and_delete(plan_client, m1db):
    prep, report = _published_prep(m1db)
    plan = _create(m1db, prep, report)
    _login(plan_client, m1db.alice_id, "advisor", "Alice")
    path = "/api/m1/plans/%d/files" % plan["id"]

    assert plan_client.post(path, data=_multipart("a.md", b"x")).status_code == 400
    assert plan_client.post(
        path, data=_multipart("big.txt", b"x" * (10 * 1024 * 1024 + 1))).status_code == 400

    text = "会议记录：" + "学生最近状态稳定。" * 8
    res = plan_client.post(path, data=_multipart("记录.txt", text.encode("utf-8")))
    assert res.status_code == 201, res.get_json()
    saved = res.get_json()["file"]
    assert saved["filename"] == "记录.txt" and saved["text_status"] == "ok"
    assert "text" not in saved
    stored = Path(pstore.get_file(saved["id"])["stored_path"])
    assert stored.exists()

    detail = plan_client.get("/api/m1/plans/%d" % plan["id"]).get_json()
    assert detail["personal"]["files"][0]["id"] == saved["id"]

    assert plan_client.delete("/api/m1/plan-files/%d" % saved["id"]).status_code == 200
    assert pstore.get_file(saved["id"]) is None
    assert not stored.exists()


def test_file_delete_needs_mentor(plan_client, m1db, monkeypatch):
    import m1.store as store
    prep, report = _published_prep(m1db)
    plan = _create(m1db, prep, report)
    _login(plan_client, m1db.alice_id, "advisor", "Alice")
    res = plan_client.post("/api/m1/plans/%d/files" % plan["id"],
                           data=_multipart("a.txt", b"hello"))
    file_id = res.get_json()["file"]["id"]

    monkeypatch.setattr(store, "_sees_all_students", lambda user: True)
    _login(plan_client, m1db.bob_id, "advisor", "Bob")
    assert plan_client.delete("/api/m1/plan-files/%d" % file_id).status_code == 403


# ---------------------------------------------------------------------------
# 内部版校验（每条规则一个 400）
# ---------------------------------------------------------------------------
def _mutations():
    def drop_session(doc):
        doc["sessions"].pop()

    def bad_focus(doc):
        doc["sessions"][0]["focus"]["primary"] = "R1.1"

    def bad_practice_code(doc):
        doc["sessions"][0]["practice"][0]["code"] = "R1.1"

    def bad_platform(doc):
        doc["sessions"][0]["practice"][0]["platform"] = "Other"

    def unknown_wb(doc):
        doc["sessions"][0]["activities"][0]["source"] = {
            "type": "world_bank", "wb_id": "WB-NOPE"}

    def empty_other(doc):
        doc["sessions"][0]["activities"][0]["source"] = {"type": "other", "text": ""}

    def duplicate_id(doc):
        doc["sessions"][1]["activities"][0]["id"] = doc["sessions"][0]["activities"][0]["id"]

    def no_block_review(doc):
        doc["sessions"][2]["activities"][-1]["block_review"] = False

    def early_block_review(doc):
        doc["sessions"][1]["activities"][-1]["block_review"] = True

    def short_review(doc):
        doc["sessions"][1]["review"] = [_field("只有一个")]

    return [
        (drop_session, "3 节课"),
        (bad_focus, "主要目标"),
        (bad_practice_code, "关联目标"),
        (bad_platform, "平台"),
        (unknown_wb, "WB 参考课"),
        (empty_other, "其他参考"),
        (duplicate_id, "重复"),
        (no_block_review, "Block Review"),
        (early_block_review, "Block Review"),
        (short_review, "2 到 3"),
    ]


@pytest.mark.parametrize("mutate,message", _mutations())
def test_internal_doc_validation_returns_400(plan_client, m1db, mutate, message):
    plan, _doc = _new_plan_with_version(m1db)
    _login(plan_client, m1db.alice_id, "advisor", "Alice")
    doc = copy.deepcopy(_doc)
    mutate(doc)
    res = plan_client.put("/api/m1/plans/%d/internal" % plan["id"],
                          json={"rev": plan["rev"], "doc": doc})
    assert res.status_code == 400, res.get_json()
    assert message in res.get_json()["error"]
    assert pstore.get_plan(plan["id"])["current_version_id"] == plan["current_version_id"]


def test_internal_save_accepts_legacy_string_reviews(plan_client, m1db):
    """旧 AI 初稿把回顾问题写成字符串，保存时也要能补成字段（否则批准会被挡住）。"""
    plan, doc = _new_plan_with_version(m1db)
    _login(plan_client, m1db.alice_id, "advisor", "Alice")
    legacy = copy.deepcopy(doc)
    for session in legacy["sessions"][1:]:
        session["review"] = [item["text"] for item in session["review"]]
    res = plan_client.put("/api/m1/plans/%d/internal" % plan["id"],
                          json={"rev": plan["rev"], "doc": legacy})
    assert res.status_code == 200, res.get_json()
    assert plan_client.post("/api/m1/plans/%d/approve" % plan["id"]).status_code == 200


def test_internal_save_and_rev_conflict(plan_client, m1db):
    plan, doc = _new_plan_with_version(m1db)
    _login(plan_client, m1db.alice_id, "advisor", "Alice")
    edited = copy.deepcopy(doc)
    edited["overview"] = _field("导师改过的概览")
    res = plan_client.put("/api/m1/plans/%d/internal" % plan["id"],
                          json={"rev": plan["rev"], "doc": edited})
    assert res.status_code == 200, res.get_json()
    assert res.get_json()["version_id"] != plan["current_version_id"]

    retry = plan_client.put("/api/m1/plans/%d/internal" % plan["id"],
                            json={"rev": plan["rev"], "doc": edited})
    assert retry.status_code == 409
    assert retry.get_json()["rev"] == res.get_json()["rev"]


# ---------------------------------------------------------------------------
# 家长版：保存 / 确认 / 导出
# ---------------------------------------------------------------------------
def test_parent_save_requires_matching_goals_and_refs(plan_client, m1db):
    plan, _doc = _new_plan_with_version(m1db)
    pstore.approve(plan["id"], m1db.alice_id)
    plan = pstore.get_plan(plan["id"])
    parent = _parent_doc(plan)
    pstore.add_version(plan["id"], part="parent", kind="ai_draft",
                       ai_doc=parent, doc=parent, checks=[],
                       source_version_id=plan["current_version_id"])
    pstore.finish_generation(plan["id"], "parent")
    plan = pstore.get_plan(plan["id"])
    _login(plan_client, m1db.alice_id, "advisor", "Alice")
    path = "/api/m1/plans/%d/parent" % plan["id"]

    bad = copy.deepcopy(parent)
    bad["goals"][0]["code"] = "R1.1"
    assert plan_client.put(path, json={"rev": plan["rev"], "doc": bad}).status_code == 400

    bad = copy.deepcopy(parent)
    bad["practice"] = ["nope"]
    assert plan_client.put(path, json={"rev": plan["rev"], "doc": bad}).status_code == 400

    res = plan_client.put(path, json={"rev": plan["rev"], "doc": parent})
    assert res.status_code == 200
    assert res.get_json()["plan"]["parent_status"] == "draft"


def test_export_refused_when_not_confirmed_or_stale(plan_client, m1db):
    plan, parent = _confirmed_plan(m1db)
    _login(plan_client, m1db.alice_id, "advisor", "Alice")
    path = "/api/m1/plans/%d/parent" % plan["id"]

    assert plan_client.post(path + "/export", json={"fits": False}).status_code == 409

    pstore.reopen(plan["id"])
    assert plan_client.post(path + "/export", json={"fits": True}).status_code == 409

    # 未确认（草稿）时导出同样被拒
    plan = pstore.get_plan(plan["id"])
    pstore.approve(plan["id"], m1db.alice_id)
    plan = pstore.get_plan(plan["id"])
    updated = plan_client.put(path, json={"rev": plan["rev"], "doc": parent}).get_json()
    assert updated["plan"]["parent_status"] == "draft"
    res = plan_client.post(path + "/export", json={"fits": True})
    assert res.status_code == 409
    assert "确认" in res.get_json()["error"]


def test_confirm_and_export_happy_path(plan_client, m1db):
    plan, _parent = _confirmed_plan(m1db)
    _login(plan_client, m1db.alice_id, "advisor", "Alice")
    path = "/api/m1/plans/%d/parent" % plan["id"]
    res = plan_client.post(path + "/export", json={"fits": True})
    assert res.status_code == 200, res.get_json()
    assert res.get_json()["plan"]["parent_status"] == "exported"
    assert res.get_json()["print_url"].endswith("/parent/print")


# ---------------------------------------------------------------------------
# 操作记录：自动保存不写 activities 列表
# ---------------------------------------------------------------------------
def test_internal_autosaves_do_not_fill_activity_list(plan_client, m1db):
    import m1.store as store

    plan, doc = _new_plan_with_version(m1db)
    _login(plan_client, m1db.alice_id, "advisor", "Alice")
    path = "/api/m1/plans/%d/internal" % plan["id"]
    for index in range(5):
        edited = copy.deepcopy(doc)
        edited["overview"] = _field("第 %d 次自动保存" % (index + 1))
        res = plan_client.put(path, json={"rev": plan["rev"], "doc": edited})
        assert res.status_code == 200, res.get_json()
        plan = pstore.get_plan(plan["id"])

    assert store.list_activity(plan["prep_id"], plan["student_id"]) == []


def test_activity_list_shows_create_and_approve_with_actor(plan_client, m1db):
    import m1.store as store

    prep, report = _published_prep(m1db)
    _login(plan_client, m1db.alice_id, "advisor", "Alice")
    payload = {"student_id": m1db.student_id, "prep_id": prep["id"], "block_no": 1,
               "period_start": "2026-11-17", "period_end": "2026-12-15",
               "wb_grade": 9}
    res = plan_client.post("/api/m1/plans", json=payload)
    assert res.status_code == 201, res.get_json()
    plan = pstore.get_plan(res.get_json()["plan"]["id"])
    pstore.save_goals(plan["id"], plan["rev"], [_goal()])
    plan = pstore.get_plan(plan["id"])
    version = pstore.add_version(plan["id"], part="internal", kind="ai_draft",
                                 ai_doc=_internal_doc(), doc=_internal_doc(), checks=[])
    pstore.finish_generation(plan["id"], "internal", version_id=version["id"])
    assert plan_client.post("/api/m1/plans/%d/approve" % plan["id"]).status_code == 200

    rows = store.list_activity(prep["id"], m1db.student_id)
    assert [row["text"] for row in rows] == ["批准内部教学计划", "新建发展计划"]
    assert all(row["actor"] == "Alice" for row in rows)
