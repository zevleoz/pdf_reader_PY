"""DP5：发展计划页面（① 资料与目标 / ② 内部版审阅 / 内部版打印）。"""
from __future__ import annotations

import html as html_lib
import re

import pytest
from flask import Flask

import m1.plan_kb as plan_kb
import m1.plan_store as pstore
import m1.report_store as report_store
from app_utils import BASE_DIR
from test_m1_pipeline import _login
from test_m1_store import m1db  # noqa: F401  pytest fixture
from test_m1dp_store import _create, _goal, _published_prep


@pytest.fixture()
def page_client(m1db, monkeypatch):  # noqa: F811
    import app_utils
    from blueprints import m1 as m1_api
    from blueprints import m1_plan

    pstore.ensure_tables(m1db.engine)
    monkeypatch.setattr(app_utils, "is_authenticated", lambda: True)
    app = Flask(__name__, template_folder=str(BASE_DIR / "templates"))
    app.secret_key = "test-secret"
    app.config["TESTING"] = True
    app.register_blueprint(m1_api.bp)
    app.register_blueprint(m1_plan.bp)
    return app.test_client()


def _field(text):
    return {"text": text, "src": "ai"}


def _internal_doc(code="R2.2", *, review_checks=None):
    doc = {"overview": _field("Overall overview"), "mentor_notes": _field(""),
           "sessions": []}
    for n in (1, 2, 3):
        activities = [
            {"id": "s%da1" % n, "name": _field("Warm up %d" % n),
             "minutes": 10, "steps": _field("Step %d" % n),
             "questions": _field("Question %d" % n), "materials": _field("Material %d" % n),
             "source": {"type": "ai_original"}, "block_review": False},
            {"id": "s%da2" % n, "name": _field("Core %d" % n),
             "minutes": 20, "steps": _field("Core steps %d" % n),
             "questions": _field("Core question %d" % n),
             "materials": _field("Core material %d" % n),
             "source": {"type": "world_bank", "wb_id": "WB1"},
             "block_review": False},
        ]
        if n == 3:
            activities.append({
                "id": "s3a3", "name": _field("Block Review"),
                "minutes": 10, "steps": _field("回顾本阶段"),
                "questions": _field("带回生活的一个问题"),
                "materials": _field("回顾卡"),
                "source": {"type": "ai_original"}, "block_review": True,
            })
        doc["sessions"].append({
            "n": n, "title": _field("Session title %d" % n),
            "review": [] if n == 1 else [_field("上次回顾")],
            "focus": {"primary": code, "supporting": None, "text": _field("Focus %d" % n)},
            "content": {"mindsets": _field("Mindset"), "path": _field("Path"),
                        "skills": _field("Skill"), "techniques": _field("Technique")},
            "activities": activities,
            "evidence": _field("Evidence %d" % n),
            "practice": [{"id": "s%dp1" % n, "code": code, "name": _field("Practice %d" % n),
                          "task": _field("Task %d" % n), "frequency": _field("每天"),
                          "platform": "StoryMap", "evidence": _field("Proof %d" % n)}],
            "next_prep": None if n == 3 else _field("Next prep %d" % n),
        })
    return doc


def _plan_with_internal(db, doc=None, checks=None):
    prep, report = _published_prep(db)
    plan = _create(db, prep, report)
    plan = pstore.save_goals(plan["id"], plan["rev"], [_goal()])
    doc = doc or _internal_doc()
    checks = checks if checks is not None else [
        {"level": "review", "label": "第 1 节 · 活动 2", "text": "核对 WB 来源",
         "path": ["sessions", 0, "activities", 1, "source", "type"]},
        {"level": "hint", "label": "长度", "text": "有点长", "path": []},
    ]
    version = pstore.add_version(plan["id"], part="internal", kind="ai_draft",
                                 ai_doc=doc, doc=doc, checks=checks)
    pstore.finish_generation(plan["id"], "internal", version_id=version["id"])
    return pstore.get_plan(plan["id"])


def _mentor(client, db):
    _login(client, db.alice_id, "advisor", "Alice")


def _viewer(client, db):
    _login(client, db.bob_id, "advisor", "Bob")
    with client.session_transaction() as sess:
        sess["student_scope"] = "all"


def _block(html, marker):
    start = html.index(marker)
    end = html.find('data-block-review=', start + 1)
    if end < 0:
        end = len(html)
    return html[start:end]


# ---------------------------------------------------------------------------
# 页面权限与基本结构
# ---------------------------------------------------------------------------
def test_page_requires_access_and_marks_read_only(page_client, m1db):
    plan = _plan_with_internal(m1db)

    _mentor(page_client, m1db)
    html = page_client.get("/m1/plans/%d" % plan["id"]).get_data(as_text=True)
    assert "资料与目标" in html
    assert "内部版 · AI 初稿" in html
    assert "① 资料与目标" in html and "② 内部版审阅批准" in html
    assert "批准内部版" in html
    assert "/m1/plans/%d/print" % plan["id"] in html
    assert "会用 AI 重写这一节" in html

    _viewer(page_client, m1db)
    html = page_client.get("/m1/plans/%d" % plan["id"]).get_data(as_text=True)
    assert "只读：只有负责导师 Alice 可以修改" in html
    for marker in ('id="approveBtn"', 'id="genBtn"', 'data-regen=', 'id="regenOk"',
                   'data-op="add-activity"', "上传会议记录"):
        assert marker not in html

    _login(page_client, m1db.bob_id, "advisor", "Bob")
    with page_client.session_transaction() as sess:
        sess.pop("student_scope", None)  # 回到默认 own 范围
    assert page_client.get("/m1/plans/%d" % plan["id"]).status_code == 404
    assert page_client.get("/m1/plans/999999").status_code == 404


def test_approved_page_is_locked(page_client, m1db):
    plan = _plan_with_internal(m1db)
    pstore.approve(plan["id"], m1db.alice_id)
    _mentor(page_client, m1db)
    html = page_client.get("/m1/plans/%d" % plan["id"]).get_data(as_text=True)
    assert "内部版 · 已批准" in html
    assert "已批准" in html and "重新打开" in html
    assert 'contenteditable="true"' not in html
    assert 'data-regen=' not in html
    assert 'id="approveBtn"' not in html


def test_block_review_text_comes_from_kb(page_client, m1db):
    doc = _internal_doc()
    review = doc["sessions"][2]["activities"][2]
    review["name"] = _field("JUNK NAME")
    review["steps"] = _field("JUNK STEPS")
    review["materials"] = _field("JUNK MATERIAL")
    review["source"] = {"type": "other", "text": "JUNK SOURCE"}
    review["questions"] = {"text": "", "src": "mentor"}
    plan = _plan_with_internal(m1db, doc=doc, checks=[])
    kb = plan_kb.block_review()
    _mentor(page_client, m1db)

    html = page_client.get("/m1/plans/%d" % plan["id"]).get_data(as_text=True)
    block = html_lib.unescape(_block(html, 'data-block-review="1"'))
    assert kb["name"] in block
    for part in kb["parts"]:
        assert part["label"] in block and part["text"] in block
    assert kb["note"] in block
    assert "引导问题：" in block
    assert 'data-path="sessions.2.activities.2.minutes"' in block
    # 页面状态 JSON 里仍带着原始 doc，只看渲染出来的部分
    assert "JUNK" not in html.split("window.M1_PLAN")[0]
    assert "参考来源" not in block
    assert "所需材料" not in block

    printed = html_lib.unescape(
        page_client.get("/m1/plans/%d/print" % plan["id"]).get_data(as_text=True))
    start = printed.index(kb["name"])
    end = printed.index("D｜课堂预期表现", start)
    pblock = printed[start:end]
    assert "约 %d 分钟" % review["minutes"] in pblock
    for part in kb["parts"]:
        assert part["label"] in pblock and part["text"] in pblock
    assert kb["note"] in pblock
    assert "引导问题" not in pblock
    assert "参考来源" not in pblock
    assert "所需材料" not in pblock
    assert "JUNK" not in printed


def test_block_review_has_no_delete_or_move_controls(page_client, m1db):
    plan = _plan_with_internal(m1db)
    _mentor(page_client, m1db)
    html = page_client.get("/m1/plans/%d" % plan["id"]).get_data(as_text=True)

    review = _block(html, 'data-block-review="1"')
    assert "Block Review" in review
    assert 'data-op="del-activity"' not in review
    assert 'data-op="up"' not in review
    assert 'data-op="down"' not in review
    assert 'data-path="sessions.2.activities.2.questions.text"' in review
    assert 'data-path="sessions.2.activities.2.steps.text"' not in review


def test_personal_and_doc_saves_share_one_plan_rev(page_client, m1db):
    """DP5-c：同一页面上的个性化需求与内部版保存共用 plan rev，不互相作废。"""
    doc = _internal_doc()
    doc["mentor_notes"] = _field("导师备注")
    for n, session in enumerate(doc["sessions"], start=1):
        if n > 1:
            session["review"] = [_field("回顾一"), _field("回顾二")]
        for activity in session["activities"]:
            activity["source"] = {"type": "ai_original"}
    plan = _plan_with_internal(m1db, doc=doc, checks=[])
    _mentor(page_client, m1db)
    path = "/api/m1/plans/%d" % plan["id"]

    res = page_client.put(path + "/personal", json={"rev": plan["rev"], "notes": "导师备注"})
    assert res.status_code == 200, res.get_json()
    rev = res.get_json()["plan"]["rev"]
    assert rev == plan["rev"] + 1

    res = page_client.put(path + "/internal", json={"rev": rev, "doc": doc})
    assert res.status_code == 200, res.get_json()
    assert res.get_json()["rev"] == rev + 1

    js = (BASE_DIR / "static" / "m1" / "plan.js").read_text(encoding="utf-8")
    assert "docRev" not in js
    html = page_client.get("/m1/plans/%d" % plan["id"]).get_data(as_text=True)
    assert "internalRev" not in html


def test_generate_button_waits_for_locked_goal(page_client, m1db):
    prep, report = _published_prep(m1db)
    plan = _create(m1db, prep, report)
    _mentor(page_client, m1db)

    html = page_client.get("/m1/plans/%d" % plan["id"]).get_data(as_text=True)
    assert 'id="genBtn" disabled' in html or 'disabled id="genBtn"' in html
    assert "需要 1 到 3 项已锁定目标" in html

    pstore.save_goals(plan["id"], plan["rev"], [_goal()])
    pstore.save_inputs_ai(plan["id"], {"strengths": _field("愿意开口"),
                                      "needs": _field("需要练习表达"),
                                      "context": _field("课堂发言"),
                                      "interests": _field("篮球")})
    html = page_client.get("/m1/plans/%d" % plan["id"]).get_data(as_text=True)
    assert re.search(r'<button class="btn p" id="genBtn">', html)


def test_wb_cards_show_installed_candidates(page_client, m1db, monkeypatch):
    from m1 import wb

    plan = _plan_with_internal(m1db)
    _mentor(page_client, m1db)

    monkeypatch.setattr(pstore, "_wb_installed", lambda: False)
    html = page_client.get("/m1/plans/%d" % plan["id"]).get_data(as_text=True)
    assert "WB 参考资料未安装" in html

    monkeypatch.setattr(pstore, "_wb_installed", lambda: True)
    monkeypatch.setattr(wb, "candidates", lambda code, grade: [
        {"wb_id": "WB1", "cite": "G9 · LESSON ONE · PDF p.59",
         "skill": "Frustration Tolerance", "match": "直接对应", "limit": "只作思路"},
    ])
    monkeypatch.setattr(wb, "lesson", lambda wb_id: {"name": "LESSON ONE"})
    monkeypatch.setattr(wb, "cite", lambda wb_id: "G9 · LESSON ONE · PDF p.59")
    html = page_client.get("/m1/plans/%d" % plan["id"]).get_data(as_text=True)
    assert "R2.2 · LESSON ONE" in html
    assert "G9 · LESSON ONE · PDF p.59" in html
    assert "直接对应" in html


def test_read_goal_chips_and_three_goal_limit(page_client, m1db):
    prep, report = _published_prep(m1db)
    version = report_store.add_version(
        report["id"], y4_ratings={}, evidence=[], ai_doc={},
        doc={"plan": [{"ability": "R2.2"}, {"ability": "R3.3"}]},
        checks=[], manifest={}, status="approved")
    report_store.publish(report["id"], m1db.alice_id)
    report = report_store.get_report(prep["id"])
    plan = _create(m1db, prep, report, report_version_id=version["id"])
    plan = pstore.save_goals(plan["id"], plan["rev"], [_goal()])
    _mentor(page_client, m1db)

    html = page_client.get("/m1/plans/%d" % plan["id"]).get_data(as_text=True)
    assert "会后报告的阶段发展重点" in html
    assert "R2.2" in html and "R3.3" in html
    assert "已添加" in html
    assert 'data-add-goal="R3.3"' in html

    # 满 3 项后不再出现添加下拉框；第 4 项由数据层拒绝
    plan = pstore.save_goals(plan["id"], plan["rev"],
                             [_goal("R2.2"), _goal("R3.3"), _goal("R1.1", locked=False)])
    html = page_client.get("/m1/plans/%d" % plan["id"]).get_data(as_text=True)
    assert 'id="addGoal"' not in html
    with pytest.raises(ValueError, match="最多 3 项目标"):
        pstore.validate_goals([_goal("R2.2"), _goal("R3.3"), _goal("R1.1"),
                               _goal("R1.2")])


def test_no_chips_when_report_has_no_plan(page_client, m1db):
    plan = _plan_with_internal(m1db)
    _mentor(page_client, m1db)
    html = page_client.get("/m1/plans/%d" % plan["id"]).get_data(as_text=True)
    assert "会后报告的阶段发展重点" not in html


# ---------------------------------------------------------------------------
# 打印
# ---------------------------------------------------------------------------
def test_print_page_draft_and_approved(page_client, m1db):
    plan = _plan_with_internal(m1db, checks=[
        {"level": "review", "label": "核对标记", "text": "CHECK_MARKER_9137", "path": []},
    ])
    _mentor(page_client, m1db)
    html = page_client.get("/m1/plans/%d/print" % plan["id"]).get_data(as_text=True)
    assert "Overall overview" in html
    assert "Session title 1" in html
    assert "Core steps 3" in html
    assert "draftmark" in html and "草稿" in html
    assert "CHECK_MARKER_9137" not in html
    assert "AI 提取" not in html and "class=\"ai\"" not in html
    assert 'data-path=' not in html

    pstore.approve(plan["id"], m1db.alice_id)
    html = page_client.get("/m1/plans/%d/print" % plan["id"]).get_data(as_text=True)
    assert "draftmark" not in html
    assert "草稿" not in html

    html = page_client.get("/m1/plans/%d/print?print=1" % plan["id"]).get_data(as_text=True)
    assert "window.print()" in html


def test_print_404_without_internal_or_access(page_client, m1db):
    prep, report = _published_prep(m1db)
    plan = _create(m1db, prep, report, block_no=2)
    _mentor(page_client, m1db)
    assert page_client.get("/m1/plans/%d/print" % plan["id"]).status_code == 404

    plan = _plan_with_internal(m1db)
    _login(page_client, m1db.bob_id, "advisor", "Bob")
    assert page_client.get("/m1/plans/%d/print" % plan["id"]).status_code == 404
