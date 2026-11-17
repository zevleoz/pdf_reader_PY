"""DP13-C-b：真实客户端 payload → Flask 分段接口 → 重新读取持久化内容。

这些用例不手写“看起来像客户端”的 patch，而是让 Node 直接执行
``static/m1/plan_collab_core.js`` 的映射函数，再原样提交给真实接口。
"""
from __future__ import annotations

import copy
import json
import subprocess
import uuid
from pathlib import Path

import pytest

from test_dp13_collab import _acquire, _client_for, _patch, _plan
from test_m1_store import m1db  # noqa: F401  pytest fixture
from test_m1dp_api import _new_plan_with_version, plan_client  # noqa: F401
from test_m1dp_pages_parent import _with_parent

ROOT = Path(__file__).resolve().parent
CORE_JS = ROOT / "static" / "m1" / "plan_collab_core.js"

_RUNNER = r"""
const core = require(process.argv[1]);
const input = JSON.parse(require('fs').readFileSync(0, 'utf8'));
function put(node, parts, value) {
  let cursor = node;
  for (let i = 0; i < parts.length - 1; i += 1) cursor = cursor[parts[i]];
  cursor[parts[parts.length - 1]] = value;
}
const doc = input.doc;
if (input.kind === 'parent' && /^family\./.test(input.path)) {
  put(doc, input.path.split('.'), {text: input.value, src: 'edited'});
} else {
  put(doc, input.path.split('.'), input.value);
}
const built = input.kind === 'parent'
  ? core.parentPatch(doc, input.path, input.value)
  : core.internalPatch(doc, input.path, input.value);
if (!built) {
  process.stderr.write('no mapping for ' + input.kind + ' ' + input.path);
  process.exit(2);
}
process.stdout.write(JSON.stringify(built));
"""


def _client_patch(kind: str, doc: dict, path: str, value):
    """像 plan.js 的 stageField 一样先写本地 doc，再由真实 CORE 构造 patch。"""
    payload = {"kind": kind, "doc": copy.deepcopy(doc), "path": path, "value": value}
    proc = subprocess.run(
        ["node", "-e", _RUNNER, str(CORE_JS)],
        input=json.dumps(payload), capture_output=True, text=True, check=False)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _persist(client, plan_id, built, *, tab=None):
    plan = _plan(client, plan_id)
    section = built["section"]
    expected = (plan.get("collaboration", {}).get("sections") or {}).get(section, 0)
    lease = _acquire(client, plan_id, section, tab=tab or uuid.uuid4().hex[:10]).get_json()
    assert lease.get("ok"), lease
    res = _patch(client, plan_id, section, built["patch"], lease,
                 expected=expected, key=uuid.uuid4().hex)
    assert res.status_code == 200, res.get_data(as_text=True)
    return _plan(client, plan_id)


def test_overview_and_mentor_notes_real_endpoint(plan_client, m1db):
    plan, doc = _new_plan_with_version(m1db)
    client = _client_for(plan_client, m1db.alice_id, "advisor", "Alice")
    for path, section, value in (
            ("overview", "internal.overview", "新的整体概览"),
            ("mentor_notes", "internal.mentor_notes", "新的导师备注")):
        built = _client_patch("internal", doc, path, value)
        assert built["section"] == section
        assert set(built["patch"]) == {"text", "src"}
        data = _persist(client, plan["id"], built)
        assert data["internal"]["doc"][path]["text"] == value


def test_internal_session_and_child_payloads(plan_client, m1db):
    plan, doc = _new_plan_with_version(m1db)
    client = _client_for(plan_client, m1db.alice_id, "advisor", "Alice")
    cases = [
        ("sessions.0.title.text", "新的课时标题", lambda d: d["sessions"][0]["title"]["text"]),
        ("sessions.0.evidence.text", "新的表现证据", lambda d: d["sessions"][0]["evidence"]["text"]),
        ("sessions.0.next_prep.text", "新的下次准备", lambda d: d["sessions"][0]["next_prep"]["text"]),
        ("sessions.0.focus.text", "新的教学重点", lambda d: d["sessions"][0]["focus"]["text"]["text"]),
        ("sessions.1.review.0.text", "新的上次回顾", lambda d: d["sessions"][1]["review"][0]["text"]),
        ("sessions.0.activities.0.name.text", "新的活动名",
         lambda d: d["sessions"][0]["activities"][0]["name"]["text"]),
        ("sessions.0.activities.0.steps.text", "新的活动步骤",
         lambda d: d["sessions"][0]["activities"][0]["steps"]["text"]),
        ("sessions.0.activities.0.questions.text", "新的引导问题",
         lambda d: d["sessions"][0]["activities"][0]["questions"]["text"]),
        ("sessions.0.activities.0.materials.text", "新的材料",
         lambda d: d["sessions"][0]["activities"][0]["materials"]["text"]),
        ("sessions.0.activities.0.minutes", 25,
         lambda d: d["sessions"][0]["activities"][0]["minutes"]),
        ("sessions.0.practice.0.name.text", "新的练习名",
         lambda d: d["sessions"][0]["practice"][0]["name"]["text"]),
        ("sessions.0.practice.0.task.text", "新的练习任务",
         lambda d: d["sessions"][0]["practice"][0]["task"]["text"]),
        ("sessions.0.practice.0.frequency.text", "每周三次",
         lambda d: d["sessions"][0]["practice"][0]["frequency"]["text"]),
        ("sessions.0.practice.0.evidence.text", "新的练习证据",
         lambda d: d["sessions"][0]["practice"][0]["evidence"]["text"]),
        ("sessions.0.practice.0.platform", "Echo",
         lambda d: d["sessions"][0]["practice"][0]["platform"]),
        ("sessions.0.content.mindsets.text", "新的心态",
         lambda d: d["sessions"][0]["content"]["mindsets"]["text"]),
        ("sessions.0.content.skills.text", "新的技能",
         lambda d: d["sessions"][0]["content"]["skills"]["text"]),
        ("sessions.0.content.techniques.text", "新的技巧",
         lambda d: d["sessions"][0]["content"]["techniques"]["text"]),
    ]
    current = copy.deepcopy(doc)
    for path, value, read in cases:
        built = _client_patch("internal", current, path, value)
        data = _persist(client, plan["id"], built)
        current = data["internal"]["doc"]
        assert read(current) == value, path


def test_parent_scalar_list_and_child_payloads(plan_client, m1db):
    plan = _with_parent(m1db)
    client = _client_for(plan_client, m1db.alice_id, "advisor", "Alice")
    data = _plan(client, plan["id"])
    current = data["parent"]["doc"]
    cases = [
        ("intro", "新的开场", lambda d: d["intro"]["text"]),
        ("transition", "新的过渡", lambda d: d["transition"]["text"]),
        ("goals.0.text", "新的目标说明", lambda d: d["goals"][0]["text"]["text"]),
        ("sessions.0.title.text", "新的家长版标题", lambda d: d["sessions"][0]["title"]["text"]),
        ("sessions.0.summary.text", "新的家长版摘要", lambda d: d["sessions"][0]["summary"]["text"]),
        ("practice_options.0.title", "新的练习标题",
         lambda d: d["practice_options"][0]["title"]["text"]),
        ("practice_options.0.text", "新的练习说明",
         lambda d: d["practice_options"][0]["text"]["text"]),
        ("practice_options.0.frequency", "每周两次",
         lambda d: d["practice_options"][0]["frequency"]["text"]),
        ("family.0", "新的家庭建议一", lambda d: d["family"][0]["text"]),
        ("family.1", "新的家庭建议二", lambda d: d["family"][1]["text"]),
        ("review.0.text", "新的观察记录", lambda d: d["review"][0]["text"]["text"]),
        ("review.1.label", "新的观察标签", lambda d: d["review"][1]["label"]["text"]),
    ]
    for path, value, read in cases:
        built = _client_patch("parent", current, path, value)
        assert built is not None, path
        if path.startswith(("practice_options", "family", "review")):
            assert isinstance(built["patch"], list), (path, built)
        data = _persist(client, plan["id"], built)
        current = data["parent"]["doc"]
        assert read(current) == value, path


def test_parent_family_seen_uses_displayed_hashes(plan_client, m1db):
    plan = _with_parent(m1db)
    client = _client_for(plan_client, m1db.alice_id, "advisor", "Alice")
    data = _plan(client, plan["id"])
    rows = data["parent_family"]
    assert len(rows) == 2
    hashes = [row["hash"] for row in rows]
    lease = _acquire(client, plan["id"], "parent.family_seen").get_json()
    expected = (data["collaboration"]["sections"] or {}).get("parent.family_seen", 0)
    res = _patch(client, plan["id"], "parent.family_seen",
                 {"seen": [True, True], "hashes": hashes}, lease, expected=expected)
    assert res.status_code == 200, res.get_data(as_text=True)
    after_plan = _plan(client, plan["id"])
    after = after_plan["parent"]["doc"]
    assert after["family_seen"] == [True, True]
    assert [item["hash"] for item in after["family_ack"]] == hashes
    # 旧 hash 再次确认必须被拒绝，而不是只更新 badge。
    expected2 = (after_plan["collaboration"]["sections"] or {}).get(
        "parent.family_seen", 0)
    stale = _patch(client, plan["id"], "parent.family_seen",
                   {"seen": [True, True], "hashes": list(reversed(hashes))},
                   lease, expected=expected2)
    assert stale.status_code == 409 or stale.get_json().get("code") == "stale_family_ack"


def test_direct_header_durations_inputs_goals_personal_brief(plan_client, m1db):
    plan, _doc = _new_plan_with_version(m1db)
    client = _client_for(plan_client, m1db.alice_id, "advisor", "Alice")
    before = _plan(client, plan["id"])

    def send(section, patch):
        data = _plan(client, plan["id"])
        lease = _acquire(client, plan["id"], section).get_json()
        assert lease.get("ok"), lease
        expected = (data.get("collaboration", {}).get("sections") or {}).get(section, 0)
        res = _patch(client, plan["id"], section, patch, lease, expected=expected)
        assert res.status_code == 200, (section, res.get_data(as_text=True))
        return _plan(client, plan["id"])

    data = send("header", {"credits": "12"})
    assert data["plan"]["credits"] == "12"

    data = send("durations", {"session_durations": [45, 45, 60]})
    assert data["plan"]["session_durations"] == [45, 45, 60]

    data = send("inputs", {"strengths": {"text": "新的优势", "src": "edited"}})
    assert data["plan"]["inputs"]["strengths"]["text"] == "新的优势"

    goals = [{"code": "R2.2", "locked": True,
              "goal": {"text": "新的目标", "src": "mentor"},
              "start": {"text": "起点", "src": "ai"},
              "expected": {"text": "终点", "src": "ai"}}]
    # 客户端实际发送的是 {goals: [...]}；数组直发会被契约拒绝。
    data = send("goals", {"goals": goals})
    assert data["plan"]["goals"][0]["goal"]["text"] == "新的目标"

    data = send("personal", {"notes": "导师备注"})
    assert data["personal"]["notes"] == "导师备注"

    brief = {"learning_need": {"text": "学习需求", "provenance": "mentor",
                               "source_ref": "", "use_for_teaching": True,
                               "disclosure": "internal_only"}}
    data = send("brief", {"teaching_brief": brief})
    assert data["plan"]["brief_revision"] == before["plan"]["brief_revision"] + 1
    assert data["plan"]["teaching_brief"]["learning_need"]["text"] == "学习需求"


def test_goals_array_is_rejected_by_contract(plan_client, m1db):
    """记录契约要求：数组直发不是合法客户端 payload，客户端必须包 goals。"""
    plan, _doc = _new_plan_with_version(m1db)
    client = _client_for(plan_client, m1db.alice_id, "advisor", "Alice")
    data = _plan(client, plan["id"])
    lease = _acquire(client, plan["id"], "goals").get_json()
    expected = (data["collaboration"]["sections"] or {}).get("goals", 0)
    res = _patch(client, plan["id"], "goals", [], lease, expected=expected)
    assert res.status_code == 400


def _admin(db):
    return {"user_id": db.admin_id, "role": "admin", "advisor_name": "",
            "display_name": "Admin"}


def test_two_accounts_same_section_do_not_lose_sibling_edits(plan_client, m1db):
    """两个独立账号编辑同一 section 的不同字段：租约串行、旧版本拒绝、最终都落库。"""
    import m1.plan_collaboration as collab

    plan, doc = _new_plan_with_version(m1db)
    collab.add_team_member(m1db.student_id, m1db.bob_id, _admin(m1db))
    alice = _client_for(plan_client, m1db.alice_id, "advisor", "Alice")
    bob = _client_for(plan_client, m1db.bob_id, "advisor", "Bob")

    alice_lease = _acquire(alice, plan["id"], "internal.session.1").get_json()
    assert alice_lease.get("ok")
    base_version = alice_lease["version"]

    title = _client_patch("internal", doc, "sessions.0.title.text", "Alice 标题")
    res = _patch(alice, plan["id"], "internal.session.1", title["patch"],
                 alice_lease, expected=base_version)
    assert res.status_code == 200, res.get_data(as_text=True)

    # Bob 不能在 Alice 持有租约时抢写同一 section。
    blocked = _acquire(bob, plan["id"], "internal.session.1", tab="tab-bob")
    assert blocked.status_code == 409
    assert blocked.get_json()["code"] == "lease_conflict"

    _release = alice.post(
        f"/api/m1/plans/{plan['id']}/leases/release",
        json={"section": "internal.session.1", "token": alice_lease["token"]})
    assert _release.status_code == 200

    bob_lease = _acquire(bob, plan["id"], "internal.session.1", tab="tab-bob").get_json()
    evidence = _client_patch("internal", doc, "sessions.0.evidence.text", "Bob 证据")
    stale = _patch(bob, plan["id"], "internal.session.1", evidence["patch"],
                   bob_lease, expected=base_version)
    assert stale.status_code == 409
    assert stale.get_json()["code"] == "stale_section"

    fresh = _plan(bob, plan["id"])
    fresh_version = fresh["collaboration"]["sections"]["internal.session.1"]
    retry = _patch(bob, plan["id"], "internal.session.1", evidence["patch"],
                   bob_lease, expected=fresh_version)
    assert retry.status_code == 200, retry.get_data(as_text=True)

    final = _plan(alice, plan["id"])["internal"]["doc"]["sessions"][0]
    assert final["title"]["text"] == "Alice 标题"
    assert final["evidence"]["text"] == "Bob 证据"
