"""DP13-C：共同导师、在线状态与分段协作编辑器界面。"""
from __future__ import annotations

import copy
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

import m1.plan_collaboration as collab
import m1.plan_store as pstore
from test_dp13_collab import _acquire, _client_for, _patch
from test_m1_pipeline import _login
from test_m1_store import m1db  # noqa: F401  pytest fixture
from test_m1dp_api import _new_plan_with_version, plan_client  # noqa: F401
from test_m1dp_pages_parent import _parent_doc, _with_parent  # noqa: F401

ROOT = Path(__file__).resolve().parent

_APPROVE_HINT = "共同导师可以编辑，但批准和导出由负责导师或管理员完成。"
_PARENT_HINT = "共同导师可以修改家长版，确认和导出由负责导师或管理员完成。"


def _admin(db):
    return {"user_id": db.admin_id, "role": "admin", "advisor_name": "",
            "display_name": "Admin"}


def _page_state(html: str) -> dict:
    match = re.search(r"window\.M1_PLAN = (\{.*?\});</script>", html, re.S)
    assert match, "计划页必须输出 window.M1_PLAN"
    return json.loads(match.group(1))


def test_plan_page_exposes_collaboration_panel_and_page_state(plan_client, m1db):
    plan, _doc = _new_plan_with_version(m1db)
    _login(plan_client, m1db.alice_id, "advisor", "Alice")
    html = plan_client.get("/m1/plans/%d" % plan["id"]).get_data(as_text=True)

    for marker in ('id="collabPanel"', 'id="collabConflicts"',
                   'id="collabList"', 'id="collabOffline"',
                   "协作状态", "plan_collab_core.js",
                   'id="approveBtn"', "window.M1_PLAN"):
        assert marker in html, marker

    state = _page_state(html)
    assert state["userId"] == m1db.alice_id
    assert state["canEdit"] is True and state["canApprove"] is True
    collaboration = state["collaboration"]
    assert collaboration["document_version"] >= 1
    assert collaboration["poll_seconds"] >= 5
    assert collaboration["lease_ttl"] and collaboration["presence_ttl"]
    assert collaboration["permissions"]["role"] in ("primary", "admin")
    assert "sections" in collaboration and "team" in collaboration


def test_co_mentor_can_edit_but_approval_and_export_are_hidden(plan_client, m1db):
    plan, _doc = _new_plan_with_version(m1db)
    collab.add_team_member(m1db.student_id, m1db.bob_id, _admin(m1db))

    _login(plan_client, m1db.bob_id, "advisor", "Bob")
    html = plan_client.get("/m1/plans/%d" % plan["id"]).get_data(as_text=True)
    assert _APPROVE_HINT in html
    assert 'id="approveBtn"' not in html
    assert "共同导师 Bob" in html

    state = _page_state(html)
    assert state["canEdit"] is True and state["canApprove"] is False
    assert state["collaboration"]["permissions"]["role"] == "co_mentor"

    # 负责导师仍看到批准按钮。
    _login(plan_client, m1db.alice_id, "advisor", "Alice")
    primary = plan_client.get("/m1/plans/%d" % plan["id"]).get_data(as_text=True)
    assert 'id="approveBtn"' in primary
    assert _APPROVE_HINT not in primary


def test_parent_page_family_acknowledgement_and_co_mentor_hints(plan_client, m1db):
    plan = _with_parent(m1db)
    collab.add_team_member(m1db.student_id, m1db.bob_id, _admin(m1db))

    _login(plan_client, m1db.bob_id, "advisor", "Bob")
    html = plan_client.get("/m1/plans/%d" % plan["id"]).get_data(as_text=True)
    assert _PARENT_HINT in html
    assert 'id="parentConfirmBtn"' not in html
    assert 'id="parentExportBtn"' not in html
    assert 'data-family-seen="0"' in html
    assert "AI 新写" in html

    state = _page_state(html)
    family = state["parent"]["family"]
    assert len(family) == 2
    assert all(row["hash"] and row["seen"] is False for row in family)
    assert state["parent"]["editable"] is True


def test_client_parent_patch_shapes_pass_server_validation(plan_client, m1db):
    """UI 生成的整列表 patch 必须保留 ref 与 {text,src} 字段，否则会被校验拒绝。"""
    plan = _with_parent(m1db, _parent_doc(seen=(True, True)))
    alice = _client_for(plan_client, m1db.alice_id, "advisor", "Alice")
    doc = pstore.current_version(plan["id"], "parent")["doc"]

    lease = _acquire(alice, plan["id"], "parent.practice_options").get_json()
    options = copy.deepcopy(doc["practice_options"])
    options[0]["title"] = {"text": "新的练习名称", "src": "edited"}
    saved = _patch(alice, plan["id"], "parent.practice_options", options, lease)
    assert saved.status_code == 200, saved.get_json()
    stored = pstore.current_version(plan["id"], "parent")["doc"]["practice_options"]
    assert stored[0]["title"]["text"] == "新的练习名称"
    assert stored[1]["title"]["src"] == "ai"
    assert [row["ref"] for row in stored] == [row["ref"] for row in options]

    lease = _acquire(alice, plan["id"], "parent.family").get_json()
    family = _patch(alice, plan["id"], "parent.family",
                    [{"text": "新的家庭建议一", "src": "edited"},
                     {"text": "家庭建议二。", "src": "ai"}], lease)
    assert family.status_code == 200, family.get_json()
    parent_doc = pstore.current_version(plan["id"], "parent")["doc"]
    assert parent_doc["family_seen"] == [False, True]
    assert parent_doc["family"][1]["src"] == "ai"

    lease = _acquire(alice, plan["id"], "parent.review").get_json()
    reviews = [{"label": {"text": "观察一", "src": "ai"},
                "text": {"text": "新的观察记录", "src": "edited"}},
               {"label": {"text": "观察二", "src": "ai"},
                "text": {"text": "观察说明二。", "src": "ai"}}]
    reviewed = _patch(alice, plan["id"], "parent.review", reviews, lease)
    assert reviewed.status_code == 200, reviewed.get_json()
    assert pstore.current_version(plan["id"], "parent")["doc"]["review"][
        0]["text"]["text"] == "新的观察记录"


def test_student_hub_and_lists_surface_team(plan_client, m1db):
    plan, _doc = _new_plan_with_version(m1db)
    collab.add_team_member(m1db.student_id, m1db.bob_id, _admin(m1db))

    _login(plan_client, m1db.admin_id, "admin")
    html = plan_client.get("/m1/students/%d" % m1db.student_id).get_data(as_text=True)
    for marker in ('id="m1HubTeam"', "m1_student_hub.js", "导师团队"):
        assert marker in html

    overview = plan_client.get("/api/m1/students/%d/overview"
                               % m1db.student_id).get_json()
    assert overview["can_manage_team"] is True
    assert [row["user_id"] for row in overview["team"]["co_mentors"]] == [m1db.bob_id]

    plans = plan_client.get("/api/m1/plans").get_json()["plans"]
    row = next(item for item in plans if item["id"] == plan["id"])
    assert [item["user_id"] for item in row["team"]["co_mentors"]] == [m1db.bob_id]
    assert [item["user_id"] for item in row["team"]["primaries"]] == [m1db.alice_id]

    hub_js = (ROOT / "static/m1/m1_student_hub.js").read_text(encoding="utf-8")
    for marker in ("共同导师", "负责导师", "/team", "window.confirm", "renderTeam"):
        assert marker in hub_js
    lists_js = (ROOT / "static/m1/m1_lists.js").read_text(encoding="utf-8")
    assert "共同导师" in lists_js


def test_editor_source_uses_section_patches_leases_and_conflict_view():
    plan_js = (ROOT / "static/m1/plan.js").read_text(encoding="utf-8")
    for marker in ("/sections/", "idempotency_key", "document_version",
                   "expected_version", "lease_token", "/leases/acquire",
                   "/leases/renew", "/leases/release", "/presence",
                   "stale_section", "stale_document", "lease_conflict",
                   "stale_family_ack", "data-family-seen",
                   "保留我的文字并重新应用", "改用当前版本",
                   "载入最新内容", "navigator.onLine", "pagehide",
                   "visibilitychange"):
        assert marker in plan_js, marker

    # 新编辑器不允许再用整份文档 PUT 覆盖其他人的分段修改。
    assert "request('PUT'" not in plan_js
    assert "API + '/internal'" not in plan_js
    assert "API + '/parent'" not in plan_js.replace("API + '/parent/", "")
    # 取得租约时不能静默采纳服务器的新 section 版本，否则本地旧正文会绕过冲突。
    assert "S.sections[section] = data.version" not in plan_js

    core_js = (ROOT / "static/m1/plan_collab_core.js").read_text(encoding="utf-8")
    for marker in ("internal.session.", "parent.family", "parent.family_seen",
                   "dependencyParent", "sectionLabel", "conflictPreview"):
        assert marker in core_js, marker


@pytest.mark.skipif(shutil.which("node") is None, reason="node 未安装")
def test_collab_core_pure_mappings_build_contract_patches():
    script = r"""
const path = require('path');
const core = require(path.join(process.cwd(), 'static/m1/plan_collab_core.js'));
function assert(ok, message) { if (!ok) { console.error(message); process.exit(1); } }

const field = function (text) { return {text: text, src: 'ai'}; };
const doc = {
  overview: field('概览'), mentor_notes: field('备注'),
  sessions: [1, 2, 3].map(function (n) {
    return {
      title: field('第 ' + n + ' 课'),
      review: [field('回顾一'), field('回顾二')],
      focus: {primary: 'R2.2', supporting: null, text: field('重点')},
      content: {mindsets: field('心态'), skills: field('技能'), techniques: field('技巧')},
      activities: [{id: 's' + n + 'a1', name: field('活动'), minutes: 15,
                    steps: field('步骤'), questions: field('问题'),
                    materials: field('材料'), source: {type: 'ai_original'}}],
      practice: [{id: 's' + n + 'p1', code: 'R2.2', name: field('练习'),
                  task: field('任务'), frequency: field('每天'),
                  platform: 'StoryMap', evidence: field('证据')}],
      evidence: field('表现'), next_prep: n === 3 ? null : field('下次准备')
    };
  })
};
const parent = {
  intro: field('开场'), transition: field('过渡'),
  goals: [{code: 'R2.2', text: field('目标说明')}],
  sessions: [1, 2, 3].map(function (n) {
    return {n: n, title: field('第 ' + n + ' 课'), summary: field('摘要')};
  }),
  practice_options: [0, 1, 2].map(function (i) {
    return {ref: 's1p' + (i + 1), title: field('练习 ' + i), text: field('说明 ' + i),
            frequency: field('每天'), platform: 'StoryMap'};
  }),
  family: [field('建议一'), field('建议二')],
  review: [{label: field('观察一'), text: field('记录一')}]
};

assert(core.internalSection(doc, 'overview').section === 'internal.overview', 'overview');
assert(core.internalSection(doc, 'mentor_notes').field === 'mentor_notes', 'notes');
assert(core.internalSection(doc, 'sessions.0.title').section === 'internal.session.1', 'session');
const activity = core.internalSection(doc, 'sessions.0.activities.0.steps');
assert(activity.section === 'internal.session.1.activity.s1a1' && activity.field === 'steps',
  'activity stable id');
assert(core.internalSection(doc, 'sessions.1.practice.0.task').section ===
  'internal.session.2.practice.s2p1', 'practice stable id');
assert(core.internalSection(doc, 'sessions.0.activities.5.name') === null,
  'missing activity must not fall back to an index');
assert(core.internalSection(doc, 'unknown.0') === null, 'unknown internal path');

// plan.js 先写入本地文档再构造最小 patch；这里按同样顺序验证。
doc.sessions[0].activities[0].minutes = 20;
const minutes = core.internalPatch(doc, 'sessions.0.activities.0.minutes', '20');
assert(minutes.section === 'internal.session.1.activity.s1a1' && minutes.patch.minutes === 20,
  'minutes numeric patch');
const sourceValue = {type: 'world_bank', wb_id: 'R2.2'};
doc.sessions[0].activities[0].source = sourceValue;
const source = core.internalPatch(doc, 'sessions.0.activities.0.source', sourceValue);
assert(source.patch.source.type === 'world_bank' && source.patch.source.wb_id === 'R2.2',
  'source keeps contract shape');
const review = core.internalPatch(doc, 'sessions.1.review', '不该覆盖');
assert(review.patch.review.length === 2 && review.patch.review[0].text === '回顾一',
  'review is a whole-list field patch');
const titlePatch = core.internalPatch(doc, 'sessions.0.title.text', '新标题');
assert(titlePatch.section === 'internal.session.1' && titlePatch.patch.title.text === '新标题',
  'session title patch');
const evidence = core.internalPatch(doc, 'sessions.1.evidence.text', '新表现');
assert(evidence.patch.evidence.text === '新表现', 'session evidence patch');
doc.sessions[1].next_prep = null;
const nextPrep = core.internalPatch(doc, 'sessions.1.next_prep.text', '新准备');
assert(nextPrep.patch.next_prep.text === '新准备', 'session next_prep patch from null');
const focus = core.internalPatch(doc, 'sessions.0.focus.text', '新重点');
assert(focus.patch.focus.text.text === '新重点' && focus.patch.focus.text.src === 'edited',
  'focus text patch');
const skills = core.internalPatch(doc, 'sessions.0.content.skills', '新技能');
assert(skills.patch.content.skills.text === '新技能', 'content patch');
doc.sessions[0].practice[0].platform = 'NewPlatform';
const practice = core.internalPatch(doc, 'sessions.0.practice.0.platform', 'NewPlatform');
assert(practice.patch.platform === 'NewPlatform', 'platform is a plain value patch');

assert(core.parentSection(parent, 'intro').section === 'parent.intro', 'parent intro');
assert(core.parentSection(parent, 'goals.0.text').section === 'parent.goal.R2.2', 'parent goal code');
assert(core.parentSection(parent, 'sessions.1.summary').section === 'parent.session.2', 'parent session');
assert(core.parentSection(parent, 'family.0') .section === 'parent.family', 'parent family');

const family = core.parentPatch(parent, 'family.1', '新建议');
assert(family.patch.length === 2 && family.patch[1].text === '新建议' &&
  family.patch[0].text === '建议一' && family.patch[0].src === 'ai',
  'family keeps the untouched sibling field and src');
const options = core.parentPatch(parent, 'practice_options.0.title', '新标题');
assert(options.patch.length === 3 && options.patch[0].title.text === '新标题' &&
  options.patch[0].ref === 's1p1' && options.patch[0].frequency.text === '每天' &&
  options.patch[0].platform === 'StoryMap' &&
  options.patch[1].title.text === '练习 1', 'practice options keep refs and field shape');
const goal = core.parentPatch(parent, 'goals.0.text', '新目标');
assert(goal.section === 'parent.goal.R2.2' && goal.patch.text.text === '新目标', 'goal text');
const pv = core.parentPatch(parent, 'review.0.text', '新记录');
assert(pv.section === 'parent.review' && pv.patch[0].text.text === '新记录' &&
  pv.patch[0].label.text === '观察一', 'review array keeps field shape');

assert(core.dependencyParent('internal.session.2.activity.s2a1') ===
  'internal.session.2.activities', 'activity dependency');
assert(core.dependencyParent('internal.session.2.practice.s2p1') ===
  'internal.session.2.practice', 'practice dependency');
assert(core.dependencyParent('internal.session.2') === null, 'session has no list dependency');
assert(core.sectionLabel('internal.session.1') === '第 1 节', 'session label');
assert(core.sectionLabel('internal.session.1.activity.s1a1') === '第 1 节 · 教学活动', 'activity label');
assert(core.sectionLabel('internal.session.1.activities') === '第 1 节 · 活动列表', 'list label');
assert(core.sectionLabel('parent.family') === '家长版 · 家庭建议', 'family label');
assert(core.conflictPreview(['一', '二'], 10) === '一 / 二', 'conflict preview joins lists');
assert(core.conflictPreview('  很长的文字  ', 20) === '很长的文字', 'conflict preview trims');
// stale_section 返回整节 current；冲突卡片必须按本地 patch 裁剪，不能展示活动 JSON。
const serverSession = {n: 1, title: field('服务器标题'),
  activities: [{id: 's1a1', name: field('服务器活动'), steps: field('步骤')}]};
assert(core.conflictPreview(titlePatch.patch) === '新标题', 'local title preview');
assert(core.conflictCurrent(titlePatch.patch, serverSession) === '服务器标题',
  'current preview is scoped to the patched field');
assert(core.conflictCurrent([doc.sessions[0].activities[0]], serverSession.activities) ===
  '服务器活动', 'list replacement preview shows server item labels');
assert(core.conflictPreview({platform: 'NewPlatform'}) === 'NewPlatform', 'plain value preview');
assert(core.get(doc, 'sessions.0.title.text') === '第 1 课', 'get helper');
core.set(doc, 'sessions.0.title.text', '改过');
assert(doc.sessions[0].title.text === '改过', 'set helper');
process.stdout.write('DP13 collab core mappings passed\n');
"""
    subprocess.run(["node", "-e", script], cwd=str(ROOT), check=True,
                   capture_output=True, text=True)
