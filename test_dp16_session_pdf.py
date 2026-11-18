"""DP16-B：单节内部教案导出（浏览器打印 / 另存为 PDF）。

覆盖选择投影、权限、前置条件、只读性、客户端保存屏障，以及真实 Chrome
打印的分页结果。整份 Block 打印仍由既有测试覆盖。
"""
from __future__ import annotations

import html as html_lib
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

import m1.plan_collaboration as collab
import m1.plan_kb as plan_kb
import m1.plan_store as pstore
from blueprints import m1_plan as plan_bp
from db import Student
from test_dp12_ui import _direct_plan
from test_m1_pipeline import _login
from test_m1dp_api import plan_client  # noqa: F401  pytest fixture
from test_m1dp_store import _create, _goal, _published_prep
from test_m1_store import m1db  # noqa: F401  pytest fixture

ROOT = Path(__file__).resolve().parent


# ---------------------------------------------------------------------------
# fixtures / helpers
# ---------------------------------------------------------------------------
def _field(text):
    return {"text": text, "src": "ai"}


def _rich_doc(*, primary="R2.2", supporting=None, legacy=False, long=False,
              paragraphs=False):
    long_text = ""
    if long:
        long_text = "LONG-A1-START\n" + ("这是用于验证长教案自然分页的完整教学步骤，不应被裁切或缩小。" * 120) + "\nLONG-A1-END"
    sessions = []
    for n in (1, 2, 3):
        activities = []
        if long and n == 1:
            activities.append({
                "id": "s1-long", "name": _field("LONG-A1"), "minutes": 30,
                "steps": _field(long_text), "questions": _field("LONG-Q1"),
                "materials": _field("LONG-M1"),
                "source": {"type": "other", "text": "LONG-CITE"},
            })
        else:
            activities.append({
                "id": "s%d-a1" % n, "name": _field("S%d-A1" % n), "minutes": 12,
                "steps": _field("S%d-A1-STEP" % n), "questions": _field("S%d-A1-Q" % n),
                "materials": _field("S%d-A1-M" % n),
                "source": {"type": "other", "text": "S%d-A1-CITE" % n},
                "purpose": _field("S%d-A1-PURPOSE" % n),
                "personalization": _field("S%d-A1-PERSONAL" % n),
                "student_action": _field("S%d-A1-ACTION" % n),
                "expected_attempt": _field("S%d-A1-ATTEMPT" % n),
                "support": _field("S%d-A1-SUPPORT" % n),
                "extension": _field("S%d-A1-EXTENSION" % n),
            })
        if legacy and n == 2:
            activities.append({
                "id": "s2-legacy", "name": _field("S2-LEGACY"),
                "minutes": 5, "steps": _field("S2-LEGACY-STEP"),
            })
        else:
            activities.append({
                "id": "s%d-a2" % n, "name": _field("S%d-A2" % n), "minutes": 8,
                "steps": _field("S%d-A2-STEP" % n), "questions": _field("S%d-A2-Q" % n),
                "materials": _field("S%d-A2-M" % n),
                "source": {"type": "ai_original"},
            })
        if n == 3:
            activities.append({
                "id": "s3-block-review", "name": _field("S3-BR"),
                "minutes": 8, "block_review": True,
                "questions": _field("S3-BR-QUESTION"),
            })
        review = (["S%d-LEGACY-REVIEW" % n]) if (legacy and n == 2) else (
            [] if n == 1 else [_field("S%d-REVIEW" % n)])
        sessions.append({
            "n": n,
            "title": _field("S%d-TITLE" % n),
            "review": review,
            "focus": {
                "primary": primary,
                "supporting": supporting if n == 3 else None,
                "text": _field("S%d-FOCUS" % n),
            },
            "content": {
                "mindsets": _field("S%d-MINDSETS" % n),
                "path": _field("S%d-PATH" % n),
                "skills": _field("S%d-SKILLS" % n),
                "techniques": _field("S%d-TECHNIQUES" % n),
            },
            "activities": activities,
            "evidence": _field("S%d-EVIDENCE" % n),
            "practice": [{
                "id": "s%d-p1" % n, "name": _field("S%d-PRACTICE" % n),
                "code": primary, "task": _field("S%d-PRACTICE-TASK" % n),
                "frequency": _field("每天"), "platform": "StoryMap",
                "evidence": _field("S%d-PRACTICE-EVIDENCE" % n),
            }],
            "next_prep": _field("LONG-FINAL-END" if (long and n == 1) else ("S%d-NEXT-END" % n)),
        })
    if paragraphs:
        first = sessions[0]
        first["activities"][0]["questions"] = _field("QUESTION_LINE_A\n\nQUESTION_LINE_B")
        first["activities"][0]["materials"] = _field("MATERIAL_LINE_A\nMATERIAL_LINE_B")
        first["activities"][0]["purpose"] = _field("PURPOSE_LINE_A\n\nPURPOSE_LINE_B")
        first["activities"][0]["support"] = _field("SUPPORT_LINE_A\n\nSUPPORT_LINE_B")
        first["content"]["mindsets"] = _field("MINDSETS_LINE_A\n\nMINDSETS_LINE_B")
        first["evidence"] = _field("EVIDENCE_LINE_A\n\nEVIDENCE_LINE_B")
        sessions[2]["activities"][-1]["questions"] = _field(
            "BR_QUESTION_LINE_A\n\nBR_QUESTION_LINE_B")
    return {
        "overview": _field("OVERVIEW-PRIVATE"),
        "mentor_notes": _field("MENTOR-PRIVATE"),
        "sessions": sessions,
    }


def _set_student_grade(db, grade):
    with Session(db.engine) as sess:
        row = sess.get(Student, db.student_id)
        row.grade = grade
        sess.commit()


def _make_plan(db, *, client=None, source_mode="report", doc=None,
               checks=None, approve=False, goals=None, grade=None, block_no=1):
    if grade is not None:
        _set_student_grade(db, grade)
    if source_mode == "report":
        prep, report = _published_prep(db)
        plan = _create(db, prep, report, block_no=block_no)
    else:
        assert client is not None
        plan = _direct_plan(client, db, block_no=block_no)
    plan = pstore.save_goals(plan["id"], plan["rev"], goals or [_goal()])
    version = pstore.add_version(
        plan["id"], part="internal", kind="ai_draft",
        ai_doc=doc, doc=doc, checks=checks or [])
    pstore.finish_generation(plan["id"], "internal", version_id=version["id"])
    plan = pstore.get_plan(plan["id"])
    if approve:
        pstore.approve(plan["id"], db.alice_id)
        plan = pstore.get_plan(plan["id"])
    return plan, version


def _admin(db):
    return {"user_id": db.admin_id, "role": "admin",
            "advisor_name": "", "display_name": "Admin"}


def _plan_html(client, plan_id):
    res = client.get("/m1/plans/%d" % plan_id)
    assert res.status_code == 200, res.get_data(as_text=True)
    return res.get_data(as_text=True)


def _page_state(html):
    match = re.search(r"window\.M1_PLAN = (\{.*?\});</script>", html, re.S)
    assert match, "plan page state missing"
    return json.loads(match.group(1))


def _print_url(plan, session_no=1, **params):
    url = "/m1/plans/%d/sessions/%d/print" % (plan["id"], session_no)
    if params:
        query = "&".join("%s=%s" % (key, value) for key, value in params.items())
        return url + "?" + query
    return url


def _session_html(client, plan, session_no, **params):
    res = client.get(_print_url(plan, session_no, **params))
    assert res.status_code == 200, res.get_data(as_text=True)
    return res.get_data(as_text=True)


def _db_plan_state(db, plan_id):
    from m1.plan_collaboration import PlanCollabState
    with Session(db.engine) as sess:
        plan = sess.get(pstore.M1Plan, int(plan_id))
        collab_state = sess.get(PlanCollabState, int(plan_id))
        versions = (sess.query(pstore.M1PlanVersion)
                    .filter(pstore.M1PlanVersion.plan_id == int(plan_id)).count())
        return {
            "status": plan.status, "parent_status": plan.parent_status,
            "rev": plan.rev, "current_version_id": plan.current_version_id,
            "parent_version_id": plan.parent_version_id,
            "approved_by": plan.approved_by, "approved_at": plan.approved_at,
            "parent_exported_at": plan.parent_exported_at,
            "versions": versions,
            "document_version": getattr(collab_state, "document_version", None),
        }


# ---------------------------------------------------------------------------
# selection / content projection
# ---------------------------------------------------------------------------
def test_selection_one_two_three_are_unique_and_do_not_leak(plan_client, m1db):
    plan, _version = _make_plan(m1db, doc=_rich_doc(legacy=True),
                                checks=[{"level": "review", "text": "CHECK-PRIVATE"}])
    with Session(m1db.engine) as sess:
        row = sess.get(pstore.M1Plan, plan["id"])
        inputs = json.loads(row.inputs or "{}")
        inputs["provenance_id"] = "INPUT-ID-PRIVATE"
        row.inputs = json.dumps(inputs, ensure_ascii=False)
        sess.commit()

    _login(plan_client, m1db.alice_id, "advisor", "Alice")
    pages = {}
    for n in (1, 2, 3):
        body = _session_html(plan_client, plan, n)
        pages[n] = body
        assert ("Session %d" % n) in body
        assert ("S%d-TITLE" % n) in body
        assert ("S%d-A1-STEP" % n) in body
        assert body.count("S%d-A1-STEP" % n) == 1
        for other in {1, 2, 3} - {n}:
            assert ("S%d-TITLE" % other) not in body
            assert ("S%d-A1-STEP" % other) not in body
        for marker in ("OVERVIEW-PRIVATE", "MENTOR-PRIVATE", "CHECK-PRIVATE",
                       "INPUT-ID-PRIVATE"):
            assert marker not in body

    assert "S2-LEGACY-STEP" in pages[2]
    assert "S2-LEGACY-REVIEW" in pages[2]
    assert "S2-LEGACY-STEP" not in pages[1]

    kb_review = plan_kb.block_review()
    kb_name = html_lib.escape(kb_review["name"])
    assert kb_name not in pages[1]
    assert kb_name not in pages[2]
    assert pages[3].count(kb_name) == 1
    for part in kb_review["parts"]:
        assert html_lib.escape(part["label"]) in pages[3]
        assert html_lib.escape(part["text"]) in pages[3]
    assert html_lib.escape(kb_review["note"]) in pages[3]
    assert "S3-BR-QUESTION" in pages[3]

    # 固定 Block Review 仍在原来的最后活动位置。
    assert pages[3].index("S3-A1-STEP") < pages[3].index(kb_name)
    assert pages[3].index(kb_name) < pages[3].index("S3-EVIDENCE")

    for marker in ("S1-A1-PURPOSE", "S1-A1-PERSONAL", "S1-A1-ACTION",
                   "S1-A1-ATTEMPT", "S1-A1-SUPPORT", "S1-A1-EXTENSION"):
        assert marker in pages[1]
    assert "S1-A1-CITE" in pages[1]
    assert "参考来源" in pages[1]


def test_full_block_print_still_contains_all_three_sessions(plan_client, m1db):
    plan, _version = _make_plan(m1db, doc=_rich_doc())
    _login(plan_client, m1db.alice_id, "advisor", "Alice")
    body = plan_client.get("/m1/plans/%d/print" % plan["id"]).get_data(as_text=True)
    for n in (1, 2, 3):
        assert ("S%d-TITLE" % n) in body
        assert ("S%d-A1-STEP" % n) in body
    assert "OVERVIEW-PRIVATE" in body
    assert html_lib.escape(plan_kb.block_review()["name"]) in body


def test_session_one_and_two_never_inherit_block_review_and_duplicate_is_once(plan_client, m1db):
    doc = _rich_doc()
    doc["sessions"][0]["activities"][0]["block_review"] = True
    doc["sessions"][2]["activities"][0]["block_review"] = True
    plan, _version = _make_plan(m1db, doc=doc)
    _login(plan_client, m1db.alice_id, "advisor", "Alice")
    kb_name = html_lib.escape(plan_kb.block_review()["name"])
    assert kb_name not in _session_html(plan_client, plan, 1)
    assert _session_html(plan_client, plan, 3).count(kb_name) == 1


def test_session_goals_only_referenced_and_legacy_missing_is_honest(plan_client, m1db):
    goals = [_goal("R2.2", text="GOAL-R22-TEXT"),
             _goal("R4.1", text="GOAL-R41-TEXT"),
             _goal("R3.1", text="UNRELATED-GOAL-TEXT")]
    plan, _version = _make_plan(m1db, doc=_rich_doc(primary="R2.2", supporting="R4.1"),
                                goals=goals)
    _login(plan_client, m1db.alice_id, "advisor", "Alice")
    s1 = _session_html(plan_client, plan, 1)
    assert "R2.2" in s1 and "GOAL-R22-TEXT" in s1
    assert "偶尔能说" in s1 and "多数时候能说" in s1
    assert "R4.1" not in s1 and "UNRELATED-GOAL-TEXT" not in s1
    s3 = _session_html(plan_client, plan, 3)
    assert "R2.2" in s3 and "R4.1" in s3
    assert "GOAL-R41-TEXT" in s3
    assert "UNRELATED-GOAL-TEXT" not in s3

    bad_doc = _rich_doc(primary="R9.9")
    bad_plan, bad_version = _make_plan(m1db, doc=bad_doc, block_no=2,
                                       goals=[_goal("R2.2", text="GOAL-R22-TEXT")])
    before = pstore.current_version(bad_plan["id"])["doc"]
    body = _session_html(plan_client, bad_plan, 1)
    assert "未找到已确认目标：R9.9" in body
    assert "GOAL-R22-TEXT" not in body
    assert pstore.current_version(bad_plan["id"])["doc"] == before


# ---------------------------------------------------------------------------
# header metadata / watermark / status
# ---------------------------------------------------------------------------
def test_header_metadata_title_and_optional_grade(plan_client, m1db):
    plan, _version = _make_plan(m1db, doc=_rich_doc(), grade="")
    _login(plan_client, m1db.alice_id, "advisor", "Alice")
    body = _session_html(plan_client, plan, 2)
    assert "<title>林晓雨 · Block 1 · Session 2 · 内部教案</title>" in body
    assert "林晓雨" in body
    assert "<th>年级</th><td>—</td>" in body
    assert "G9" not in body
    assert "Alice" in body
    assert "2026-11-17" in body and "12-15" in body
    assert "本节 60 分钟" in body
    assert "S2-TITLE" in body
    assert "draftmark" in body and "草稿" in body


def test_approved_plan_has_no_draft_watermark_and_uses_current_snapshot(plan_client, m1db):
    plan, _version = _make_plan(m1db, doc=_rich_doc(), approve=True)
    assert plan["status"] == "approved"
    assert plan["parent_status"] in (None, "", "none")
    _login(plan_client, m1db.alice_id, "advisor", "Alice")
    body = _session_html(plan_client, plan, 1)
    assert "draftmark" not in body
    assert "草稿" not in body
    assert "S1-A1-STEP" in body


# ---------------------------------------------------------------------------
# permissions / export entry
# ---------------------------------------------------------------------------
def test_export_entry_visible_to_primary_co_mentor_and_admin(plan_client, m1db):
    plan, _version = _make_plan(m1db, doc=_rich_doc())
    collab.add_team_member(m1db.student_id, m1db.bob_id, _admin(m1db))

    for user_id, role, name in ((m1db.alice_id, "advisor", "Alice"),
                                (m1db.bob_id, "advisor", "Bob"),
                                (m1db.admin_id, "admin", "")):
        _login(plan_client, user_id, role, name)
        page = _plan_html(plan_client, plan["id"])
        assert page.count('class="btn s g sess-export"') == 3
        assert 'data-session="1"' in page
        if user_id == m1db.bob_id:
            assert _page_state(page)["canApprove"] is False
        res = plan_client.get(_print_url(plan, 1))
        assert res.status_code == 200

    pstore.approve(plan["id"], m1db.alice_id)
    for user_id, role, name in ((m1db.alice_id, "advisor", "Alice"),
                                (m1db.bob_id, "advisor", "Bob"),
                                (m1db.admin_id, "admin", "")):
        _login(plan_client, user_id, role, name)
        page = _plan_html(plan_client, plan["id"])
        assert page.count('class="btn s g sess-export"') == 3


def test_removal_takes_effect_and_unrelated_viewer_m1_disabled_denied(
        plan_client, m1db, monkeypatch):
    plan, _version = _make_plan(m1db, doc=_rich_doc())
    collab.add_team_member(m1db.student_id, m1db.bob_id, _admin(m1db))
    _login(plan_client, m1db.bob_id, "advisor", "Bob")
    assert plan_client.get(_print_url(plan, 1)).status_code == 200

    collab.remove_team_member(m1db.student_id, m1db.bob_id, _admin(m1db))
    assert plan_client.get(_print_url(plan, 1)).status_code == 404
    assert plan_client.get("/m1/plans/%d" % plan["id"]).status_code == 404

    _login(plan_client, m1db.viewer_id, "viewer")
    assert plan_client.get(_print_url(plan, 1)).status_code in (403, 404)

    _login(plan_client, m1db.alice_id, "advisor", "Alice")
    import app_utils
    monkeypatch.setattr(app_utils, "can_use_m1", lambda: False)
    assert plan_client.get(_print_url(plan, 1)).status_code == 403


def test_generating_button_disabled_with_message_and_print_409(plan_client, m1db):
    plan, _version = _make_plan(m1db, doc=_rich_doc())
    _login(plan_client, m1db.alice_id, "advisor", "Alice")
    pstore.begin_generation(plan["id"], "internal")
    page = _plan_html(plan_client, plan["id"])
    assert page.count('class="btn s g sess-export"') == 3
    assert page.count("disabled") >= 3
    assert "内部版正在更新，完成后可导出本节 PDF" in page
    res = plan_client.get(_print_url(plan, 1))
    assert res.status_code == 409
    assert "内部版正在更新" in res.get_data(as_text=True)


def test_plan_without_internal_version_has_no_export(plan_client, m1db):
    prep, report = _published_prep(m1db)
    plan = _create(m1db, prep, report)
    plan = pstore.save_goals(plan["id"], plan["rev"], [_goal()])
    _login(plan_client, m1db.alice_id, "advisor", "Alice")
    page = _plan_html(plan_client, plan["id"])
    assert "sess-export" not in page
    assert plan_client.get(_print_url(plan, 1)).status_code == 404


# ---------------------------------------------------------------------------
# route contract / preconditions / read-only
# ---------------------------------------------------------------------------
def test_selection_and_precondition_contract(plan_client, m1db):
    plan, version = _make_plan(m1db, doc=_rich_doc())
    _login(plan_client, m1db.alice_id, "advisor", "Alice")

    assert plan_client.get("/m1/plans/%d/sessions/0/print" % plan["id"]).status_code == 404
    assert plan_client.get("/m1/plans/%d/sessions/4/print" % plan["id"]).status_code == 404
    assert plan_client.get("/m1/plans/%d/sessions/x/print" % plan["id"]).status_code == 404

    ok = plan_client.get(_print_url(plan, 1, expected_rev=plan["rev"],
                                    version_id=version["id"]))
    assert ok.status_code == 200
    assert plan_client.get(_print_url(plan, 1)).status_code == 200

    stale_rev = plan_client.get(_print_url(plan, 1, expected_rev=plan["rev"] + 1,
                                           version_id=version["id"]))
    assert stale_rev.status_code == 409
    assert "计划已有更新" in stale_rev.get_data(as_text=True)

    stale_version = plan_client.get(_print_url(plan, 1, expected_rev=plan["rev"],
                                               version_id=version["id"] + 1))
    assert stale_version.status_code == 409

    parent = pstore.add_version(plan["id"], part="parent", kind="ai_draft",
                                ai_doc={"sessions": []}, doc={"sessions": []},
                                checks=[], source_version_id=version["id"])
    assert plan_client.get(_print_url(
        plan, 1, expected_rev=pstore.get_plan(plan["id"])["rev"],
        version_id=parent["id"])).status_code == 409

    other_plan, other_version = _make_plan(m1db, doc=_rich_doc(), block_no=2)
    assert plan_client.get(_print_url(
        plan, 1, expected_rev=plan["rev"], version_id=other_version["id"])).status_code == 409

    assert plan_client.get(_print_url(plan, 1, expected_rev=plan["rev"])).status_code == 400
    assert plan_client.get(_print_url(plan, 1, version_id=version["id"])).status_code == 400
    assert plan_client.get(_print_url(
        plan, 1, expected_rev="abc", version_id=version["id"])).status_code == 400

    # 版本 ID 不变、文档就地更新的竞态必须由修订号兜住。
    with Session(m1db.engine) as sess:
        row = sess.get(pstore.M1PlanVersion, version["id"])
        doc = json.loads(row.doc)
        doc["sessions"][0]["title"] = _field("S1-RACE")
        row.doc = json.dumps(doc, ensure_ascii=False)
        plan_row = sess.get(pstore.M1Plan, plan["id"])
        plan_row.rev += 1
        sess.commit()
    race = plan_client.get(_print_url(plan, 1, expected_rev=plan["rev"],
                                      version_id=version["id"]))
    assert race.status_code == 409
    assert "计划已有更新" in race.get_data(as_text=True)


def test_print_uses_one_snapshot_and_writes_nothing(plan_client, m1db, monkeypatch):
    plan, version = _make_plan(m1db, doc=_rich_doc())
    _login(plan_client, m1db.alice_id, "advisor", "Alice")
    before = _db_plan_state(m1db, plan["id"])

    called = []
    real_snapshot = pstore.internal_print_snapshot

    def spy(plan_id):
        called.append(plan_id)
        return real_snapshot(plan_id)

    monkeypatch.setattr(pstore, "internal_print_snapshot", spy)
    monkeypatch.setattr(plan_bp, "_plan_page_context", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("selected print must not use multi-read page context")))

    body = _session_html(plan_client, plan, 2)
    assert called == [plan["id"]]
    assert "S2-A1-STEP" in body
    after = _db_plan_state(m1db, plan["id"])
    assert after == before


def test_direct_source_mode_selected_print(plan_client, m1db):
    plan, _version = _make_plan(
        m1db, client=plan_client, source_mode="mentor_inputs", doc=_rich_doc())
    _login(plan_client, m1db.alice_id, "advisor", "Alice")
    body = _session_html(plan_client, plan, 1)
    assert "S1-A1-STEP" in body
    assert "S2-A1-STEP" not in body


# ---------------------------------------------------------------------------
# real client behaviour
# ---------------------------------------------------------------------------
JS_HARNESS = r"""
const fs = require('fs');
const path = require('path');
const src = fs.readFileSync(path.join(process.cwd(), 'static/m1/plan.js'), 'utf8');

function slice(name) {
  const start = src.indexOf('function ' + name + '(');
  if (start < 0) throw new Error('missing function ' + name);
  let i = src.indexOf('{', start), depth = 0, quote = null, comment = null;
  for (; i < src.length; i += 1) {
    const ch = src[i], next = src[i + 1];
    if (comment === 'line') { if (ch === '\n') comment = null; continue; }
    if (comment === 'block') { if (ch === '*' && next === '/') { comment = null; i += 1; } continue; }
    if (quote) {
      if (ch === '\\') { i += 1; continue; }
      if (ch === quote) quote = null;
      continue;
    }
    if (ch === '/' && next === '/') { comment = 'line'; i += 1; continue; }
    if (ch === '/' && next === '*') { comment = 'block'; i += 1; continue; }
    if (ch === "'" || ch === '"' || ch === '`') { quote = ch; continue; }
    if (ch === '{') depth += 1;
    else if (ch === '}') { depth -= 1; if (depth === 0) return src.slice(start, i + 1); }
  }
  throw new Error('unterminated function ' + name);
}

const names = ['sessionPrintUrl', 'sessionExportBlockedReason', 'runSessionExport'];
const body = names.map(slice).join('\n');
const exportsObj = new Function(body + '\nreturn {sessionPrintUrl: sessionPrintUrl, '
  + 'sessionExportBlockedReason: sessionExportBlockedReason, runSessionExport: runSessionExport};')();

function assert(ok, message) {
  if (!ok) { console.error('FAIL: ' + message); process.exit(1); }
}

function harness(overrides) {
  const log = [];
  const toasts = [];
  const tab = {
    location: { replace: function (url) { log.push('nav:' + url); } },
    close: function () { log.push('close'); }
  };
  const state = Object.assign({
    rev: 4, versionId: 9, status: 'review', offline: false, revoked: false,
    docText: 'UNSAVED-TEXT'
  }, overrides && overrides.state);
  const opts = Object.assign({
    state: state, planId: 7, online: true,
    openTab: function () { log.push('open'); return tab; },
    flushDirect: function () { log.push('direct'); return Promise.resolve(); },
    flushAll: function () { log.push('all'); return Promise.resolve(true); },
    toast: function (message) { toasts.push(message); },
    navigate: function (url) { log.push('nav:' + url); }
  }, overrides && overrides.opts);
  return {state: state, opts: opts, log: log, toasts: toasts, tab: tab};
}

async function main() {
  // 1) 点击时先开空白页，等待 direct + section 保存确认后才导航。
  let release;
  const gate = new Promise(function (resolve) { release = resolve; });
  const h1 = harness({
    opts: {
      flushDirect: function () { h1.log.push('direct'); return gate; },
      flushAll: function () { h1.log.push('all'); return Promise.resolve(true); }
    }
  });
  const p = exportsObj.runSessionExport(1, h1.opts);
  assert(h1.log[0] === 'open', 'loading tab opens synchronously');
  await Promise.resolve();
  assert(h1.log.indexOf('direct') >= 0 && h1.log.indexOf('all') < 0,
    'flushDirect runs before flushAll');
  assert(h1.log.filter(function (x) { return x.indexOf('nav:') === 0; }).length === 0,
    'no navigation before acknowledgement');
  release();
  assert(await p === true, 'export resolves true');
  assert(h1.log.indexOf('nav:/m1/plans/7/sessions/1/print?expected_rev=4&version_id=9&print=1') >= 0,
    'navigates with acknowledged preconditions');

  // 2) 保存失败：关闭加载页，不导航，保留草稿文本。
  const h2 = harness({opts: {flushDirect: function () {
    h2.log.push('direct'); return Promise.reject(new Error('保存失败'));
  }}});
  assert(await exportsObj.runSessionExport(1, h2.opts) === false, 'failed save returns false');
  assert(h2.log.indexOf('close') >= 0, 'loading tab closed on failure');
  assert(!h2.log.some(function (x) { return x.indexOf('nav:') === 0; }), 'no print on failure');
  assert(h2.state.docText === 'UNSAVED-TEXT', 'drafts retained');
  assert(h2.toasts.join('').indexOf('保存失败') >= 0, 'failure surfaced');

  // 3) 本地未解决冲突：flushAll=false 阻止打印。
  const h3 = harness({opts: {flushAll: function () {
    h3.log.push('all'); return Promise.resolve(false);
  }}});
  assert(await exportsObj.runSessionExport(2, h3.opts) === false, 'conflict blocks');
  assert(h3.log.indexOf('close') >= 0, 'tab closed on conflict');
  assert(!h3.log.some(function (x) { return x.indexOf('nav:') === 0; }), 'no print on conflict');

  // 4) 离线 / 生成中 / 权限撤销：不开标签页、不导航。
  for (const state of [{offline: true}, {status: 'generating'}, {revoked: true}]) {
    const h = harness({state: state});
    assert(await exportsObj.runSessionExport(1, h.opts) === false, 'blocked state');
    assert(h.log.length === 0, 'no tab for blocked state');
    assert(h.toasts.length === 1, 'blocked reason shown');
  }

  // 5) 保存确认后版本推进，URL 使用最近确认值。
  const h5 = harness({opts: {flushAll: function () {
    h5.state.rev = 5; h5.state.versionId = 11; h5.log.push('all');
    return Promise.resolve(true);
  }}});
  assert(await exportsObj.runSessionExport(3, h5.opts) === true, 'advanced revision exports');
  assert(h5.log.indexOf('nav:/m1/plans/7/sessions/3/print?expected_rev=5&version_id=11&print=1') >= 0,
    'uses acknowledged revision/version');

  // 6) 保存后另一标签页开始重新生成：阻止而不是打印旧版。
  const h6 = harness({opts: {flushAll: function () {
    h6.state.status = 'generating'; h6.log.push('all'); return Promise.resolve(true);
  }}});
  assert(await exportsObj.runSessionExport(1, h6.opts) === false, 'late generating blocks');
  assert(h6.log.indexOf('close') >= 0, 'tab closed when generation starts');
  assert(!h6.log.some(function (x) { return x.indexOf('nav:') === 0; }), 'no stale lesson');

  // 7) 非法节次 / 缺失版本不打开打印页。
  const h7 = harness();
  assert(await exportsObj.runSessionExport(4, h7.opts) === false, 'session 4 rejected');
  assert(h7.log.length === 0, 'no tab for invalid session');
  const h8 = harness({state: {versionId: null}});
  assert(await exportsObj.runSessionExport(1, h8.opts) === false, 'missing version rejected');
  assert(h8.log.length === 0, 'no tab without version');

  // 8) 弹窗被拦截时，持久化成功后同页导航。
  const h9 = harness({opts: {
    openTab: function () { h9.log.push('open-blocked'); return null; },
    navigate: function (url) { h9.log.push('nav:' + url); }
  }});
  assert(await exportsObj.runSessionExport(1, h9.opts) === true, 'fallback navigates');
  assert(h9.log.indexOf('nav:/m1/plans/7/sessions/1/print?expected_rev=4&version_id=9&print=1') >= 0,
    'same-tab fallback URL');
}

main().catch(function (err) { console.error(err && err.stack || err); process.exit(1); });
"""


def test_client_export_waits_for_acknowledged_writes_and_blocks_on_failure():
    if shutil.which("node") is None:
        pytest.skip("node not installed")
    result = subprocess.run(
        ["node", "-e", JS_HARNESS], cwd=str(ROOT),
        capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr + result.stdout


# ---------------------------------------------------------------------------
# actual Chrome printing
# ---------------------------------------------------------------------------
def _inline_assets(body: str) -> str:
    css = ((ROOT / "static/m1/m1.css").read_text(encoding="utf-8") + "\n"
           + (ROOT / "static/m1/plan.css").read_text(encoding="utf-8"))
    body = re.sub(r'<link rel="stylesheet" href="[^"]+">\s*', "", body)
    return body.replace("</head>", "<style>%s</style></head>" % css)


def _print_pdf(body: str, out_path: Path):
    playwright = pytest.importorskip("playwright.sync_api")
    page_path = out_path.with_suffix(".html")
    page_path.write_text(_inline_assets(body), encoding="utf-8")
    try:
        with playwright.sync_playwright() as p:
            browser = p.chromium.launch(channel="chrome", headless=True)
            page = browser.new_page(viewport={"width": 1200, "height": 900})
            page.goto(page_path.as_uri(), wait_until="load")
            page.pdf(path=str(out_path), format="A4", print_background=True,
                     prefer_css_page_size=True)
            browser.close()
    except Exception as exc:  # pragma: no cover - environment dependent
        pytest.skip("Chrome printing unavailable: %s" % exc)
    pypdf = pytest.importorskip("pypdf")
    return pypdf.PdfReader(str(out_path))


def _pdf_texts(reader):
    return [page.extract_text() or "" for page in reader.pages]


def _assert_natural_a4(reader, texts, sentinels):
    assert reader.pages
    for page in reader.pages:
        width = float(page.mediabox.width)
        height = float(page.mediabox.height)
        assert abs(width - 595.28) < 3, width
        assert abs(height - 841.89) < 3, height
    assert all(text.strip() for text in texts), "blank page in PDF"
    joined = "\n".join(texts)
    positions = [joined.index(sentinel) for sentinel in sentinels]
    assert positions == sorted(positions), positions
    assert not any(button in joined for button in
                   ("打印 / 另存为 PDF", "正在准备打印预览", "返回计划"))
    for marker in ("OVERVIEW-PRIVATE", "MENTOR-PRIVATE", "CHECK-PRIVATE",
                   "INPUT-ID-PRIVATE", "S2-A1-STEP", "S3-A1-STEP"):
        assert marker not in joined, marker


def test_chrome_prints_typical_selected_session(plan_client, m1db, tmp_path):
    plan, _version = _make_plan(m1db, doc=_rich_doc())
    _login(plan_client, m1db.alice_id, "advisor", "Alice")
    body = _session_html(plan_client, plan, 1)
    reader = _print_pdf(body, tmp_path / "typical-session1.pdf")
    texts = _pdf_texts(reader)
    joined = "\n".join(texts)
    assert "S1-A1-STEP" in joined
    assert "S1-NEXT-END" in joined
    _assert_natural_a4(reader, texts,
                       ["S1-TITLE", "S1-A1-STEP", "S1-EVIDENCE", "S1-NEXT-END"])
    assert len(texts) >= 1


def test_chrome_prints_long_selected_session_without_clipping(plan_client, m1db, tmp_path):
    plan, _version = _make_plan(m1db, doc=_rich_doc(long=True))
    _login(plan_client, m1db.alice_id, "advisor", "Alice")
    body = _session_html(plan_client, plan, 1)
    reader = _print_pdf(body, tmp_path / "long-session1.pdf")
    texts = _pdf_texts(reader)
    joined = "\n".join(texts)
    assert len(texts) >= 3, "long lesson should paginate"
    assert "LONG-A1-START" in joined and "LONG-A1-END" in joined
    assert "LONG-FINAL-END" in texts[-1]
    _assert_natural_a4(reader, texts,
                       ["S1-TITLE", "LONG-A1-START", "LONG-A1-END", "LONG-FINAL-END"])
