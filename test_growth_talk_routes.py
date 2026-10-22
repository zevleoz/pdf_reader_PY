"""Growth Talk 会话路由测试（tmp SQLite，不联网）。

覆盖计划 Task 8 钉住的关键不变量：
- 分片上传重发幂等，合并后的资料正文正确；
- 被 run 引用的资料不能删除（409 原文案）；
- 创建分析作业会拉起子进程；
- 过期 revision 的审核动作返回 409，不静默覆盖；
- Advisor 不能访问他人学生（统一 404）；
- 报告 PDF 下载头符合 RFC 5987。
"""
from __future__ import annotations

import io
import json

import pytest
from flask import Flask
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

import app_utils
import db as _db
import growth_talk_store as store
from growth_talk import jobs


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
    monkeypatch.setattr(gt_routes, "GT_UPLOAD_DIR", tmp_path / "gt_uploads")
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
_NARRATIVE = (
    "在篮球和机器人两件事上，投入方式并不相同。篮球更多来自持续的兴趣和身体经验，"
    "机器人则更依赖结构化的学习与动手尝试。\n\n"
    "两件事在偏好与胜任上的组合并不完全一致，因此可以分别围绕课堂内外的真实投入、"
    "遇到困难时的坚持程度，以及完成任务后的复盘习惯继续观察。"
)


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
# 上传 / 资料
# ---------------------------------------------------------------------------
def test_upload_chunk_idempotent(client, gdb, tmp_path):
    login_as(client)

    for _ in range(2):
        res = client.post(
            "/api/growth-talk/upload/chunk",
            data={"upload_id": "u-1", "index": "0", "total": "1",
                  "file": (io.BytesIO("会议正文".encode("utf-8")), "meeting.txt")},
            content_type="multipart/form-data",
        )
        assert res.status_code == 200, res.get_json()

    parts = list((tmp_path / "gt_uploads" / "u-1").glob("*.part"))
    assert len(parts) == 1

    res = client.post(
        f"/api/students/{gdb.student_id}/growth-talk/sources",
        json={"upload_id": "u-1", "file_name": "meeting.txt",
              "source_kind": "GROWTH_TALK"},
    )
    assert res.status_code == 201, res.get_json()
    body = res.get_json()
    assert body["content"] == "会议正文"
    assert body["purpose"] == "MEETING"
    assert body["type"] == "GROWTH_TALK"


def test_source_create_then_delete_blocked_when_referenced(client, gdb):
    login_as(client)

    res = client.post(
        f"/api/students/{gdb.student_id}/growth-talk/sources",
        json={"text": "每周打篮球。", "title": "会谈记录",
              "source_kind": "GROWTH_TALK"},
    )
    assert res.status_code == 201, res.get_json()
    source = res.get_json()
    store.create_run(gdb.student_id, source["id"])

    res = client.delete(f"/api/growth-talk/sources/{source['id']}")
    assert res.status_code == 409
    assert res.get_json()["error"] == "资料已被历史分析或确认报告引用，不能删除"

    res = client.post(
        f"/api/students/{gdb.student_id}/growth-talk/sources",
        json={"text": "第二份资料。", "title": "第二份",
              "source_kind": "Y4_CAREER_PROFILE"},
    )
    assert res.status_code == 201, res.get_json()
    unused = res.get_json()["id"]
    assert client.delete(f"/api/growth-talk/sources/{unused}").status_code == 200


def test_source_rejects_y4_json(client, gdb):
    login_as(client)

    res = client.post(
        f"/api/students/{gdb.student_id}/growth-talk/sources",
        json={"upload_id": "missing", "file_name": "career.json",
              "source_kind": "Y4_CAREER_PROFILE"},
    )
    assert res.status_code == 400
    assert res.get_json()["error"] == "职业兴趣资料不支持 JSON"


def test_sources_list_and_get(client, gdb):
    login_as(client)
    source = store.create_source(
        gdb.student_id, "GROWTH_TALK", "GROWTH_TALK", "会谈记录", "正文",
        purpose="MEETING")

    res = client.get(f"/api/students/{gdb.student_id}/growth-talk/sources")
    assert res.status_code == 200
    assert [item["id"] for item in res.get_json()["sources"]] == [source["id"]]

    res = client.get(f"/api/growth-talk/sources/{source['id']}")
    assert res.status_code == 200
    assert res.get_json()["source"]["title"] == "会谈记录"


# ---------------------------------------------------------------------------
# 作业 / run
# ---------------------------------------------------------------------------
def test_run_create_launches_subprocess(client, gdb, monkeypatch):
    login_as(client)
    source = store.create_source(
        gdb.student_id, "GROWTH_TALK", "GROWTH_TALK", "会议", "正文",
        purpose="MEETING")
    calls = []
    monkeypatch.setattr(jobs, "launch_analysis", lambda run_id: calls.append(run_id))

    res = client.post(f"/api/students/{gdb.student_id}/growth-talk/runs", json={})

    assert res.status_code == 201, res.get_json()
    run_id = res.get_json()["run_id"]
    assert run_id == res.get_json()["runId"]
    assert calls == [run_id]
    assert store.get_run(run_id)["source_id"] == source["id"]


def test_run_create_rejects_stale_source(client, gdb, monkeypatch):
    login_as(client)
    old = store.create_source(
        gdb.student_id, "GROWTH_TALK", "GROWTH_TALK", "旧会议", "旧正文",
        purpose="MEETING")
    store.create_source(
        gdb.student_id, "GROWTH_TALK", "GROWTH_TALK", "新会议", "新正文",
        purpose="MEETING")
    calls = []
    monkeypatch.setattr(jobs, "launch_analysis", lambda run_id: calls.append(run_id))

    res = client.post(f"/api/students/{gdb.student_id}/growth-talk/runs",
                      json={"source_id": old["id"]})
    assert res.status_code == 409
    assert res.get_json()["error"] == "请使用当前会议资料"
    assert calls == []


def test_job_status_falls_back_to_run(client, gdb):
    login_as(client)
    source = store.create_source(
        gdb.student_id, "GROWTH_TALK", "GROWTH_TALK", "会议", "正文",
        purpose="MEETING")
    run = store.create_run(gdb.student_id, source["id"])
    store.set_run_status(run["id"], "PENDING_REVIEW")

    res = client.get(f"/api/growth-talk/jobs/{run['id']}")

    assert res.status_code == 200
    body = res.get_json()
    assert body["status"] == "done"
    assert body["runStatus"] == "PENDING_REVIEW"


# ---------------------------------------------------------------------------
# 审核动作 / 预览 / 确认
# ---------------------------------------------------------------------------
def test_put_action_revision_conflict_409(client, gdb):
    login_as(client)
    run_id, _ids, _career = _seed_ready_run(gdb)
    store.bump_run_revision(run_id, 1)

    res = client.put(f"/api/growth-talk/runs/{run_id}", json={
        "action": "edit-quadrant-narrative",
        "expected_revision": 1,
        "narrative": _NARRATIVE,
    })

    assert res.status_code == 409
    assert res.get_json()["error"] == "内容已更新，请刷新后重试"


def test_put_action_applies_with_current_revision(client, gdb):
    login_as(client)
    run_id, _ids, _career = _seed_ready_run(gdb)

    res = client.put(f"/api/growth-talk/runs/{run_id}", json={
        "action": "edit-quadrant-narrative",
        "expected_revision": 1,
        "narrative": _NARRATIVE,
    })

    assert res.status_code == 200, res.get_json()
    assert res.get_json()["revision"] == 2
    assert store.get_run_full(run_id)["quadrant"]["narrative"] == _NARRATIVE


def test_preview_and_confirm_report(client, gdb):
    login_as(client)
    run_id, interest_ids, _career = _seed_ready_run(gdb)

    preview = client.post(f"/api/growth-talk/runs/{run_id}/preview-report")
    assert preview.status_code == 200, preview.get_json()
    body = preview.get_json()
    assert body["runId"] == run_id
    assert body["fingerprint"]

    res = client.post(f"/api/growth-talk/runs/{run_id}/report", json={
        "reviewedMeeting": True,
        "reviewedNarrative": True,
        "suggestionIds": [item["id"] for item in body["suggestions"]],
        "fingerprint": body["fingerprint"],
    })

    assert res.status_code == 201, res.get_json()
    assert res.get_json()["version"] == 1
    assert store.get_report(res.get_json()["id"])["status"] == "CONFIRMED"


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


# ---------------------------------------------------------------------------
# Copilot / 职业分析
# ---------------------------------------------------------------------------
def test_copilot_requires_sources_and_question(client, gdb):
    login_as(client)
    run_id, _ids, career_id = _seed_ready_run(gdb)

    res = client.post(f"/api/growth-talk/runs/{run_id}/copilot",
                      json={"question": "  "})
    assert res.status_code == 422
    assert "1000" in res.get_json()["error"]

    store.delete_source(career_id)
    res = client.post(f"/api/growth-talk/runs/{run_id}/copilot",
                      json={"question": "下一步做什么？"})
    assert res.status_code == 409
    assert res.get_json()["error"] == "请先上传会议纪要和 Y4 职业兴趣画像报告"


def test_copilot_returns_answer_and_audits(client, gdb, monkeypatch):
    login_as(client)
    run_id, _ids, _career = _seed_ready_run(gdb)
    from growth_talk import analysis

    monkeypatch.setattr(
        analysis, "ask_growth_talk_copilot",
        lambda question, context: {"answer": "先记录一周比赛。", "evidence": []})

    res = client.post(f"/api/growth-talk/runs/{run_id}/copilot",
                      json={"question": "下一步做什么？"})

    assert res.status_code == 200, res.get_json()
    assert res.get_json()["answer"] == "先记录一周比赛。"
    audit = store.list_audit(gdb.student_id, action="growth_talk_copilot_asked")
    assert audit and audit[0]["details"]


def test_career_analysis_uses_latest_source(client, gdb):
    login_as(client)
    old = store.create_source(
        gdb.student_id, "Y4_CAREER_PROFILE", "Y4_CAREER_PROFILE",
        "旧画像", "旧内容", purpose="CAREER")
    store.create_source(
        gdb.student_id, "Y4_CAREER_PROFILE", "Y4_CAREER_PROFILE",
        "新画像", "新内容", purpose="CAREER")

    res = client.post(
        f"/api/students/{gdb.student_id}/growth-talk/career-analysis",
        json={"source_id": old["id"]},
    )

    assert res.status_code == 409
    assert res.get_json()["error"] == "请使用当前职业兴趣报告"


# ---------------------------------------------------------------------------
# Advisor 隔离
# ---------------------------------------------------------------------------
def test_advisor_cannot_touch_others_student(client, gdb):
    login_as(client, role="advisor", advisor_name="Alice")
    other_source = store.create_source(
        gdb.other_student_id, "GROWTH_TALK", "GROWTH_TALK", "他人会议", "正文",
        purpose="MEETING")
    other_run = store.create_run(gdb.other_student_id, other_source["id"])

    assert client.get(
        f"/api/students/{gdb.other_student_id}/growth-talk/runs").status_code == 404
    assert client.post(
        f"/api/students/{gdb.other_student_id}/growth-talk/runs", json={}
    ).status_code == 404
    assert client.get(
        f"/api/growth-talk/sources/{other_source['id']}").status_code == 404
    assert client.get(
        f"/api/growth-talk/jobs/{other_run['id']}").status_code == 404


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
