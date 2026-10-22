"""Growth Talk 报告契约与确认事务测试（tmp SQLite，不联网）。"""
from __future__ import annotations

import json

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session

import db as _db
import growth_talk_store as store
from growth_talk import runs
from growth_talk.errors import ActionError
from growth_talk.report_contract import (
    build_report_preview,
    confirm_report,
    validate_report,
)


class GTDB:
    def __init__(self, engine):
        self.engine = engine
        self.student_id = None

    def insert_student(self, name="测试学生", grade="10", school="测试中学"):
        with Session(self.engine) as sess:
            row = _db.Student(student_code="Y4-9001", name=name, grade=grade,
                              school=school, advisor_name="Mine")
            sess.add(row)
            sess.commit()
            self.student_id = row.id
        return self.student_id


@pytest.fixture()
def qdb(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'growth_talk_report.db'}")

    @event.listens_for(engine, "connect")
    def _enable_fk(dbapi_connection, _record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    tables = [
        _db.Student.__table__,
        store.GtSource.__table__,
        store.GtRun.__table__,
        store.GtUnderstanding.__table__,
        store.GtInterest.__table__,
        store.GtQuadrant.__table__,
        store.GtSuggestion.__table__,
        store.GtReport.__table__,
        store.ExternalIdentity.__table__,
        store.AuditLog.__table__,
        store.CrmDeliveryReceipt.__table__,
        store.CrmAppointment.__table__,
    ]
    _db.Base.metadata.create_all(engine, tables=tables)
    monkeypatch.setattr(_db, "engine", engine)

    helper = GTDB(engine)
    helper.insert_student()
    yield helper
    engine.dispose()


def _valid_payload() -> dict:
    return {
        "schema": "first-touch.report.v1",
        "reportId": "1",
        "version": 1,
        "yuguoStudentId": "Y4-9001",
        "status": "CONFIRMED",
        "confirmedAt": "2026-10-22T10:00:00",
        "confirmedBy": {"id": "1", "name": "顾问A"},
        "student": {"name": "测试学生", "grade": "10", "school": "测试中学"},
        "meetingSummary": "访谈日期：2026年10月22日 18:00\n\n本次会议主要围绕兴趣与经历展开。",
        "career": None,
        "interests": [{
            "id": "1", "label": "篮球", "evidence": "每周打篮球",
            "preferenceScore": 3, "competenceScore": 2,
            "quadrant": "非常喜欢 × 擅长",
        }],
        "narrative": "第一段说明。\n\n第二段分析。",
        "suggestions": [{
            "id": "1", "title": "记录比赛", "introduction": "记录一周比赛。",
            "growthValue": "练习复盘。", "possibleOutputs": ["记录表"],
            "interestRefs": ["1"],
        }],
        "sources": [{
            "id": "1", "type": "GROWTH_TALK",
            "createdAt": "2026-10-20T10:00:00",
        }],
        "promptVersions": {"meeting": "v1"},
    }


def _seed_ready_run(qdb):
    source = store.create_source(
        qdb.student_id, "GROWTH_TALK", "GROWTH_TALK", "会谈记录",
        "他说自己每周打篮球，也在学机器人。", purpose="MEETING",
    )
    run = store.create_run(qdb.student_id, source["id"])
    store.save_understanding(
        run["id"], "本次会议主要围绕兴趣与经历展开。他每周打篮球。",
        json.dumps([
            {"label": "篮球", "topicType": "interest", "evidence": "每周打篮球"},
            {"label": "机器人", "topicType": "interest", "evidence": "在学机器人"},
        ], ensure_ascii=False),
        json.dumps([], ensure_ascii=False), "deepseek-chat",
    )
    store.replace_interests(run["id"], [
        {"label": "篮球", "evidence": "每周打篮球", "preference_score": 3,
         "competence_score": 2, "status": "CONFIRMED"},
        {"label": "机器人", "evidence": "在学机器人", "preference_score": 2,
         "competence_score": 1, "status": "CONFIRMED"},
    ])
    full = store.get_run_full(run["id"])
    interest_ids = [item["id"] for item in full["interests"]]
    store.save_quadrant(run["id"], json.dumps([
        {"interestId": interest_ids[0], "preferenceScore": 3, "competenceScore": 2},
        {"interestId": interest_ids[1], "preferenceScore": 2, "competenceScore": 1},
    ], ensure_ascii=False), "第一段说明。\n\n第二段分析。", "deepseek-chat")
    store.replace_suggestions(run["id"], [
        {"title": "篮球观察记录", "introduction": "记录一周比赛中的决策。",
         "growthValue": "练习观察与复盘。", "possibleOutputs": ["记录表"],
         "interestRefs": [interest_ids[0]], "status": "CONFIRMED"},
        {"title": "待确认建议", "introduction": "不收录。", "growthValue": "无。",
         "possibleOutputs": [], "interestRefs": [interest_ids[0]],
         "status": "DRAFT"},
    ])
    career = store.create_source(
        qdb.student_id, "Y4_CAREER_PROFILE", "Y4_CAREER_PROFILE",
        "职业兴趣报告", "职业兴趣报告内容", purpose="CAREER",
    )
    store.set_source_key_points(career["id"], json.dumps({
        "careerInterests": "对工程与动手实践有持续兴趣",
        "abilityTendencies": "空间与逻辑推理表现较稳定",
        "valuePreferences": "重视自主探索与可验证成果",
    }, ensure_ascii=False))
    return run["id"], interest_ids, career["id"]


def test_validate_rejects_non_confirmed():
    payload = _valid_payload()
    payload["status"] = "DRAFT"
    with pytest.raises(ValueError, match="只支持已确认"):
        validate_report(payload)


def test_validate_rejects_bad_score():
    for bad in (4, 1.5, -1, True):
        payload = _valid_payload()
        payload["interests"][0]["preferenceScore"] = bad
        with pytest.raises(ValueError, match="兴趣分值必须为 0–3"):
            validate_report(payload)
    payload = _valid_payload()
    payload["interests"][0]["preferenceScore"] = 2
    assert validate_report(payload) is payload


def test_validate_rejects_orphan_interest_ref():
    payload = _valid_payload()
    payload["suggestions"][0]["interestRefs"] = ["999"]
    with pytest.raises(ValueError, match="建议引用了报告外的兴趣"):
        validate_report(payload)


def test_preview_assembles_confirmed_outputs(qdb):
    run_id, interest_ids, career_id = _seed_ready_run(qdb)
    preview = build_report_preview(run_id)

    assert preview["runId"] == run_id
    assert preview["revision"] == 1
    assert preview["meetingSummary"].startswith("访谈日期：")
    assert preview["fingerprint"]
    assert {item["id"] for item in preview["interests"]} == {
        str(value) for value in interest_ids
    }
    assert all(item["quadrant"] for item in preview["interests"])
    assert len(preview["suggestions"]) == 1
    assert preview["suggestions"][0]["title"] == "篮球观察记录"
    assert preview["careerSourceId"] == career_id
    assert preview["career"]["careerInterests"] == "对工程与动手实践有持续兴趣"


def test_preview_rejects_quadrant_mismatch(qdb):
    run_id, interest_ids, _career_id = _seed_ready_run(qdb)
    store.save_quadrant(
        run_id,
        json.dumps([{
            "interestId": interest_ids[0],
            "preferenceScore": 0, "competenceScore": 0,
        }], ensure_ascii=False),
        "第一段说明。\n\n第二段分析。", "deepseek-chat",
    )
    with pytest.raises(ActionError, match="象限分析与兴趣评分不一致"):
        build_report_preview(run_id)


def test_confirm_fingerprint_mismatch(qdb):
    run_id, _ids, _career_id = _seed_ready_run(qdb)
    preview = build_report_preview(run_id)
    runs.apply_action(run_id, "edit-quadrant-narrative", {
        "expected_revision": preview["revision"],
        "narrative": (
            "他对动手搭建和运动训练都表现出持续的投入，会议中多次主动描述"
            "自己的练习安排与调整过程，说明这些兴趣并非一时兴起。\n\n"
            "两者对比如下：机器人更依赖持续积累与问题拆解，篮球更依赖即时"
            "判断与团队配合，他在两类活动中的表现差异值得在后续会谈中继续"
            "观察。"
        ),
    }, "顾问A")

    with pytest.raises(store.RevisionConflict, match="报告内容已变化"):
        confirm_report(
            run_id,
            reviewed_meeting=True, reviewed_narrative=True,
            suggestion_ids=[item["id"] for item in preview["suggestions"]],
            fingerprint=preview["fingerprint"], confirmed_by="顾问A",
        )


def test_confirm_creates_immutable_versioned_report(qdb):
    run_id, _ids, _career_id = _seed_ready_run(qdb)
    preview = build_report_preview(run_id)
    selected = [item["id"] for item in preview["suggestions"]]

    result = confirm_report(
        run_id,
        reviewed_meeting=True, reviewed_narrative=True,
        suggestion_ids=selected, fingerprint=preview["fingerprint"],
        confirmed_by="顾问A", actor_id=7,
    )
    assert result["version"] == 1
    assert result["confirmedAt"]

    stored = store.get_report(result["id"])
    assert stored["status"] == "CONFIRMED"
    payload = json.loads(stored["payload"])
    assert validate_report(payload) is payload
    assert payload["confirmedBy"] == {"id": "7", "name": "顾问A"}
    assert payload["student"]["grade"] == "10"
    assert len(payload["sources"]) == 2
    assert [item["title"] for item in payload["suggestions"]] == ["篮球观察记录"]
    assert payload["meetingSummary"].startswith("访谈日期：")

    full = store.get_run_full(run_id)
    assert full["understanding"]["status"] == "CONFIRMED"
    assert full["quadrant"]["status"] == "CONFIRMED"
    assert full["revision"] == 2
    with Session(qdb.engine) as sess:
        audit = sess.execute(
            select(store.AuditLog).where(store.AuditLog.action == "report_confirmed")
        ).scalars().all()
    assert len(audit) == 1

    preview2 = build_report_preview(run_id)
    second = confirm_report(
        run_id,
        reviewed_meeting=True, reviewed_narrative=True,
        suggestion_ids=[item["id"] for item in preview2["suggestions"]],
        fingerprint=preview2["fingerprint"], confirmed_by="顾问B",
    )
    assert second["version"] == 2
    assert store.get_report(result["id"])["payload"] == stored["payload"]


def test_confirm_requires_grade(qdb):
    run_id, _ids, _career_id = _seed_ready_run(qdb)
    with Session(qdb.engine) as sess:
        row = sess.get(_db.Student, qdb.student_id)
        row.grade = None
        sess.commit()
    preview = build_report_preview(run_id)
    with pytest.raises(ActionError, match="请先补充年级"):
        confirm_report(
            run_id,
            reviewed_meeting=True, reviewed_narrative=True,
            suggestion_ids=[item["id"] for item in preview["suggestions"]],
            fingerprint=preview["fingerprint"], confirmed_by="顾问A",
        )


def test_confirm_requires_review_flags(qdb):
    run_id, _ids, _career_id = _seed_ready_run(qdb)
    preview = build_report_preview(run_id)
    with pytest.raises(ActionError, match="请完成报告内容复核"):
        confirm_report(
            run_id,
            reviewed_meeting=False, reviewed_narrative=True,
            suggestion_ids=[item["id"] for item in preview["suggestions"]],
            fingerprint=preview["fingerprint"], confirmed_by="顾问A",
        )


def test_confirm_rejects_unconfirmed_suggestions(qdb):
    run_id, _ids, _career_id = _seed_ready_run(qdb)
    preview = build_report_preview(run_id)
    full = store.get_run_full(run_id)
    draft_id = next(
        str(item["id"]) for item in full["suggestions"] if item["status"] == "DRAFT"
    )
    with pytest.raises(ActionError, match="只能收录已确认的建议"):
        confirm_report(
            run_id,
            reviewed_meeting=True, reviewed_narrative=True,
            suggestion_ids=[draft_id], fingerprint=preview["fingerprint"],
            confirmed_by="顾问A",
        )
