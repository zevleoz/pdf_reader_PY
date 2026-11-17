from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from flask import Flask, render_template

from app_utils import BASE_DIR
from test_m1_pipeline import _login
from test_m1_store import m1db  # noqa: F401  pytest fixture
from test_m1dp_api import plan_client  # noqa: F401  pytest fixture

ROOT = Path(__file__).resolve().parent


def _direct_plan(client, m1db, student_id=None, **extra):
    _login(client, m1db.alice_id, "advisor", "Alice")
    body = {"source_mode": "mentor_inputs", "student_id": student_id or m1db.student_id,
            "block_no": 1, "period_start": "2026-11-02",
            "period_end": "2026-12-18", "credits": "3"}
    body.update(extra)
    res = client.post("/api/m1/plans", json=body)
    assert res.status_code == 201, res.get_data(as_text=True)
    return res.get_json()["plan"]


def test_lists_page_offers_report_and_direct_creation(plan_client, m1db):
    _login(plan_client, m1db.alice_id, "advisor", "Alice")
    html = plan_client.get("/m1/plans").get_data(as_text=True)
    for marker in ("从会后报告创建", "直接创建教案", 'id="planMode"',
                   'id="planMentorUser"', 'id="planMentorSelfWrap"',
                   'id="planGradeWrap"', 'id="planError"', "m1_lists.js"):
        assert marker in html
    assert 'data-can-assign-mentor="0"' in html

    _login(plan_client, m1db.admin_id, "admin")
    admin_html = plan_client.get("/m1/plans").get_data(as_text=True)
    assert 'data-can-assign-mentor="1"' in admin_html


def test_student_hub_renders_html_and_json_stays_available(plan_client, m1db):
    plan = _direct_plan(plan_client, m1db)
    html = plan_client.get(f"/m1/students/{m1db.student_id}").get_data(as_text=True)
    assert 'id="m1StudentHub"' in html
    assert "m1_student_hub.js" in html
    assert "林晓雨" in html
    assert "直接创建" in html

    payload = plan_client.get(f"/api/m1/students/{m1db.student_id}/overview").get_json()
    assert payload["plans"][0]["id"] == plan["id"]
    assert payload["plans"][0]["source_mode"] == "mentor_inputs"
    assert payload["preps"] == []

    _login(plan_client, m1db.bob_id, "advisor", "Bob")
    assert plan_client.get(f"/m1/students/{m1db.student_id}").status_code == 404
    _login(plan_client, m1db.viewer_id, "viewer")
    assert plan_client.get(f"/m1/students/{m1db.student_id}").status_code == 403


def test_direct_inputs_partial_exposes_mount_contract_and_initial_data():
    app = Flask(__name__, template_folder=str(BASE_DIR / "templates"))
    plan = {"id": 21, "rev": 4, "source_mode": "mentor_inputs", "status": "inputs",
            "brief_revision": 0, "brief_confirmed_revision": None,
            "session_durations": [60, 60, 60], "inputs": {}, "brief": [], "goals": []}
    with app.app_context():
        html = render_template("m1/_direct_inputs.html", plan=plan, files=[],
                               goals=[], step1_editable=True)
        report = render_template("m1/_direct_inputs.html",
                                 plan={**plan, "source_mode": "report"}, files=[],
                                 goals=[], step1_editable=True)

    for marker in ('id="m1DirectInputs"', 'data-plan-id="21"',
                   'data-source-mode="mentor_inputs"', 'data-rev="4"',
                   'data-role="brief"', 'data-role="profile"',
                   'data-role="confirm-brief"', 'data-role="extract"',
                   'data-role="file-input"', 'data-role="goals"',
                   'direct_inputs.css', 'direct_inputs.js'):
        assert marker in html
    assert "m1DirectInputs" not in report

    match = re.search(r'<script type="application/json" data-role="initial">(.*?)</script>',
                      html, re.S)
    data = json.loads(match.group(1))
    assert data["plan"]["id"] == 21
    assert data["plan"]["rev"] == 4
    assert data["can_edit"] is True


@pytest.mark.skipif(shutil.which("node") is None, reason="node 未安装")
def test_ui_pure_helpers_for_direct_creation_and_brief():
    paths = json.dumps([str(ROOT / "static/m1/m1_lists.js"),
                        str(ROOT / "static/m1/direct_inputs.js"),
                        str(ROOT / "static/m1/m1_student_hub.js")])
    script = """
const fs = require('fs');
const vm = require('vm');
const paths = %s;
function load(path) {
  const context = {module: {exports: {}}};
  vm.runInNewContext(fs.readFileSync(path, 'utf8'), context);
  return context.module.exports;
}
function assert(ok, message) { if (!ok) { console.error(message); process.exit(1); } }
const lists = load(paths[0]);
const direct = load(paths[1]);
const hub = load(paths[2]);

const directPayload = lists.creationPayload('direct', {
  studentId: '8', blockNo: '2', periodStart: '2026-11-02',
  periodEnd: '2026-12-18', credits: '3', wbGrade: '', mentorUserId: '5'
});
assert(directPayload.source_mode === 'mentor_inputs', 'direct source mode');
assert(directPayload.prep_id === undefined, 'direct must not send prep_id');
assert(directPayload.student_id === 8 && directPayload.block_no === 2, 'direct ids numeric');
assert(directPayload.mentor_user_id === 5, 'direct mentor id');
assert(directPayload.wb_grade === undefined, 'blank grade omitted');

const reportPayload = lists.creationPayload('report', {
  studentId: '8', prepId: '30', blockNo: '1', periodStart: '2026-11-02',
  periodEnd: '2026-12-18', credits: '', wbGrade: 'G6'
});
assert(reportPayload.prep_id === 30 && reportPayload.source_mode === undefined, 'report path');
assert(reportPayload.wb_grade === 6, 'report grade retained');

assert(lists.gradeVisible('direct', {wb_grade: 7}) === true, 'direct grade optional');
assert(lists.gradeVisible('report', {wb_grade: 7}) === false, 'report grade hidden');
assert(lists.planHintText('report', {eligibleCount: 0}).indexOf('会后报告') >= 0, 'report gate hint');
assert(lists.planHintText('direct', {eligibleCount: 2, hasStudent: true, hasDates: true,
  hasMentor: false}).indexOf('导师') >= 0, 'direct mentor required');

const empty = direct.briefFromPlan({teaching_brief: {}});
assert(Object.keys(empty).length === 12, 'all 12 brief fields');
assert(direct.missingTeaching(empty).length === 3, 'three teaching inputs required');
assert(direct.missingTeaching(empty).map(function (f) { return f.label; }).join('|') ===
  '学习需求|当前情境|当前反应', 'missing labels');
['learning_need', 'current_situation', 'current_response'].forEach(function (key) {
  empty[key] = direct.normalizeEntry({text: '已写', provenance: 'mentor', use_for_teaching: true});
});
assert(direct.missingTeaching(empty).length === 0, 'minimum teaching inputs complete');

const payload = direct.briefPayload(empty);
assert(Object.keys(payload).length === 12, 'brief payload keeps all fields');
assert(payload.learning_need && 'disclosure' in payload.learning_need,
  'brief payload contract');
const signature = direct.briefSignature(empty);
empty.strengths = direct.normalizeEntry({text: '保留其他修改', provenance: 'mentor'});
assert(direct.briefSignature(empty) !== signature, 'signature detects local edits');
assert(direct.briefPayload(empty).learning_need.use_for_teaching === true,
  'unrelated brief edits preserved');

const profile = direct.profileFromPlan({inputs: {strengths: {text: '优势', src: 'ai'}}});
assert(Object.keys(profile).length === 4, 'all profile inputs');
assert(direct.profilePayload(profile).interests.text === '', 'blank profile preserved');
assert(direct.provenanceLabel('parent') === '家长', 'source label');

assert(hub.planStep('confirm_brief') === 'inputs', 'brief step');
assert(hub.planStep('review_internal') === 'internal', 'internal step');
assert(hub.planStep('export_parent') === 'parent', 'parent step');
assert(hub.planLabel({next_action: {action: 'confirm_brief'}}) === '确认教学简报', 'label');
assert(hub.planHref({id: 5, next_action: {action: 'generate_parent'}}) ===
  '/m1/plans/5#step=parent', 'href');
const next = hub.nextStepFor({student: {id: 9}, plans: []});
assert(next.href === '/m1/plans?new_student=9&mode=direct', 'zero-meeting next step');
""" % paths
    subprocess.run(["node", "-e", script], check=True, capture_output=True, text=True)


def test_ui_source_covers_conflicts_extraction_and_explicit_confirmation():
    lists_js = (ROOT / "static/m1/m1_lists.js").read_text(encoding="utf-8")
    direct_js = (ROOT / "static/m1/direct_inputs.js").read_text(encoding="utf-8")
    for marker in ("source_mode=mentor_inputs", "mentor_user_id", "planError",
                   "event.key === 'Escape'", "直接创建不需要会后报告"):
        assert marker in lists_js
    for marker in ("409", "teaching_brief", "/brief/confirm", "用于教学",
                   "提取已完成，但你在提取期间修改了内容",
                   "可进入家长版", "setRev", "flush"):
        assert marker in direct_js
