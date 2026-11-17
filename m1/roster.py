"""Minimal M1 discovery, independent of raw student/prep access.

Build authorized source maps once. Never use plan serialization here: it contains
raw-source identifiers and mentor inputs that team-only discovery must not expose.
"""
from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

import db
from m1 import plan_collaboration as collab, plan_store as plans, store


def visible_sources(user) -> list[dict]:
    """One student row with latest readable prep and highest readable Block.

    Visibility follows can_access_student/can_access_prep/can_view_plan, without
    their per-record queries. Creation is participation, never access authority.
    The caller projects these internal source summaries into the public schema.
    """
    u = store._user_dict(user)
    uid = u.get("user_id")
    settings = db.effective_account_settings(
        u.get("role") or "", u.get("student_scope"), u.get("detail_level"),
        u.get("m1_access"), u.get("m1_admin"))
    if uid is None or u.get("role") not in ("admin", "advisor") or not settings["m1_access"]:
        return []
    all_students = u.get("role") == "admin" or settings["student_scope"] == "all"
    advisor = (u.get("advisor_name") or "").strip()
    own_student = db.Student.advisor_name == advisor if advisor else False
    raw_student = True if all_students else own_student
    prep = store.M1Prep
    plan = plans.M1Plan
    team = collab.PlanTeamMember
    with Session(db.engine) as sess:
        account = sess.get(db.User, uid)
        if account is None or not account.is_active:
            return []
        # Membership is effective only while its account is active. For raw-scope
        # readers, a team is also an M1 participation marker before any plan exists.
        memberships = sess.execute(
            select(team.student_id, team.user_id, team.role)
            .join(db.User, db.User.id == team.user_id)
            .join(db.Student, db.Student.id == team.student_id)
            .where(db.User.is_active == 1,
                   or_(raw_student, team.user_id == uid))).all()
        my_team = {r.student_id: r.role for r in memberships if r.user_id == uid}
        prep_rows = sess.execute(
            select(prep.id, prep.student_id, prep.meeting_date,
                   prep.mentor_user_id, prep.created_by, prep.status,
                   prep.current_version_id, db.User.display_name,
                   db.User.advisor_name, db.User.username)
            .join(db.Student, db.Student.id == prep.student_id)
            .outerjoin(db.User, db.User.id == prep.mentor_user_id)
            .where(or_(raw_student, prep.mentor_user_id == uid))
            .order_by(prep.updated_at.desc(), prep.id.desc())).all()
        readable_preps = {r.id for r in prep_rows}
        # A report plan requires its actual prep authority (not merely its plan
        # mentor field); direct plans require student authority or team membership.
        plan_rows = sess.execute(
            select(plan.id, plan.student_id, plan.block_no, plan.status,
                   plan.parent_status, plan.current_version_id,
                   plan.parent_version_id, plan.mentor_user_id, plan.created_by,
                   plans.M1PlanVersion.source_version_id)
            .join(db.Student, db.Student.id == plan.student_id)
            .outerjoin(plans.M1PlanVersion,
                       plans.M1PlanVersion.id == plan.parent_version_id)
            .where(or_(raw_student, plan.student_id.in_(my_team),
                       (plan.source_mode == "report") & plan.prep_id.in_(readable_preps)))
            .order_by(plan.block_no.desc(), plan.updated_at.desc(), plan.id.desc())).all()
        ids = ({r.student_id for r in memberships}
               | {r.student_id for r in prep_rows} | {r.student_id for r in plan_rows})
        students = sess.execute(
            select(db.Student.id, db.Student.name, db.Student.student_code,
                   db.Student.grade, db.Student.advisor_name)
            .where(db.Student.id.in_(ids))
            .order_by(db.Student.name, db.Student.id)).all()

    rows = {}
    for s in students:
        roles = []
        if s.id in my_team:
            roles.append(my_team[s.id])
        if advisor and (s.advisor_name or "").strip() == advisor:
            roles.append("advisor")
        rows[s.id] = {"student_id": s.id, "student_name": s.name or "",
                      "student_code": s.student_code or "", "grade": s.grade or "",
                      "roles": roles, "participating": bool(roles),
                      "prep": None, "plan": None}
    for sources, kind in ((prep_rows, "prep"), (plan_rows, "plan")):
        for source in sources:
            row = rows[source.student_id]
            if source.mentor_user_id == uid and "primary" not in row["roles"]:
                row["roles"].append("primary")
            if source.created_by == uid and "creator" not in row["roles"]:
                row["roles"].append("creator")
            row["participating"] = bool(row["roles"])
            if row[kind] is not None:
                continue
            if kind == "prep":
                row[kind] = {"id": source.id, "meeting_date": source.meeting_date or "",
                             "mentor_name": source.display_name or source.advisor_name
                             or source.username or "", "status": source.status,
                             "current_version_id": source.current_version_id}
            else:
                row[kind] = {"id": source.id, "block_no": source.block_no,
                             "status": source.status,
                             "status_label": plans.STATUS_LABELS.get(source.status, source.status),
                             "parent_status": source.parent_status,
                             "parent_version_id": source.parent_version_id,
                             "parent_stale": bool(source.parent_version_id and (
                                 source.status != "approved" or
                                 (source.source_version_id or 0) != (source.current_version_id or 0)))}
    return list(rows.values())
