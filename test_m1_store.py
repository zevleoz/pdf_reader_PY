"""M1 数据层测试：建表、权限、资料上传、问卷状态、版本并发与定稿。"""
from __future__ import annotations

import io
import json
from datetime import date
from pathlib import Path

import fitz
import pytest
from docx import Document
from sqlalchemy import create_engine, event, inspect, select
from sqlalchemy.orm import Session

import db as _db
import growth_talk_store as _gt
import m1.sources as sources
import m1.store as store
import questionnaire_store as qs
from app_utils import BASE_DIR


class M1DB:
    def __init__(self, engine):
        self.engine = engine
        self.alice_id = None
        self.bob_id = None
        self.admin_id = None
        self.viewer_id = None
        self.student_id = None
        self.other_student_id = None
        self.incomplete_student_id = None

    def user(self, role, advisor_name, username=None):
        with Session(self.engine) as sess:
            row = _db.User(username=username or f"{role}-{advisor_name}",
                           password_hash="x", role=role,
                           advisor_name=advisor_name, display_name=advisor_name)
            sess.add(row)
            sess.commit()
            return row.id

    def seed(self):
        with Session(self.engine) as sess:
            mine = _db.Student(student_code="Y4-8001", name="林晓雨",
                               grade="初二", school="示例中学", advisor_name="Alice")
            other = _db.Student(student_code="Y4-8002", name="陈一鸣",
                                grade="初三", school="示例中学", advisor_name="Bob")
            third = _db.Student(student_code="Y4-8003", name="吴子涵",
                                grade="初一", school="示例中学", advisor_name="Alice")
            sess.add_all([mine, other, third])
            sess.commit()
            self.student_id, self.other_student_id, self.incomplete_student_id = (
                mine.id, other.id, third.id)
        self.alice_id = self.user("advisor", "Alice", "alice")
        self.bob_id = self.user("advisor", "Bob", "bob")
        self.admin_id = self.user("admin", "", "admin")
        self.viewer_id = self.user("viewer", "", "viewer")
        self.add_y4(self.student_id, complete=True)
        self.add_y4(self.other_student_id, complete=True)

    def add_y4(self, student_id, complete=True):
        points = [{"code": "072", "value": "SAE", "type": "string"}]
        if complete:
            points += [{"code": code, "value": value, "type": "number"}
                       for code, value in (("073", "2"), ("074", "5"),
                                           ("075", "2"), ("076", "4"),
                                           ("077", "1"), ("078", "3"))]
        with Session(self.engine) as sess:
            sess.add(_db.Report(
                student_id=student_id, report_date=date(2026, 9, 2),
                pdf_path="report.pdf",
                data_json=json.dumps({"schema_124": points}, ensure_ascii=False)))
            sess.commit()

    def prep(self, student_id=None, mentor_user_id=None):
        return store.create_prep(student_id or self.student_id,
                                 created_by=mentor_user_id or self.alice_id,
                                 mentor_user_id=mentor_user_id or self.alice_id)


@pytest.fixture()
def m1db(tmp_path, monkeypatch):
    path = tmp_path / "m1_store.db"
    engine = create_engine(f"sqlite:///{path}")

    @event.listens_for(engine, "connect")
    def _enable_fk(dbapi_connection, _record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    tables = [
        _db.Student.__table__, _db.User.__table__, _db.Report.__table__,
        store.M1Prep.__table__, store.M1Source.__table__, store.M1Version.__table__,
        _gt.AuditLog.__table__,
        _gt.CopilotSession.__table__, _gt.CopilotPhaseEvent.__table__,
        _gt.CopilotCareerCalibration.__table__, _gt.CopilotInterestNote.__table__,
        _gt.CopilotTranscriptSupplement.__table__,
        qs.Questionnaire.__table__, qs.Assignment.__table__,
        qs.AssignmentToken.__table__, qs.Response.__table__,
        qs.ResponseDraft.__table__,
    ]
    _db.Base.metadata.create_all(engine, tables=tables)
    monkeypatch.setattr(_db, "engine", engine)
    monkeypatch.setattr(qs, "engine", engine)
    monkeypatch.setattr(sources, "UPLOAD_ROOT", tmp_path / "m1_uploads")

    helper = M1DB(engine)
    helper.seed()
    yield helper
    engine.dispose()


def _user(db, role, advisor_name="", user_id=None):
    return {"user_id": user_id, "role": role, "advisor_name": advisor_name,
            "display_name": advisor_name}


# ---------------------------------------------------------------------------
# 建表
# ---------------------------------------------------------------------------
def test_tables_created(m1db):
    names = set(inspect(m1db.engine).get_table_names())
    assert {"m1_preps", "m1_sources", "m1_versions"} <= names


# ---------------------------------------------------------------------------
# can_access
# ---------------------------------------------------------------------------
def test_admin_sees_everything(m1db):
    admin = _user(m1db, "admin", user_id=m1db.admin_id)
    assert store.can_access_student(admin, m1db.other_student_id)
    prep = m1db.prep(m1db.other_student_id, m1db.bob_id)
    assert store.can_access_prep(admin, prep["id"])
    assert store.can_access(admin, prep)


def test_advisor_sees_own_students_and_mentored_preps(m1db):
    alice = _user(m1db, "advisor", "Alice", m1db.alice_id)
    assert store.can_access_student(alice, m1db.student_id)
    assert not store.can_access_student(alice, m1db.other_student_id)

    own = m1db.prep(m1db.student_id, m1db.alice_id)
    assert store.can_access_prep(alice, own["id"])

    # 别人的学生，但本人是这次准备的 Mentor → 可见
    mentored = m1db.prep(m1db.other_student_id, m1db.alice_id)
    assert store.can_access_prep(alice, mentored["id"])

    others = m1db.prep(m1db.other_student_id, m1db.bob_id)
    assert not store.can_access_prep(alice, others["id"])


def test_other_advisor_and_viewer_denied(m1db):
    bob = _user(m1db, "advisor", "Bob", m1db.bob_id)
    viewer = _user(m1db, "viewer", "", m1db.viewer_id)
    prep = m1db.prep(m1db.student_id, m1db.alice_id)
    assert not store.can_access_prep(bob, prep["id"])
    assert not store.can_access_prep(viewer, prep["id"])
    assert not store.can_access_student(viewer, m1db.student_id)


# ---------------------------------------------------------------------------
# 上传
# ---------------------------------------------------------------------------
def _docx_bytes(text: str) -> bytes:
    document = Document()
    document.add_paragraph(text)
    buf = io.BytesIO()
    document.save(buf)
    return buf.getvalue()


def _pdf_bytes(text: str) -> bytes:
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), text)
    return document.tobytes()


def test_upload_txt(m1db):
    prep = m1db.prep()
    body = ("2026-10-20 Case Review 会议记录。参与：田老师、王老师。"
            "课堂观察一条：答错后整节课低头不说话。团队假设两条。")
    row = sources.add_upload(prep["id"], "2026-10-20 Case Review.txt",
                             body.encode(), "case_review", _user(m1db, "admin"))
    assert "课堂观察" in row["text"]
    assert row["detected_date"] == "2026-10-20"
    assert row["status"] == "ok"
    assert row["category"] == "case_review"
    stored = Path(row["stored_path"])
    assert stored.exists()
    assert stored.read_bytes() == body.encode()


def test_upload_docx_and_pdf(m1db):
    prep = m1db.prep()
    docx = sources.add_upload(prep["id"], "家长反馈.docx",
                              _docx_bytes("家长反馈：期中后情绪低落，回家不怎么说话。" * 3),
                              "parent", _user(m1db, "admin"))
    assert "期中后情绪低落" in docx["text"]

    pdf = sources.add_upload(prep["id"], "课堂观察.pdf",
                             _pdf_bytes("Classroom observation: silent after a wrong answer."),
                             "other", _user(m1db, "admin"))
    assert "Classroom observation" in pdf["text"]


def test_upload_empty_file_is_400(m1db):
    prep = m1db.prep()
    with pytest.raises(sources.UploadError) as error:
        sources.add_upload(prep["id"], "empty.txt", b"", "other",
                           _user(m1db, "admin"))
    assert error.value.status == 400


def test_uploads_live_outside_static(m1db):
    prep = m1db.prep()
    row = sources.add_upload(prep["id"], "note.txt", "会议时间：2026年11月3日".encode(),
                             "other", _user(m1db, "admin"))
    stored = Path(row["stored_path"]).resolve()
    static = (BASE_DIR / "static").resolve()
    assert static not in stored.parents
    assert row["suggested_meeting_date"] == "2026-11-03"
    # 会议日期只作为提示返回，不写回 prep
    assert store.get_prep(prep["id"])["meeting_date"] == ""


def test_add_text_and_update_delete(m1db):
    prep = m1db.prep()
    row = sources.add_text(prep["id"], "妈妈 10 月 9 日微信反馈：考差会说自己笨。"
                          "孩子回家不怎么说话，我们报了数学补习班但效果不明显。",
                          "parent", _user(m1db, "admin"))
    assert row["detected_date"].endswith("-10-09")
    updated = store.update_source(row["id"], category="other",
                                  detected_date="2026-10-10")
    assert updated["category"] == "other"
    assert updated["detected_date"] == "2026-10-10"
    store.delete_source(row["id"])
    assert store.list_sources(prep["id"]) == []


# ---------------------------------------------------------------------------
# 补充问卷状态
# ---------------------------------------------------------------------------
def _questionnaire(db, code, title, questions):
    with Session(db.engine) as sess:
        row = qs.Questionnaire(
            code=code, title=title, is_active=1,
            schema_json=json.dumps({"version": 1, "questions": questions},
                                   ensure_ascii=False))
        sess.add(row)
        sess.commit()
        return row.id


def _assignment(db, qid, student_id, status):
    with Session(db.engine) as sess:
        row = qs.Assignment(student_id=student_id, questionnaire_id=qid,
                            status=status, source="auto")
        sess.add(row)
        sess.commit()
        return row.id


def test_questionnaire_status_mapping(m1db):
    done_qid = _questionnaire(m1db, "ERQ", "情绪调节问卷", [
        {"id": "q1", "type": "single", "title": "我会改变想法", "dimension": "认知重评",
         "options": [{"value": "1", "label": "不赞同"}, {"value": "5", "label": "赞同"}]},
        {"id": "q2", "type": "single", "title": "我会隐藏情绪", "dimension": "表达抑制",
         "options": [{"value": "1", "label": "不赞同"}, {"value": "5", "label": "赞同"}]},
    ])
    sent_qid = _questionnaire(m1db, "ANX", "焦虑问卷", [
        {"id": "a1", "type": "scale", "title": "最近感到紧张", "dimension": "焦虑",
         "scale": {"min": 1, "max": 5}}])
    _questionnaire(m1db, "SOC", "社交能力问卷", [
        {"id": "s1", "type": "scale", "title": "容易交到朋友", "dimension": "社交",
         "scale": {"min": 1, "max": 5}}])

    done_aid = _assignment(m1db, done_qid, m1db.student_id, "submitted")
    _assignment(m1db, sent_qid, m1db.student_id, "sent")
    with Session(m1db.engine) as sess:
        sess.add(qs.Response(
            assignment_id=done_aid, student_id=m1db.student_id,
            questionnaire_id=done_qid, submitted_via="link",
            answers_json=json.dumps({"q1": "5", "q2": "1"}, ensure_ascii=False)))
        sess.commit()

    rows = {row["code"]: row for row in sources.auto_sources(m1db.student_id)["questionnaires"]}
    assert rows["ERQ"]["status"] == "已完成"
    assert rows["ERQ"]["by_dimension"]["认知重评"][0]["answer"] == "赞同"
    assert rows["ERQ"]["by_dimension"]["表达抑制"][0]["answer"] == "不赞同"
    assert rows["ANX"]["status"] == "未取得"
    assert rows["SOC"]["status"] == "未触发"


# ---------------------------------------------------------------------------
# rev / 定稿 / 重新打开
# ---------------------------------------------------------------------------
def _doc(text="AI 初稿", safety=None):
    block = {"id": "b1", "text": text, "origin": "ai", "ai_text": text}
    return {"meta": {"student": "林晓雨"}, "sources": [],
            "dims": [], "priority": [], "special": {}, "events": [],
            "backups": [], "growth": {}, "appendix": [],
            "flags": {"safety": safety or [], "insufficient": []},
            "_block": block}


def test_rev_conflict_returns_server_doc(m1db):
    prep = m1db.prep()
    first = store.save_doc(prep["id"], prep["rev"], _doc("第一版"))
    assert first["rev"] == prep["rev"] + 1
    store.save_doc(prep["id"], first["rev"], _doc("第二版"))

    with pytest.raises(store.RevConflict) as error:
        store.save_doc(prep["id"], first["rev"], _doc("过期写入"))
    assert error.value.rev == first["rev"] + 1
    assert error.value.doc["_block"]["text"] == "第二版"


def test_finalize_blocked_until_safety_ack(m1db):
    prep = m1db.prep()
    saved = store.save_doc(prep["id"], prep["rev"],
                           _doc(safety=[{"text": "说过不想活了", "source_ref": "m1_source:1"}]))
    with pytest.raises(store.FinalizeBlocked):
        store.finalize_prep(prep["id"], m1db.alice_id)
    assert store.get_prep(prep["id"])["status"] == "draft"

    store.ack_safety(prep["id"], m1db.alice_id)
    final = store.finalize_prep(prep["id"], m1db.alice_id)
    assert final["kind"] == "final"
    assert final["reviewed_at"]
    assert store.get_prep(prep["id"])["status"] == "final"
    assert saved["rev"] == prep["rev"] + 1


def test_reopen_keeps_final_unchanged(m1db):
    prep = m1db.prep()
    store.save_doc(prep["id"], prep["rev"], _doc("定稿内容"))
    final = store.finalize_prep(prep["id"], m1db.alice_id)

    edit = store.reopen_prep(prep["id"], m1db.alice_id)
    assert edit["kind"] == "edit"
    assert edit["n"] > final["n"]
    assert edit["doc"]["_block"]["text"] == "定稿内容"

    # 改草稿不影响 final 行
    store.save_doc(prep["id"], store.get_prep(prep["id"])["rev"], _doc("改过的草稿"))
    stored_final = store.get_version(final["id"])
    assert stored_final["doc"]["_block"]["text"] == "定稿内容"
    assert store.get_prep(prep["id"])["status"] == "review"


def test_audit_writes_existing_table(m1db):
    prep = m1db.prep()
    store.audit(m1db.alice_id, m1db.student_id, "m1.create", {"prep_id": prep["id"]})
    with Session(m1db.engine) as sess:
        rows = sess.execute(select(_gt.AuditLog)).scalars().all()
    assert rows and rows[-1].action == "m1.create"


# ---------------------------------------------------------------------------
# 学生清单
# ---------------------------------------------------------------------------
def test_list_students_marks_incomplete_y4(m1db):
    rows = {row["name"]: row for row in store.list_students(_user(m1db, "admin"))}
    assert rows["林晓雨"]["y4_complete"] is True
    assert rows["吴子涵"]["y4_complete"] is False
    assert rows["吴子涵"]["reason"] == "Y4 尚未完成"

    alice = {row["name"] for row in store.list_students(
        _user(m1db, "advisor", "Alice", m1db.alice_id))}
    assert alice == {"林晓雨", "吴子涵"}


def test_advisor_without_name_owns_no_unassigned_student(m1db):
    from m1 import store as _store
    from sqlalchemy.orm import Session
    import db as _db
    with Session(_db.engine) as sess:
        orphan = _db.Student(student_code="Y4-9999", name="无顾问", grade="初一", advisor_name="")
        sess.add(orphan); sess.commit(); sid = orphan.id
    nameless = {"user_id": 77, "role": "advisor", "advisor_name": ""}
    assert _store.can_access_student(nameless, sid) is False
    assert _store.list_students(nameless) == []
