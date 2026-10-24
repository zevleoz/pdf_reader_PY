"""Growth Talk 已确认报告下载测试。

Growth Talk 1.0 的分析/上传/审核路由已随工作区下线；本文件只保留下载契约：
- 已确认报告的 PDF / JSON 下载可用，PDF 头符合 RFC 5987；
- 未确认报告视为不存在；
- Advisor 不能下载他人学生的报告。
"""
from __future__ import annotations

import json

import pytest
from flask import Flask
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

import app_utils
import db as _db
import growth_talk_store as store


class RoutesDB:
    """tmp SQLite 上的学生/分析数据工厂。"""

    def __init__(self, engine):
        self.engine = engine
        self.student_id = None
        self.other_student_id = None

    def seed(self):
        with Session(self.engine) as sess:
            mine = _db.Student(student_code="Y4-9001", name="测试学生",
                               grade="10", school="测试中学",
                               advisor_name="Alice")
            other = _db.Student(student_code="Y4-9002", name="其他学生",
                                grade="11", school="另一中学",
                                advisor_name="Bob")
            sess.add_all([mine, other])
            sess.commit()
            self.student_id = mine.id
            self.other_student_id = other.id


@pytest.fixture()
def gdb(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'growth_talk_routes.db'}")

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

    helper = RoutesDB(engine)
    helper.seed()
    yield helper
    engine.dispose()


@pytest.fixture()
def client(gdb, tmp_path, monkeypatch):
    from blueprints import growth_talk as gt_routes

    # 只跳过「会话用户是否仍有效」的检查；角色与 advisor 归属走真实实现。
    monkeypatch.setattr(app_utils, "is_authenticated", lambda: True)
    app = Flask(__name__)
    app.secret_key = "test-secret"
    app.register_blueprint(gt_routes.bp)
    return app.test_client()


def login_as(client, role="admin", advisor_name=None, display_name="顾问A"):
    with client.session_transaction() as sess:
        sess["user_id"] = 1
        sess["role"] = role
        sess["display_name"] = display_name
        if advisor_name is not None:
            sess["advisor_name"] = advisor_name


# ---------------------------------------------------------------------------
# seed helpers
# ---------------------------------------------------------------------------
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


def _seed_ready_run(gdb, *, with_career=True):
    source = store.create_source(
        gdb.student_id, "GROWTH_TALK", "GROWTH_TALK", "会谈记录",
        "他说自己每周打篮球，也在学机器人。", purpose="MEETING",
    )
    run = store.create_run(gdb.student_id, source["id"])
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
    ])
    career_id = None
    if with_career:
        career = store.create_source(
            gdb.student_id, "Y4_CAREER_PROFILE", "Y4_CAREER_PROFILE",
            "职业兴趣报告", "职业兴趣报告内容", purpose="CAREER",
        )
        store.set_source_key_points(career["id"], json.dumps({
            "careerInterests": "对工程与动手实践有持续兴趣",
            "abilityTendencies": "空间与逻辑推理表现较稳定",
            "valuePreferences": "重视自主探索与可验证成果",
        }, ensure_ascii=False))
        career_id = career["id"]
    return run["id"], interest_ids, career_id


# ---------------------------------------------------------------------------
# 下载
# ---------------------------------------------------------------------------
def test_report_download_pdf_headers(client, gdb):
    login_as(client)
    run_id, _ids, _career = _seed_ready_run(gdb)
    report = store.create_report(
        gdb.student_id, run_id,
        json.dumps(_valid_payload(), ensure_ascii=False), "顾问A")

    res = client.get(f"/api/growth-talk/reports/{report['id']}/download.pdf")

    assert res.status_code == 200
    assert res.mimetype == "application/pdf"
    disposition = res.headers["Content-Disposition"]
    assert disposition.startswith("attachment")
    assert "filename*=UTF-8''" in disposition

    res = client.get(f"/api/growth-talk/reports/{report['id']}/download.json")
    assert res.status_code == 200
    assert f"first-touch-{report['id']}-v1.json" in res.headers["Content-Disposition"]
    assert json.loads(res.data.decode("utf-8"))["schema"] == "first-touch.report.v1"


def test_report_download_ignores_unconfirmed(client, gdb):
    login_as(client)
    run_id, _ids, _career = _seed_ready_run(gdb)
    with Session(gdb.engine) as sess:
        row = store.GtReport(
            student_id=gdb.student_id, run_id=run_id, version=1,
            status="DRAFT", payload=json.dumps(_valid_payload()),
        )
        sess.add(row)
        sess.commit()
        report_id = row.id

    assert client.get(
        f"/api/growth-talk/reports/{report_id}/download.pdf").status_code == 404
    assert client.get(
        f"/api/growth-talk/reports/{report_id}/download.json").status_code == 404


def test_advisor_cannot_read_others_report(client, gdb):
    login_as(client, role="advisor", advisor_name="Alice")
    other_source = store.create_source(
        gdb.other_student_id, "GROWTH_TALK", "GROWTH_TALK", "他人会议", "正文",
        purpose="MEETING")
    other_run = store.create_run(gdb.other_student_id, other_source["id"])
    report = store.create_report(
        gdb.other_student_id, other_run["id"],
        json.dumps(_valid_payload(), ensure_ascii=False), "顾问B")

    res = client.get(f"/api/growth-talk/reports/{report['id']}/download.json")
    assert res.status_code == 404
