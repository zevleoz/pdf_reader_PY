"""DP4：四项导航、三个列表页、列表 API 的扩展字段与学生页发展计划。"""
from __future__ import annotations

import json
import shutil
import subprocess

import pytest
from flask import Flask

import app_utils
import m1.plan_store as pstore
import m1.report_store as report_store
import m1.store as store
from app_utils import BASE_DIR
from test_m1_api import login_as
from test_m1_store import m1db  # noqa: F401  pytest fixture


@pytest.fixture()
def client(m1db, monkeypatch):  # noqa: F811
    from blueprints import m1 as m1_bp
    from blueprints import m1_plan as m1_plan_bp
    from blueprints import m1_report

    monkeypatch.setattr(app_utils, "is_authenticated", lambda: True)
    pstore.ensure_tables(m1db.engine)
    app = Flask(__name__, template_folder=str(BASE_DIR / "templates"))
    app.secret_key = "test-secret"
    app.register_blueprint(m1_bp.bp)
    app.register_blueprint(m1_plan_bp.bp)
    app.register_blueprint(m1_report.bp)
    app_utils.register_admin_context(app)
    app.context_processor(lambda: {"csrf_token": app_utils.get_csrf_token})
    app.add_template_filter(app_utils.dt_short, "dt_short")
    return app.test_client()


def _final_prep(db, student_id=None, mentor_id=None):
    prep = db.prep(student_id or db.student_id, mentor_id or db.alice_id)
    store.add_version(prep["id"], "ai_draft", doc={}, kb_version="test",
                      ai_generated_at=None)
    store.set_status(prep["id"], "final")
    return store.get_prep(prep["id"])


def _published_report(db, prep, *, transcript="家长说孩子最近总在睡前反复想白天的事。"):
    report = report_store.get_or_create_report(prep["id"], db.alice_id)
    if transcript:
        report_store.set_transcript(report["id"], text=transcript, filename="t.txt")
    report_store.add_version(report["id"], y4_ratings={}, evidence=[], ai_doc={},
                             doc={}, checks=[], manifest={}, status="approved")
    report_store.publish(report["id"], db.alice_id)
    return report_store.get_report(prep["id"])


def _plan(db, prep, report, block_no=1, student_id=None, mentor_id=None):
    return pstore.create_plan(
        student_id or prep["student_id"], prep_id=prep["id"], report_id=report["id"],
        report_version_id=report.get("current_version_id"),
        mentor_user_id=mentor_id or db.alice_id, block_no=block_no,
        period_start="2026-11-17", period_end="2026-12-15",
        credits="3", sessions=3, wb_grade=9, created_by=db.alice_id)


# ---------------------------------------------------------------------------
# 导航
# ---------------------------------------------------------------------------
def test_nav_has_four_items_and_marks_the_current_one(client, m1db):
    login_as(client, m1db.alice_id, "advisor", "Alice")
    html = client.get("/m1").get_data(as_text=True)
    for href in ("/m1", "/m1/preps", "/m1/reports", "/m1/plans"):
        assert 'href="%s"' % href in html
    for label in ("学生", "会前准备", "会后报告", "发展计划"):
        assert ">%s<" % label in html
    assert 'href="/m1" aria-current="page"' in html
    assert 'href="/m1/preps" aria-current="page"' not in html

    assert 'href="/m1/preps" aria-current="page"' in client.get("/m1/preps").get_data(as_text=True)
    assert 'href="/m1/reports" aria-current="page"' in client.get("/m1/reports").get_data(as_text=True)
    assert 'href="/m1/plans" aria-current="page"' in client.get("/m1/plans").get_data(as_text=True)

    prep = m1db.prep()
    student = client.get("/m1/preps/%d" % prep["id"]).get_data(as_text=True)
    assert 'href="/m1" aria-current="page"' in student
    workspace = client.get("/m1/preps/%d/prep" % prep["id"]).get_data(as_text=True)
    assert 'href="/m1/preps" aria-current="page"' in workspace
    report = client.get("/m1/preps/%d/report" % prep["id"]).get_data(as_text=True)
    assert 'href="/m1/reports" aria-current="page"' in report


# ---------------------------------------------------------------------------
# 三个列表页
# ---------------------------------------------------------------------------
def test_preps_list_page(client, m1db):
    login_as(client, m1db.alice_id, "advisor", "Alice")
    html = client.get("/m1/preps").get_data(as_text=True)
    assert '<div class="cr"><b>会前准备</b></div>' in html
    assert "First Meeting 前给导师用的提纲。按会议时间排。" in html
    assert 'data-kind="preps"' in html
    for tab in ("全部", "待生成", "待定稿", "已定稿"):
        assert ">%s<" % tab in html
    assert "/m1/assets/m1_lists.js" in html
    assert 'id="addStudent"' not in html


def test_reports_list_page(client, m1db):
    login_as(client, m1db.alice_id, "advisor", "Alice")
    html = client.get("/m1/reports").get_data(as_text=True)
    assert '<div class="cr"><b>会后报告</b></div>' in html
    assert "生成 AI 草稿后就可以开始发展计划" in html
    assert 'data-kind="reports"' in html
    for tab in ("全部", "待上传逐字稿", "待发布", "已发布"):
        assert ">%s<" % tab in html


def test_plans_list_page(client, m1db):
    login_as(client, m1db.alice_id, "advisor", "Alice")
    html = client.get("/m1/plans").get_data(as_text=True)
    assert '<div class="cr"><b>发展计划</b></div>' in html
    assert "会后报告生成 AI 草稿后可以新建" in html
    assert 'data-kind="plans"' in html
    for tab in ("全部", "待批准内部版", "待确认家长版", "已导出"):
        assert ">%s<" % tab in html
    assert 'id="newPlan"' in html
    assert 'id="planDlg"' in html
    assert 'id="m1Eligible"' in html


# ---------------------------------------------------------------------------
# /api/m1/preps 的扩展字段
# ---------------------------------------------------------------------------
def test_preps_api_adds_transcript_published_at_and_plan(client, m1db):
    login_as(client, m1db.alice_id, "advisor", "Alice")
    prep = _final_prep(m1db)
    report = _published_report(m1db, prep)
    plan = _plan(m1db, prep, report)

    payload = client.get("/api/m1/preps").get_json()
    row = [item for item in payload["preps"] if item["id"] == prep["id"]][0]
    assert row["transcript"] is True
    assert row["published_at"]
    assert row["plan"]["id"] == plan["id"]
    assert row["plan"]["block_no"] == 1
    assert row["plan"]["label"] == "资料与目标"
    assert row["plan"]["step_url"] == "/m1/plans/%d#step=inputs" % plan["id"]
    assert row["next"] is None or isinstance(row["next"], dict)

    overview = report_store.list_overview([prep["id"]])
    assert set(overview[prep["id"]].keys()) == {
        "status", "label", "started", "has_transcript", "updated_at"}


def test_preps_api_without_plan_keeps_plan_null(client, m1db):
    login_as(client, m1db.alice_id, "advisor", "Alice")
    prep = m1db.prep()
    row = [item for item in client.get("/api/m1/preps").get_json()["preps"]
           if item["id"] == prep["id"]][0]
    assert row["plan"] is None
    assert row["transcript"] is False
    assert row["published_at"] == ""


# ---------------------------------------------------------------------------
# 下一步：§2 的每一行
# ---------------------------------------------------------------------------
def test_next_step_one_case_per_row(client, m1db):
    login_as(client, m1db.alice_id, "advisor", "Alice")
    prep = m1db.prep()

    def next_of(prep_id):
        rows = client.get("/api/m1/preps").get_json()["preps"]
        return [row for row in rows if row["id"] == prep_id][0]["next"]

    assert next_of(prep["id"])["label"] == "生成"
    assert next_of(prep["id"])["href"] == "/m1/preps/%d/prep" % prep["id"]

    store.add_version(prep["id"], "ai_draft", doc={}, kb_version="test",
                      ai_generated_at=None)
    assert next_of(prep["id"])["label"] == "去定稿"
    assert next_of(prep["id"])["href"].endswith("/prep#step=review")

    store.set_status(prep["id"], "final")
    assert next_of(prep["id"])["label"] == "上传逐字稿"
    assert next_of(prep["id"])["href"] == "/m1/preps/%d/report" % prep["id"]

    report = report_store.get_or_create_report(prep["id"], m1db.alice_id)
    report_store.set_transcript(report["id"], text="逐字稿内容")
    assert next_of(prep["id"])["label"] == "继续会后报告"

    report_store.add_version(report["id"], y4_ratings={}, evidence=[], ai_doc={},
                             doc={}, checks=[], manifest={}, status="approved")
    report_store.publish(report["id"], m1db.alice_id)
    report = report_store.get_report(prep["id"])
    assert next_of(prep["id"])["label"] == "新建发展计划"
    assert next_of(prep["id"])["href"] == "/m1/plans?new=%d" % prep["id"]

    plan = _plan(m1db, prep, report)
    assert next_of(prep["id"])["label"] == "继续发展计划"

    pstore.finish_generation(plan["id"], "internal", status="review")
    assert next_of(prep["id"])["label"] == "审阅内部版"

    pstore.approve(plan["id"], m1db.alice_id)
    pstore.finish_generation(plan["id"], "parent", status="draft")
    assert next_of(prep["id"])["label"] == "确认家长版"

    pstore.confirm_parent(plan["id"], m1db.alice_id)
    pstore.export_parent(plan["id"], m1db.alice_id)
    assert next_of(prep["id"])["label"] == "打开发展计划"


# ---------------------------------------------------------------------------
# 学生页 overview
# ---------------------------------------------------------------------------
def test_student_overview_lists_plans_and_report_state(client, m1db):
    login_as(client, m1db.alice_id, "advisor", "Alice")
    prep = _final_prep(m1db)

    before = client.get("/api/m1/preps/%d/overview" % prep["id"]).get_json()
    assert before["can_create_plan"] is False
    assert before["plans"] == []

    drafted = report_store.get_or_create_report(prep["id"], m1db.alice_id)
    report_store.add_version(drafted["id"], y4_ratings={}, evidence=[], ai_doc={},
                             doc={}, checks=[], manifest={}, status="ai_draft")
    mid = client.get("/api/m1/preps/%d/overview" % prep["id"]).get_json()
    assert mid["can_create_plan"] is True

    report = _published_report(m1db, prep)
    after = client.get("/api/m1/preps/%d/overview" % prep["id"]).get_json()
    assert after["can_create_plan"] is True
    assert after["report_part"]["published_at"]
    assert after["plans"] == []

    plan = _plan(m1db, prep, report)
    data = client.get("/api/m1/preps/%d/overview" % prep["id"]).get_json()
    assert len(data["plans"]) == 1
    item = data["plans"][0]
    assert item["id"] == plan["id"]
    assert item["step_url"] == "/m1/plans/%d#step=inputs" % plan["id"]
    assert item["finished"] is False
    assert isinstance(item["goal_names"], dict)


# ---------------------------------------------------------------------------
# 可见性 / eligible
# ---------------------------------------------------------------------------
def test_plan_list_scope_respects_visibility(client, m1db):
    login_as(client, m1db.alice_id, "advisor", "Alice")
    prep = _final_prep(m1db)
    report = _published_report(m1db, prep)
    mine = _plan(m1db, prep, report)

    other_prep = _final_prep(m1db, m1db.other_student_id, m1db.bob_id)
    other_report = report_store.get_or_create_report(other_prep["id"], m1db.bob_id)
    report_store.add_version(other_report["id"], y4_ratings={}, evidence=[],
                             ai_doc={}, doc={}, checks=[], manifest={},
                             status="approved")
    report_store.publish(other_report["id"], m1db.bob_id)
    other = _plan(m1db, other_prep, report_store.get_report(other_prep["id"]),
                  student_id=m1db.other_student_id, mentor_id=m1db.bob_id)

    ids = [row["id"] for row in client.get("/api/m1/plans").get_json()["plans"]]
    assert mine["id"] in ids
    assert other["id"] not in ids


def test_eligible_requires_ai_draft_report(client, m1db):
    login_as(client, m1db.alice_id, "advisor", "Alice")
    published = _final_prep(m1db)
    _published_report(m1db, published)
    drafted = _final_prep(m1db, student_id=m1db.other_student_id)
    drafted_report = report_store.get_or_create_report(drafted["id"], m1db.alice_id)
    report_store.add_version(drafted_report["id"], y4_ratings={}, evidence=[],
                             ai_doc={}, doc={}, checks=[], manifest={},
                             status="ai_draft")
    pending = m1db.prep(m1db.incomplete_student_id)
    report_store.get_or_create_report(pending["id"], m1db.alice_id)

    students = client.get("/api/m1/plans/eligible").get_json()["students"]
    ids = [row["student_id"] for row in students]
    assert published["student_id"] in ids
    assert drafted["student_id"] in ids
    assert pending["student_id"] not in ids


def test_new_plan_dialog_grade_can_be_blank_and_says_what_is_missing():
    script = (BASE_DIR / "static" / "m1" / "m1_lists.js").read_text(encoding="utf-8")
    first = script.index("先选择学生")
    second = script.index("填好阶段开始和结束后就可以新建")
    third = script.index("会后报告生成 AI 草稿后就可以新建")
    assert first < second < third
    assert "if (gradeValue) body.wb_grade" in script

    html = (BASE_DIR / "templates" / "m1" / "lists.html").read_text(encoding="utf-8")
    assert "参考年级（可不填）" in html
    assert '<option value="">不填</option>' in html
    assert 'id="planHint"' in html


# ---------------------------------------------------------------------------
# 列表排序（页面脚本里的纯函数）
# ---------------------------------------------------------------------------
@pytest.mark.skipif(shutil.which("node") is None, reason="node 未安装")
def test_list_sorting_helpers():
    script = (
        "var h=require(%s);"
        "var preps=[{id:1,status:'final',meeting_date:'2026-11-01'},"
        "{id:2,status:'final',meeting_date:'2026-11-05'},"
        "{id:3,status:'draft',meeting_date:'2026-11-07'},"
        "{id:4,status:'final',meeting_date:'2026-11-03'}];"
        "var reports=[{id:1,meeting_date:'2026-11-02',published_at:'2026-11-05',"
        "report:{status:'published'}},"
        "{id:2,meeting_date:'2026-11-04',published_at:'',report:{status:'draft'}},"
        "{id:3,meeting_date:'2026-11-01',published_at:'2026-11-09',"
        "report:{status:'published'}}];"
        "var dup=[{id:1,student_id:7,meeting_date:'2026-11-01'},"
        "{id:2,student_id:7,meeting_date:'2026-11-06'},"
        "{id:3,student_id:8,meeting_date:'2026-10-01'}];"
        "console.log(JSON.stringify({preps:h.sortPreps(preps).map(function(r){return r.id}),"
        "reports:h.sortReports(reports).map(function(r){return r.id}),"
        "dup:h.uniqueByStudent(dup).map(function(r){return r.id})}));"
    ) % json.dumps(str(BASE_DIR / "static" / "m1" / "m1_lists.js"))
    out = subprocess.run(["node", "-e", script], capture_output=True, text=True,
                         check=True).stdout
    result = json.loads(out)
    assert result["preps"] == [3, 2, 4, 1]
    assert result["reports"] == [2, 3, 1]
    assert result["dup"] == [2, 3]


@pytest.mark.parametrize("prep_status,version", [("draft", None), ("ai_draft", 10)])
@pytest.mark.parametrize("status,parent,label,step", [
    ("inputs", "none", "继续发展计划", "inputs"),
    ("generating", "none", "查看生成进度", "internal"),
    ("review", "none", "审阅内部版", "internal"),
    ("approved", "none", "生成家长版", "parent"),
    ("approved", "generating", "查看家长版生成", "parent"),
    ("approved", "draft", "确认家长版", "parent"),
    ("approved", "confirmed", "导出家长版", "parent"),
    ("approved", "exported", "打开发展计划", "parent"),
])
def test_next_step_resumes_plan_before_old_prep(prep_status, version, status, parent, label, step):
    from blueprints.m1 import _next_step
    prep = {"id": 7, "status": prep_status, "current_version_id": version}
    plan = {"id": 9, "status": status, "parent_status": parent}
    action = _next_step(prep, {"started": True, "status": "published"}, plan)
    assert action["label"] == label
    assert action["href"] == "/m1/plans/9#step=" + step
    assert _next_step(prep, None, plan) == action


@pytest.mark.parametrize("status,label,suffix", [
    ("draft", "继续会后报告", "/report"),
    ("generating", "查看生成进度", "/report"),
    ("ai_draft", "核对发布", "/report#step=review"),
    ("published", "新建发展计划", None),
])
def test_next_step_resumes_report_before_old_prep(status, label, suffix):
    from blueprints.m1 import _next_step
    action = _next_step({"id": 7, "status": "ai_draft"},
                        {"started": True, "status": status}, None)
    assert action["label"] == label
    assert action["href"] == ("/m1/preps/7" + suffix if suffix else "/m1/plans?new=7")


@pytest.mark.skipif(shutil.which("node") is None, reason="node 未安装")
def test_student_next_step_downstream_priority_and_labels():
    source = (BASE_DIR / "static/m1/m1_student.js").read_text()
    function = source[source.index("  function nextStep(data)"):source.index("  function renderHead(data)")]
    script = function + """
const assert = require('assert');
const data = {prep:{id:7}, prep_part:{has_doc:true,status:'ai_draft'},
  report_part:{started:true,status:'published'}, plans:[]};
assert.equal(nextStep(data).button, '新建发展计划');
for (const [status, parent_status, button] of [
  ['inputs','none','继续发展计划'], ['generating','none','查看生成进度'],
  ['review','none','审阅内部版'], ['approved','generating','查看生成进度'],
  ['approved','none','生成家长版'], ['approved','draft','确认家长版'],
  ['approved','confirmed','导出家长版'], ['approved','exported','打开发展计划']]) {
  data.plans = [{id:9,block_no:1,status,parent_status,step_url:'/m1/plans/9#step=current'}];
  assert.equal(nextStep(data).button, button);
  assert.equal(nextStep(data).href, data.plans[0].step_url);
}
data.plans = [];
for (const [status,button] of [['draft','继续会后报告'],['generating','查看生成进度'],['ai_draft','核对发布']]) {
  data.report_part.status = status;
  assert.equal(nextStep(data).button,button);
}
data.report_part.started = false;
assert.equal(nextStep(data).button,'去定稿');
data.prep_part.has_doc = false;
assert.equal(nextStep(data).button,'开始会前准备');
"""
    subprocess.run(["node", "-e", script], check=True, capture_output=True, text=True)


@pytest.mark.skipif(shutil.which("node") is None, reason="node 未安装")
def test_list_row_destinations_and_nested_controls():
    source = (BASE_DIR / "static/m1/m1_lists.js").read_text()
    action = source[source.index("  function planAction("):source.index("  function planRow(")]
    row = source[source.index("  function makeRow("):source.index("  function headerRow(")]
    routing = source[source.index("      var href = kind === 'plans'"):source.index("      listHost.appendChild(makeRow")]
    script = action + row + """
const assert = require('assert');
function destination(kind, row) {
""" + routing + """
return href;
}
assert.equal(destination('reports',{id:7,report:{status:'published'}}),'/m1/preps/7/report');
assert.equal(destination('preps',{id:7,status:'final',current_version_id:1}),'/m1/preps/7/prep');
assert.equal(destination('preps',{id:7,status:'ai_draft',current_version_id:1}),'/m1/preps/7/prep#step=review');
assert.equal(destination('plans',{id:9,next:{hash:'#step=internal'}}),'/m1/plans/9#step=internal');
assert.equal(destination('plans',{id:9,next:{hash:'#step=parent'}}),'/m1/plans/9#step=parent');
let handlers = {};
function el() {return {dataset:{},setAttribute(){},appendChild(){},addEventListener(k,v){handlers[k]=v;}};}
const window = {location:{href:''}};
const node = makeRow({student_name:'Test'},[], '/workflow');
handlers.click({target:{closest(){return true;}}});
assert.equal(window.location.href,'');
handlers.keydown({target:{},key:'Enter',preventDefault(){throw Error('nested control intercepted');}});
assert.equal(window.location.href,'');
handlers.keydown({target:node,key:'Enter',preventDefault(){}});
assert.equal(window.location.href,'/workflow');
window.location.href='';
handlers.click({target:{closest(){return null;}}});
assert.equal(window.location.href,'/workflow');
"""
    subprocess.run(["node", "-e", script], check=True, capture_output=True, text=True)
