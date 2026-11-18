"""DP13-B：共同导师、在线状态、编辑租约与分段并发保存。"""
from __future__ import annotations

import copy
import multiprocessing as mp
import uuid
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

import db as _db
import m1.plan_collaboration as collab
import m1.plan_store as pstore
from test_m1_pipeline import _login
from test_m1_store import m1db  # noqa: F401  pytest fixture
from test_m1dp_api import (  # noqa: F401
    _field, _new_plan_with_version, plan_client,
)
from test_m1dp_pages_parent import _parent_doc, _with_parent  # noqa: F401


def _admin(db):
    return {"user_id": db.admin_id, "role": "admin", "advisor_name": "",
            "display_name": "Admin"}


def _add_bob(db):
    return collab.add_team_member(db.student_id, db.bob_id, _admin(db))


def _client_for(base, user_id, role, name=""):
    client = base.application.test_client()
    _login(client, user_id, role, name)
    return client


def _acquire(client, plan_id, section, tab="tab-a"):
    res = client.post("/api/m1/plans/%d/leases/acquire" % plan_id,
                      json={"section": section, "tab_id": tab})
    return res


def _patch(client, plan_id, section, patch, lease, *, expected=0, document=None,
           key=None):
    if document is None:
        document = lease.get("document_version", 1)
    return client.patch("/api/m1/plans/%d/sections/%s" % (plan_id, section),
                        json={"expected_version": expected,
                              "document_version": document,
                              "lease_token": lease["token"],
                              "idempotency_key": key or uuid.uuid4().hex,
                              "patch": patch})


def _plan(client, plan_id):
    return client.get("/api/m1/plans/%d" % plan_id).get_json()


def _mp_engine(db_path):
    engine = create_engine("sqlite:///%s" % db_path,
                           connect_args={"timeout": 10})
    import db as local_db
    local_db.engine = engine
    return engine


def _mp_busy_timeout(engine):
    with engine.connect() as conn:
        return int(conn.exec_driver_sql("PRAGMA busy_timeout").scalar() or 0)


def _mp_apply_worker(db_path, barrier, queue, plan_id, user, section, token,
                     expected, document_version, title, key):
    engine = None
    try:
        engine = _mp_engine(db_path)
        barrier.wait(timeout=20)
        result = collab.apply_section(
            plan_id, section, {"title": {"text": title}}, user,
            expected_version=expected,
            document_version_value=document_version,
            lease_token=token, idempotency_key=key, require_lease=True)
        queue.put({"ok": True, "rev": result["rev"],
                   "section_version": result["section_version"],
                   "busy_timeout": _mp_busy_timeout(engine)})
    except Exception as exc:  # report the structured failure back to the parent
        queue.put({"ok": False, "type": type(exc).__name__,
                   "code": getattr(exc, "code", None),
                   "message": str(exc),
                   "busy_timeout": _mp_busy_timeout(engine) if engine else None})
    finally:
        if engine is not None:
            engine.dispose()


def _mp_patch_release_worker(db_path, barrier, queue, plan_id, user,
                             section, title, key):
    engine = None
    try:
        engine = _mp_engine(db_path)
        lease = collab.acquire_lease(plan_id, section, user, "mp-patch")
        barrier.wait(timeout=20)
        result = collab.apply_section(
            plan_id, section, {"title": {"text": title}}, user,
            expected_version=lease["version"],
            document_version_value=lease["document_version"],
            lease_token=lease["token"], idempotency_key=key, require_lease=True)
        collab.release_lease(plan_id, section, lease["token"], user)
        queue.put({"ok": True, "rev": result["rev"],
                   "busy_timeout": _mp_busy_timeout(engine)})
    except Exception as exc:
        queue.put({"ok": False, "type": type(exc).__name__,
                   "code": getattr(exc, "code", None), "message": str(exc),
                   "busy_timeout": _mp_busy_timeout(engine) if engine else None})
    finally:
        if engine is not None:
            engine.dispose()


def _mp_approve_worker(db_path, barrier, queue, plan_id, user, rev):
    engine = None
    try:
        engine = _mp_engine(db_path)
        barrier.wait(timeout=20)
        result = collab.approve_plan(plan_id, user, rev)
        queue.put({"ok": True, "rev": result["rev"],
                   "status": result["plan"]["status"]})
    except Exception as exc:
        queue.put({"ok": False, "type": type(exc).__name__,
                   "code": getattr(exc, "code", None), "message": str(exc)})
    finally:
        if engine is not None:
            engine.dispose()


def _mp_context():
    try:
        return mp.get_context("fork")
    except ValueError:
        return mp.get_context("spawn")


def _collect(queue, count=2, timeout=30):
    results = []
    for _ in range(count):
        results.append(queue.get(timeout=timeout))
    return results


# ---------------------------------------------------------------------------
# 团队与可见范围
# ---------------------------------------------------------------------------
def test_team_admin_add_remove_and_plan_access(plan_client, m1db):
    plan, _doc = _new_plan_with_version(m1db)
    admin = _client_for(plan_client, m1db.admin_id, "admin")
    bob = _client_for(plan_client, m1db.bob_id, "advisor", "Bob")

    # 未加入团队：看不到计划与会前准备。
    assert bob.get("/api/m1/plans/%d" % plan["id"]).status_code == 404
    assert bob.get("/api/m1/preps/%d" % plan["prep_id"]).status_code == 403

    # 普通导师不能管理团队。
    alice = _client_for(plan_client, m1db.alice_id, "advisor", "Alice")
    assert alice.post("/api/m1/students/%d/team" % m1db.student_id,
                      json={"user_id": m1db.bob_id}).status_code == 403

    added = admin.post("/api/m1/students/%d/team" % m1db.student_id,
                       json={"user_id": m1db.bob_id})
    assert added.status_code == 200, added.get_json()
    team = added.get_json()["team"]
    assert [row["user_id"] for row in team["co_mentors"]] == [m1db.bob_id]
    assert [row["user_id"] for row in team["primaries"]] == [m1db.alice_id]

    detail = bob.get("/api/m1/plans/%d" % plan["id"]).get_json()
    assert detail["ok"] and detail["can_edit"] is True
    assert detail["can_approve"] is False
    assert detail["collaboration"]["permissions"]["role"] == "co_mentor"
    assert "report_doc" not in detail and "transcript" not in detail
    # DP15: student assignment adds document reads, never prep/report edits.
    prep_detail = bob.get("/api/m1/preps/%d" % plan["prep_id"])
    assert prep_detail.status_code == 200
    assert prep_detail.get_json()["can_edit"] is False
    assert bob.patch("/api/m1/preps/%d" % plan["prep_id"],
                     json={"duration": 90}).status_code == 403
    mine = bob.get("/api/m1/plans?scope=mine").get_json()["plans"]
    assert [row["id"] for row in mine] == [plan["id"]]

    removed = admin.delete("/api/m1/students/%d/team/%d"
                           % (m1db.student_id, m1db.bob_id))
    assert removed.status_code == 200
    assert removed.get_json()["team"]["removed"] is True
    assert bob.get("/api/m1/plans/%d" % plan["id"]).status_code == 404

    actions = [row.action for row in _audit_rows(m1db, m1db.student_id)]
    assert "m1.plan_team_add" in actions and "m1.plan_team_remove" in actions


def _audit_rows(db, student_id):
    import growth_talk_store as gt
    with Session(db.engine) as sess:
        return sess.execute(select(gt.AuditLog).where(
            gt.AuditLog.student_id == int(student_id))).scalars().all()


def test_team_rejects_primary_inactive_and_viewer(plan_client, m1db):
    _new_plan_with_version(m1db)
    admin = _client_for(plan_client, m1db.admin_id, "admin")

    assert admin.post("/api/m1/students/%d/team" % m1db.student_id,
                      json={"user_id": m1db.alice_id}).status_code == 400
    assert admin.post("/api/m1/students/%d/team" % m1db.student_id,
                      json={"user_id": m1db.viewer_id}).status_code == 400
    assert admin.post("/api/m1/students/%d/team" % m1db.student_id,
                      json={"user_id": 99999}).status_code == 400
    with Session(m1db.engine) as sess:
        row = sess.get(_db.User, m1db.bob_id)
        row.is_active = 0
        sess.commit()
    assert admin.post("/api/m1/students/%d/team" % m1db.student_id,
                      json={"user_id": m1db.bob_id}).status_code == 400


# ---------------------------------------------------------------------------
# 分段保存
# ---------------------------------------------------------------------------
def test_different_sections_merge_without_loss(plan_client, m1db):
    plan, _doc = _new_plan_with_version(m1db)
    _add_bob(m1db)
    alice = _client_for(plan_client, m1db.alice_id, "advisor", "Alice")
    bob = _client_for(plan_client, m1db.bob_id, "advisor", "Bob")

    lease_a = _acquire(alice, plan["id"], "internal.session.1").get_json()
    lease_b = _acquire(bob, plan["id"], "internal.session.2").get_json()
    assert lease_a["version"] == 0 and lease_b["version"] == 0
    assert lease_a["document_version"] == lease_b["document_version"]

    res_a = _patch(alice, plan["id"], "internal.session.1",
                   {"title": {"text": "Alice 的第一节"}}, lease_a)
    res_b = _patch(bob, plan["id"], "internal.session.2",
                   {"title": {"text": "Bob 的第二节"}}, lease_b)
    assert res_a.status_code == 200, res_a.get_json()
    assert res_b.status_code == 200, res_b.get_json()

    detail = _plan(alice, plan["id"])
    titles = [session["title"]["text"] for session in detail["internal"]["doc"]["sessions"]]
    assert titles == ["Alice 的第一节", "Bob 的第二节", "第 3 课"]
    assert res_b.get_json()["rev"] == res_a.get_json()["rev"] + 1


def test_same_section_exclusion_and_admin_takeover(plan_client, m1db):
    plan, _doc = _new_plan_with_version(m1db)
    _add_bob(m1db)
    alice = _client_for(plan_client, m1db.alice_id, "advisor", "Alice")
    bob = _client_for(plan_client, m1db.bob_id, "advisor", "Bob")
    admin = _client_for(plan_client, m1db.admin_id, "admin")

    lease = _acquire(alice, plan["id"], "internal.session.1").get_json()
    blocked = _acquire(bob, plan["id"], "internal.session.1")
    assert blocked.status_code == 409
    assert blocked.get_json()["code"] == "lease_conflict"
    assert blocked.get_json()["holder"]["user_id"] == m1db.alice_id

    takeover = admin.post("/api/m1/plans/%d/leases/takeover" % plan["id"],
                          json={"section": "internal.session.1", "tab_id": "admin-tab",
                                "reason": "Alice 掉线"})
    assert takeover.status_code == 200, takeover.get_json()
    new_lease = takeover.get_json()
    assert new_lease["previous"]["user_id"] == m1db.alice_id

    old = _patch(alice, plan["id"], "internal.session.1",
                 {"title": {"text": "旧编辑者"}}, lease)
    assert old.status_code == 409 and old.get_json()["code"] == "lease_conflict"
    new = _patch(admin, plan["id"], "internal.session.1",
                 {"title": {"text": "管理员接管"}}, new_lease)
    assert new.status_code == 200, new.get_json()
    actions = [row.action for row in _audit_rows(m1db, m1db.student_id)]
    assert "m1.plan_lease_takeover" in actions


def test_stale_section_and_expired_lease(plan_client, m1db):
    plan, _doc = _new_plan_with_version(m1db)
    _add_bob(m1db)
    alice = _client_for(plan_client, m1db.alice_id, "advisor", "Alice")
    bob = _client_for(plan_client, m1db.bob_id, "advisor", "Bob")

    lease = _acquire(alice, plan["id"], "internal.session.1").get_json()
    assert _patch(alice, plan["id"], "internal.session.1",
                  {"title": {"text": "第一次"}}, lease).status_code == 200

    stale = _patch(alice, plan["id"], "internal.session.1",
                   {"title": {"text": "基于旧版本的修改"}}, lease, expected=0)
    assert stale.status_code == 409
    assert stale.get_json()["code"] == "stale_section"
    assert stale.get_json()["current_version"] == 1
    assert stale.get_json()["current"]["title"]["text"] == "第一次"

    # 过期租约视为空闲；旧 token 的写入被拒绝。
    with Session(m1db.engine) as sess:
        row = sess.execute(select(collab.PlanEditLease).where(
            collab.PlanEditLease.plan_id == plan["id"],
            collab.PlanEditLease.section_key == "internal.session.1",
            collab.PlanEditLease.released_at.is_(None))).scalars().first()
        row.expires_at = datetime.utcnow() - timedelta(seconds=1)
        sess.commit()
    bob_lease = _acquire(bob, plan["id"], "internal.session.1")
    assert bob_lease.status_code == 200, bob_lease.get_json()
    old = _patch(alice, plan["id"], "internal.session.1",
                 {"title": {"text": "过期编辑"}}, lease, expected=1)
    assert old.status_code == 409 and old.get_json()["code"] == "lease_conflict"


def test_idempotent_retry_does_not_double_apply(plan_client, m1db):
    plan, _doc = _new_plan_with_version(m1db)
    alice = _client_for(plan_client, m1db.alice_id, "advisor", "Alice")
    lease = _acquire(alice, plan["id"], "internal.session.1").get_json()
    key = "retry-key-0001"
    first = _patch(alice, plan["id"], "internal.session.1",
                   {"title": {"text": "幂等保存"}}, lease, key=key)
    assert first.status_code == 200
    again = _patch(alice, plan["id"], "internal.session.1",
                   {"title": {"text": "幂等保存"}}, lease, key=key)
    assert again.status_code == 200
    assert again.get_json()["replayed"] is True
    assert again.get_json()["rev"] == first.get_json()["rev"]
    conflict = _patch(alice, plan["id"], "internal.session.1",
                      {"title": {"text": "不同内容"}}, lease, key=key)
    assert conflict.status_code == 409
    assert conflict.get_json()["code"] == "idempotency_conflict"
    assert pstore.get_plan(plan["id"])["rev"] == first.get_json()["rev"]


def _release(client, plan_id, section, lease):
    return client.post("/api/m1/plans/%d/leases/release" % plan_id,
                       json={"section": section, "token": lease["token"]})


def test_list_and_child_leases_are_mutually_exclusive(plan_client, m1db):
    plan, _doc = _new_plan_with_version(m1db)
    _add_bob(m1db)
    alice = _client_for(plan_client, m1db.alice_id, "advisor", "Alice")
    bob = _client_for(plan_client, m1db.bob_id, "advisor", "Bob")
    list_section = "internal.session.1.activities"
    child = "internal.session.1.activity.s1a1"

    child_lease = _acquire(alice, plan["id"], child).get_json()
    blocked_list = _acquire(bob, plan["id"], list_section)
    assert blocked_list.status_code == 409
    assert blocked_list.get_json()["reason"] == "related_section"
    assert _release(alice, plan["id"], child, child_lease).status_code == 200

    list_lease = _acquire(bob, plan["id"], list_section).get_json()
    blocked_child = _acquire(alice, plan["id"], child)
    assert blocked_child.status_code == 409
    assert blocked_child.get_json()["reason"] == "related_section"
    assert _release(bob, plan["id"], list_section, list_lease).status_code == 200


def test_disjoint_child_activities_in_same_list_merge(plan_client, m1db):
    plan, doc = _new_plan_with_version(m1db)
    _add_bob(m1db)
    alice = _client_for(plan_client, m1db.alice_id, "advisor", "Alice")
    bob = _client_for(plan_client, m1db.bob_id, "advisor", "Bob")
    list_section = "internal.session.1.activities"
    original = copy.deepcopy(doc["sessions"][0]["activities"][0])
    extra = copy.deepcopy(original)
    extra["id"] = "s1a2"
    extra["name"] = _field("第二条活动")
    list_lease = _acquire(alice, plan["id"], list_section).get_json()
    assert _patch(alice, plan["id"], list_section, [original, extra],
                  list_lease).status_code == 200
    assert _release(alice, plan["id"], list_section, list_lease).status_code == 200

    lease_a = _acquire(alice, plan["id"], "internal.session.1.activity.s1a1").get_json()
    lease_b = _acquire(bob, plan["id"], "internal.session.1.activity.s1a2",
                       tab="bob-child").get_json()
    res_a = _patch(alice, plan["id"], "internal.session.1.activity.s1a1",
                   {"name": {"text": "Alice 改的第一条"}}, lease_a,
                   expected=lease_a["version"])
    res_b = _patch(bob, plan["id"], "internal.session.1.activity.s1a2",
                   {"name": {"text": "Bob 改的第二条"}}, lease_b,
                   expected=lease_b["version"])
    assert res_a.status_code == 200, res_a.get_json()
    assert res_b.status_code == 200, res_b.get_json()
    activities = pstore.current_version(plan["id"], "internal")["doc"]["sessions"][0]["activities"]
    assert [item["name"]["text"] for item in activities] == [
        "Alice 改的第一条", "Bob 改的第二条"]


def test_stale_list_after_child_edit_conflicts_after_reacquire(plan_client, m1db):
    plan, doc = _new_plan_with_version(m1db)
    alice = _client_for(plan_client, m1db.alice_id, "advisor", "Alice")
    list_section = "internal.session.1.activities"
    child = "internal.session.1.activity.s1a1"
    stale_list = copy.deepcopy(doc["sessions"][0]["activities"])

    list_lease = _acquire(alice, plan["id"], list_section).get_json()
    assert list_lease["version"] == 0
    assert _release(alice, plan["id"], list_section, list_lease).status_code == 200

    child_lease = _acquire(alice, plan["id"], child).get_json()
    saved = _patch(alice, plan["id"], child,
                   {"steps": {"text": "ALICE_SAVED_NEW_INSTRUCTIONS"}}, child_lease,
                   expected=0)
    assert saved.status_code == 200, saved.get_json()
    assert _release(alice, plan["id"], child, child_lease).status_code == 200

    fresh = _acquire(alice, plan["id"], list_section).get_json()
    assert fresh["version"] == 1
    # 重新取得租约也不能用旧列表覆盖已保存的子项编辑。
    stale = _patch(alice, plan["id"], list_section, stale_list, fresh, expected=0)
    assert stale.status_code == 409
    assert stale.get_json()["code"] == "stale_section"
    assert stale.get_json()["current_version"] == 1
    actual = pstore.current_version(plan["id"], "internal")["doc"]["sessions"][0]["activities"][0]["steps"]["text"]
    assert actual == "ALICE_SAVED_NEW_INSTRUCTIONS"


def test_stale_child_after_list_replacement_conflicts(plan_client, m1db):
    plan, doc = _new_plan_with_version(m1db)
    alice = _client_for(plan_client, m1db.alice_id, "advisor", "Alice")
    list_section = "internal.session.1.activities"
    child = "internal.session.1.activity.s1a1"
    child_lease = _acquire(alice, plan["id"], child).get_json()
    assert _release(alice, plan["id"], child, child_lease).status_code == 200

    list_lease = _acquire(alice, plan["id"], list_section).get_json()
    replacement = copy.deepcopy(doc["sessions"][0]["activities"])
    replacement[0]["name"] = _field("列表替换后的名称")
    assert _patch(alice, plan["id"], list_section, replacement, list_lease,
                  expected=0).status_code == 200
    assert _release(alice, plan["id"], list_section, list_lease).status_code == 200

    fresh_child = _acquire(alice, plan["id"], child).get_json()
    assert fresh_child["version"] == 1
    stale = _patch(alice, plan["id"], child,
                   {"name": {"text": "旧子项"}}, fresh_child, expected=0)
    assert stale.status_code == 409
    assert stale.get_json()["code"] == "stale_section"


def test_reorder_delete_and_id_reuse_use_stable_ids(plan_client, m1db):
    plan, doc = _new_plan_with_version(m1db)
    alice = _client_for(plan_client, m1db.alice_id, "advisor", "Alice")
    list_section = "internal.session.1.activities"
    lease = _acquire(alice, plan["id"], list_section).get_json()
    original = copy.deepcopy(doc["sessions"][0]["activities"][0])
    extra = copy.deepcopy(original)
    extra["id"] = "s1a2"
    extra["name"] = _field("补充活动")

    added = _patch(alice, plan["id"], list_section, [extra, original], lease)
    assert added.status_code == 200, added.get_json()
    reordered = _patch(alice, plan["id"], list_section, [original, extra],
                       lease, expected=1)
    assert reordered.status_code == 200, reordered.get_json()
    assert _release(alice, plan["id"], list_section, lease).status_code == 200

    # 列表改动已把子项版本推到 2；按下标改不到另一条活动。
    activity_lease = _acquire(alice, plan["id"],
                              "internal.session.1.activity.s1a2",
                              tab="tab-activity").get_json()
    assert activity_lease["version"] == 2
    edited = _patch(alice, plan["id"], "internal.session.1.activity.s1a2",
                    {"name": {"text": "按稳定编号修改"}}, activity_lease,
                    expected=2)
    assert edited.status_code == 200, edited.get_json()
    activities = _plan(alice, plan["id"])["internal"]["doc"]["sessions"][0]["activities"]
    assert [item["id"] for item in activities] == ["s1a1", "s1a2"]
    assert activities[1]["name"]["text"] == "按稳定编号修改"
    assert activities[0]["name"]["text"] == "活动"
    assert _release(alice, plan["id"],
                    "internal.session.1.activity.s1a2", activity_lease).status_code == 200

    # 列表替换（删除 s1a2）会推进所有子项版本。
    lease2 = _acquire(alice, plan["id"], list_section).get_json()
    assert lease2["version"] == 3
    removed = _patch(alice, plan["id"], list_section, [original], lease2,
                     expected=3)
    assert removed.status_code == 200, removed.get_json()
    assert _release(alice, plan["id"], list_section, lease2).status_code == 200

    deleted_lease = _acquire(alice, plan["id"],
                             "internal.session.1.activity.s1a2",
                             tab="tab-deleted").get_json()
    gone = _patch(alice, plan["id"], "internal.session.1.activity.s1a2",
                  {"name": {"text": "不存在"}}, deleted_lease,
                  expected=deleted_lease["version"])
    assert gone.status_code == 404
    assert gone.get_json()["code"] == "item_not_found"
    assert _release(alice, plan["id"],
                    "internal.session.1.activity.s1a2",
                    deleted_lease).status_code == 200

    # 重新加回同一 ID 后，旧版本不能用。
    readd = _acquire(alice, plan["id"], list_section).get_json()
    readded = _patch(alice, plan["id"], list_section, [original, extra], readd,
                     expected=readd["version"])
    assert readded.status_code == 200, readded.get_json()
    assert _release(alice, plan["id"], list_section, readd).status_code == 200
    reused = _acquire(alice, plan["id"],
                      "internal.session.1.activity.s1a2", tab="tab-reuse").get_json()
    stale = _patch(alice, plan["id"], "internal.session.1.activity.s1a2",
                   {"name": {"text": "旧版本"}}, reused,
                   expected=deleted_lease["version"])
    assert stale.status_code == 409
    assert stale.get_json()["code"] == "stale_section"


# ---------------------------------------------------------------------------
# 批准 / 重新打开
# ---------------------------------------------------------------------------
def test_approval_checks_revision_and_active_edits(plan_client, m1db):
    plan, _doc = _new_plan_with_version(m1db)
    _add_bob(m1db)
    alice = _client_for(plan_client, m1db.alice_id, "advisor", "Alice")
    bob = _client_for(plan_client, m1db.bob_id, "advisor", "Bob")
    lease = _acquire(alice, plan["id"], "internal.session.1").get_json()

    blocked = alice.post("/api/m1/plans/%d/approve" % plan["id"],
                         json={"rev": plan["rev"]})
    assert blocked.status_code == 409
    assert blocked.get_json()["code"] == "lease_conflict"

    released = alice.post("/api/m1/plans/%d/leases/release" % plan["id"],
                          json={"section": "internal.session.1",
                                "token": lease["token"]})
    assert released.status_code == 200

    stale = alice.post("/api/m1/plans/%d/approve" % plan["id"],
                       json={"rev": plan["rev"] - 1})
    assert stale.status_code == 409
    assert stale.get_json()["rev"] == plan["rev"]

    # 共同导师不能批准/重新打开。
    assert bob.post("/api/m1/plans/%d/approve" % plan["id"],
                    json={"rev": plan["rev"]}).status_code == 403

    approved = alice.post("/api/m1/plans/%d/approve" % plan["id"],
                          json={"rev": plan["rev"]})
    assert approved.status_code == 200, approved.get_json()
    assert approved.get_json()["plan"]["status"] == "approved"
    assert approved.get_json()["document_version"] >= 2

    assert bob.post("/api/m1/plans/%d/reopen" % plan["id"],
                    json={"rev": approved.get_json()["plan"]["rev"]}).status_code == 403
    reopened = alice.post("/api/m1/plans/%d/reopen" % plan["id"],
                          json={"rev": approved.get_json()["plan"]["rev"]})
    assert reopened.status_code == 200, reopened.get_json()
    assert reopened.get_json()["plan"]["status"] == "review"


# ---------------------------------------------------------------------------
# 家庭建议确认绑定
# ---------------------------------------------------------------------------
def test_changed_family_text_resets_only_changed_acknowledgements(plan_client, m1db):
    plan = _with_parent(m1db, _parent_doc(seen=(True, True)))
    alice = _client_for(plan_client, m1db.alice_id, "advisor", "Alice")
    old_hashes = [collab.family_hash({"text": "家庭建议一。"}),
                  collab.family_hash({"text": "家庭建议二。"})]
    lease = _acquire(alice, plan["id"], "parent.family").get_json()
    saved = _patch(alice, plan["id"], "parent.family",
                   [{"text": "NEW_UNREVIEWED_ADVICE"},
                    {"text": "家庭建议二。"}], lease)
    assert saved.status_code == 200, saved.get_json()
    doc = pstore.current_version(plan["id"], "parent")["doc"]
    assert doc["family_seen"] == [False, True]
    assert doc["family_ack"][0]["hash"] != old_hashes[0]
    assert doc["family_ack"][1]["hash"] == old_hashes[1]
    assert _release(alice, plan["id"], "parent.family", lease).status_code == 200

    ack_lease = _acquire(alice, plan["id"], "parent.family_seen").get_json()
    delayed = _patch(alice, plan["id"], "parent.family_seen",
                     {"seen": [True, True], "hashes": old_hashes},
                     ack_lease, expected=ack_lease["version"])
    assert delayed.status_code == 409
    assert delayed.get_json()["code"] == "stale_family_ack"
    assert pstore.current_version(plan["id"], "parent")["doc"]["family_seen"] == [False, True]

    current = collab.family_state(doc)
    accepted = _patch(alice, plan["id"], "parent.family_seen",
                      {"seen": [True, True],
                       "hashes": [item["hash"] for item in current]},
                      ack_lease, expected=ack_lease["version"])
    assert accepted.status_code == 200, accepted.get_json()
    assert pstore.current_version(plan["id"], "parent")["doc"]["family_seen"] == [True, True]


def test_family_text_and_ack_races_in_both_orders(plan_client, m1db):
    _add_bob(m1db)
    alice = _client_for(plan_client, m1db.alice_id, "advisor", "Alice")
    bob = _client_for(plan_client, m1db.bob_id, "advisor", "Bob")

    # 顺序一：Alice 先改文字，Bob 的旧确认版本失效。
    plan = _with_parent(m1db, _parent_doc(seen=(True, True)))
    family_lease = _acquire(alice, plan["id"], "parent.family").get_json()
    ack_lease = _acquire(bob, plan["id"], "parent.family_seen",
                         tab="bob-ack").get_json()
    assert _patch(alice, plan["id"], "parent.family",
                  [{"text": "先改的建议一"}, {"text": "先改的建议二"}],
                  family_lease).status_code == 200
    stale_ack = _patch(bob, plan["id"], "parent.family_seen",
                       {"seen": [True, True],
                        "hashes": [collab.family_hash({"text": "家庭建议一。"}),
                                   collab.family_hash({"text": "家庭建议二。"})]},
                       ack_lease, expected=ack_lease["version"])
    assert stale_ack.status_code == 409
    assert stale_ack.get_json()["code"] in ("stale_section", "stale_family_ack")

    # 顺序二：Bob 先确认，Alice 后改文字仍会重置改动项。
    plan2 = _with_parent(m1db, _parent_doc(seen=(True, True)))
    family_lease = _acquire(alice, plan2["id"], "parent.family").get_json()
    ack_lease = _acquire(bob, plan2["id"], "parent.family_seen",
                         tab="bob-ack-2").get_json()
    current = collab.family_state(pstore.current_version(plan2["id"], "parent")["doc"])
    assert _patch(bob, plan2["id"], "parent.family_seen",
                  {"seen": [True, True],
                   "hashes": [item["hash"] for item in current]},
                  ack_lease, expected=ack_lease["version"]).status_code == 200
    assert _patch(alice, plan2["id"], "parent.family",
                  [{"text": "后改的建议一"}, {"text": "家庭建议二。"}],
                  family_lease).status_code == 200
    assert pstore.current_version(plan2["id"], "parent")["doc"]["family_seen"] == [False, True]


def test_parent_export_rechecks_current_family_ack_atomically(plan_client, m1db):
    plan = _with_parent(m1db, _parent_doc(seen=(True, True)))
    alice = _client_for(plan_client, m1db.alice_id, "advisor", "Alice")
    confirmed = alice.post("/api/m1/plans/%d/parent/confirm" % plan["id"],
                           json={"rev": plan["rev"]})
    assert confirmed.status_code == 200, confirmed.get_json()
    plan = pstore.get_plan(plan["id"])
    version = pstore.current_version(plan["id"], "parent")
    original_ack = [{"hash": collab.family_hash(item), "seen": True}
                    for item in version["doc"]["family"]]
    distorted = copy.deepcopy(version["doc"])
    distorted["family_seen"] = [True, True]
    distorted["family_ack"] = original_ack
    distorted["family"][1] = {"text": "EXPORT_UNREVIEWED_ADVICE", "src": "mentor"}
    with Session(m1db.engine) as sess:
        row = sess.get(pstore.M1PlanVersion, version["id"])
        row.doc = pstore._dumps(distorted)
        sess.commit()
    res = alice.post("/api/m1/plans/%d/parent/export" % plan["id"],
                     json={"rev": plan["rev"]})
    assert res.status_code == 409
    assert res.get_json()["code"] == "parent_blocking"
    assert any(item["path"][0] == "family_seen"
               for item in res.get_json()["blocking"])


def test_legacy_parent_document_save_resets_changed_family_ack(plan_client, m1db):
    plan = _with_parent(m1db, _parent_doc(seen=(True, True)))
    alice = _client_for(plan_client, m1db.alice_id, "advisor", "Alice")
    version = pstore.current_version(plan["id"], "parent")
    changed = copy.deepcopy(version["doc"])
    changed["family"] = [{"text": "旧版整份保存的新建议一", "src": "mentor"},
                         {"text": "旧版整份保存的新建议二", "src": "mentor"}]
    changed["family_seen"] = [True, True]
    res = alice.put("/api/m1/plans/%d/parent" % plan["id"],
                    json={"rev": plan["rev"], "doc": changed})
    assert res.status_code == 200, res.get_json()
    saved = pstore.current_version(plan["id"], "parent")["doc"]
    assert saved["family_seen"] == [False, False]
    assert all(item["seen"] is False for item in saved["family_ack"])
    assert all(item["hash"] == collab.family_hash(field)
               for item, field in zip(saved["family_ack"], saved["family"]))
    current = pstore.get_plan(plan["id"])
    blocked = alice.post("/api/m1/plans/%d/parent/confirm" % plan["id"],
                         json={"rev": current["rev"]})
    assert blocked.status_code == 409


def test_whole_internal_save_bumps_list_and_child_versions(plan_client, m1db):
    plan, doc = _new_plan_with_version(m1db)
    alice = _client_for(plan_client, m1db.alice_id, "advisor", "Alice")
    changed = copy.deepcopy(doc)
    extra = copy.deepcopy(changed["sessions"][0]["activities"][0])
    extra["id"] = "s1a2"
    extra["name"] = _field("整份保存新增活动")
    changed["sessions"][0]["activities"].append(extra)
    res = alice.put("/api/m1/plans/%d/internal" % plan["id"],
                    json={"rev": plan["rev"], "doc": changed})
    assert res.status_code == 200, res.get_json()
    child_lease = _acquire(alice, plan["id"],
                           "internal.session.1.activity.s1a2").get_json()
    assert child_lease["version"] >= 1
    stale = _patch(alice, plan["id"], "internal.session.1.activity.s1a2",
                   {"name": {"text": "旧版本"}}, child_lease,
                   expected=0, document=child_lease["document_version"])
    assert stale.status_code == 409
    assert stale.get_json()["code"] == "stale_section"


def test_parent_transition_rechecks_current_family_ack_atomically(plan_client, m1db):
    plan = _with_parent(m1db, _parent_doc(seen=(True, True)))
    alice = _client_for(plan_client, m1db.alice_id, "advisor", "Alice")
    version = pstore.current_version(plan["id"], "parent")
    original_ack = [{"hash": collab.family_hash(item), "seen": True}
                    for item in version["doc"]["family"]]
    distorted = copy.deepcopy(version["doc"])
    distorted["family_seen"] = [True, True]
    distorted["family_ack"] = original_ack
    distorted["family"][0] = {"text": "UNREVIEWED_CHANGED_ADVICE", "src": "mentor"}
    with Session(m1db.engine) as sess:
        row = sess.get(pstore.M1PlanVersion, version["id"])
        row.doc = pstore._dumps(distorted)
        sess.commit()
    plan = pstore.get_plan(plan["id"])
    res = alice.post("/api/m1/plans/%d/parent/confirm" % plan["id"],
                     json={"rev": plan["rev"]})
    assert res.status_code == 409
    assert res.get_json()["code"] == "parent_blocking"
    assert any(item["path"][0] == "family_seen"
               for item in res.get_json()["blocking"])


# ---------------------------------------------------------------------------
# 撤销 / 在线状态
# ---------------------------------------------------------------------------
def test_removal_revokes_lease_and_presence(plan_client, m1db):
    plan, _doc = _new_plan_with_version(m1db)
    _add_bob(m1db)
    admin = _client_for(plan_client, m1db.admin_id, "admin")
    bob = _client_for(plan_client, m1db.bob_id, "advisor", "Bob")
    lease = _acquire(bob, plan["id"], "internal.session.1").get_json()
    presence = bob.post("/api/m1/plans/%d/presence" % plan["id"],
                        json={"tab_id": "bob-tab", "state": "editing",
                              "editing_section": "internal.session.1"})
    assert presence.status_code == 200
    assert [row["user_id"] for row in presence.get_json()["participants"]] == [m1db.bob_id]

    assert admin.delete("/api/m1/students/%d/team/%d"
                        % (m1db.student_id, m1db.bob_id)).status_code == 200
    assert bob.get("/api/m1/plans/%d" % plan["id"]).status_code == 404
    assert _patch(bob, plan["id"], "internal.session.1",
                  {"title": {"text": "被移除后"}}, lease).status_code == 404
    with Session(m1db.engine) as sess:
        leases = sess.execute(select(collab.PlanEditLease).where(
            collab.PlanEditLease.plan_id == plan["id"],
            collab.PlanEditLease.user_id == m1db.bob_id,
            collab.PlanEditLease.released_at.is_(None))).scalars().all()
        presence_rows = sess.execute(select(collab.PlanPresence).where(
            collab.PlanPresence.plan_id == plan["id"],
            collab.PlanPresence.user_id == m1db.bob_id)).scalars().all()
    assert leases == [] and presence_rows == []


def test_presence_ttl_and_minimal_personal_data(plan_client, m1db):
    plan, _doc = _new_plan_with_version(m1db)
    alice = _client_for(plan_client, m1db.alice_id, "advisor", "Alice")
    sent = alice.post("/api/m1/plans/%d/presence" % plan["id"],
                      json={"tab_id": "alice-tab", "state": "editing",
                            "editing_section": "internal.session.1"})
    assert sent.status_code == 200
    participant = sent.get_json()["participants"][0]
    assert participant["name"] == "Alice"
    assert participant["editing_section"] == "internal.session.1"
    assert set(participant) == {"user_id", "name", "role", "state",
                                "editing_section", "last_seen", "tabs"}
    assert "username" not in participant and "email" not in participant

    with Session(m1db.engine) as sess:
        row = sess.execute(select(collab.PlanPresence).where(
            collab.PlanPresence.plan_id == plan["id"],
            collab.PlanPresence.user_id == m1db.alice_id)).scalars().first()
        row.last_seen_at = datetime.utcnow() - timedelta(
            seconds=collab.PRESENCE_TTL_SECONDS + 5)
        sess.commit()
    listed = alice.get("/api/m1/plans/%d/presence" % plan["id"]).get_json()
    assert listed["participants"] == []

    # 在线状态从不授予访问权。
    bob = _client_for(plan_client, m1db.bob_id, "advisor", "Bob")
    assert bob.post("/api/m1/plans/%d/presence" % plan["id"],
                    json={"tab_id": "bob-tab"}).status_code == 404


# ---------------------------------------------------------------------------
# AI 写入与生成锁
# ---------------------------------------------------------------------------
def test_ai_writes_cannot_overwrite_newer_revision(plan_client, m1db):
    plan, _doc = _new_plan_with_version(m1db)
    stale_rev = plan["rev"]
    pstore.save_goals(plan["id"], stale_rev, [{"code": "R2.2",
                                               "goal": {"text": "导师改过", "src": "mentor"},
                                               "start": {"text": "起点", "src": "ai"},
                                               "expected": {"text": "预期", "src": "ai"},
                                               "locked": True}])
    with pytest.raises(pstore.RevConflict):
        pstore.save_goal_ai(plan["id"], "R2.2", "AI 起点", "AI 预期",
                            goal="AI 目标", expected_rev=stale_rev)


def test_patch_refused_while_generating(plan_client, m1db):
    plan, _doc = _new_plan_with_version(m1db)
    alice = _client_for(plan_client, m1db.alice_id, "advisor", "Alice")
    lease = _acquire(alice, plan["id"], "internal.session.1").get_json()
    pstore.begin_generation(plan["id"], "internal")
    lease["document_version"] = collab.document_version(plan["id"])
    res = _patch(alice, plan["id"], "internal.session.1",
                 {"title": {"text": "生成中"}}, lease)
    assert res.status_code == 409
    assert "生成" in res.get_json()["error"]


# ---------------------------------------------------------------------------
# 独立 OS 进程并发（同一 SQLite 文件，各自 engine）
# ---------------------------------------------------------------------------
def _db_path(db):
    return db.engine.url.database


def test_multiprocess_disjoint_sections_both_survive(plan_client, m1db):
    plan, _doc = _new_plan_with_version(m1db)
    _add_bob(m1db)
    alice_lease = collab.acquire_lease(
        plan["id"], "internal.session.1", _client_user(m1db.alice_id, "Alice"),
        "mp-alice")
    bob_lease = collab.acquire_lease(
        plan["id"], "internal.session.2", _client_user(m1db.bob_id, "Bob"),
        "mp-bob")
    ctx = _mp_context()
    barrier, queue = ctx.Barrier(2), ctx.Queue()
    path = _db_path(m1db)
    p1 = ctx.Process(target=_mp_apply_worker, args=(
        path, barrier, queue, plan["id"], _client_user(m1db.alice_id, "Alice"),
        "internal.session.1", alice_lease["token"], alice_lease["version"],
        alice_lease["document_version"], "MP Alice Session 1", "mp-apply-a"))
    p2 = ctx.Process(target=_mp_apply_worker, args=(
        path, barrier, queue, plan["id"], _client_user(m1db.bob_id, "Bob"),
        "internal.session.2", bob_lease["token"], bob_lease["version"],
        bob_lease["document_version"], "MP Bob Session 2", "mp-apply-b"))
    p1.start(); p2.start()
    results = _collect(queue)
    p1.join(30); p2.join(30)
    assert p1.exitcode == 0 and p2.exitcode == 0
    assert all(item["ok"] for item in results), results
    assert all((item.get("busy_timeout") or 0) >= 5000 for item in results), results
    doc = pstore.current_version(plan["id"], "internal")["doc"]
    assert [session["title"]["text"] for session in doc["sessions"][:2]] == [
        "MP Alice Session 1", "MP Bob Session 2"]


def test_multiprocess_same_lease_stale_writer_conflicts(plan_client, m1db):
    plan, _doc = _new_plan_with_version(m1db)
    alice = _client_user(m1db.alice_id, "Alice")
    lease = collab.acquire_lease(plan["id"], "internal.session.1", alice,
                                 "mp-shared")
    ctx = _mp_context()
    barrier, queue = ctx.Barrier(2), ctx.Queue()
    path = _db_path(m1db)
    common = (path, barrier, queue, plan["id"], alice,
              "internal.session.1", lease["token"], lease["version"],
              lease["document_version"])
    p1 = ctx.Process(target=_mp_apply_worker, args=common + (
        "MP First Tab", "mp-same-a"))
    p2 = ctx.Process(target=_mp_apply_worker, args=common + (
        "MP Second Tab", "mp-same-b"))
    p1.start(); p2.start()
    results = _collect(queue)
    p1.join(30); p2.join(30)
    assert p1.exitcode == 0 and p2.exitcode == 0
    ok = [item for item in results if item["ok"]]
    failed = [item for item in results if not item["ok"]]
    assert len(ok) == 1 and len(failed) == 1, results
    assert failed[0]["code"] in ("stale_section", "lease_conflict"), failed
    doc = pstore.current_version(plan["id"], "internal")["doc"]
    assert doc["sessions"][0]["title"]["text"] in ("MP First Tab", "MP Second Tab")


def test_multiprocess_approval_versus_save_is_serializable(plan_client, m1db):
    plan, _doc = _new_plan_with_version(m1db)
    alice = _client_user(m1db.alice_id, "Alice")
    ctx = _mp_context()
    barrier, queue = ctx.Barrier(2), ctx.Queue()
    path = _db_path(m1db)
    saver = ctx.Process(target=_mp_patch_release_worker, args=(
        path, barrier, queue, plan["id"], alice, "internal.session.1",
        "MP Saved Before Approval", "mp-approve-save"))
    approver = ctx.Process(target=_mp_approve_worker, args=(
        path, barrier, queue, plan["id"], alice, plan["rev"]))
    saver.start(); approver.start()
    results = _collect(queue)
    saver.join(30); approver.join(30)
    assert saver.exitcode == 0 and approver.exitcode == 0
    patch_result = next(item for item in results if "busy_timeout" in item)
    approve_result = next(item for item in results if "busy_timeout" not in item)
    assert patch_result["ok"], results
    assert patch_result.get("busy_timeout", 0) >= 5000
    assert not approve_result["ok"], results
    final = pstore.get_plan(plan["id"])
    assert final["status"] == "review"
    title = pstore.current_version(plan["id"], "internal")["doc"]["sessions"][0]["title"]["text"]
    assert title == "MP Saved Before Approval"


def _client_user(user_id, name):
    return {"user_id": user_id, "role": "advisor", "advisor_name": name,
            "display_name": name}
