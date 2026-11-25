# -*- coding: utf-8 -*-
"""任务 N 验收：6AM PDF 独立导出与取件链路。

覆盖：状态机（待生成 / 生成中 / 就绪 / 失败重试 / 内容过期）、同版本去重、
并发锁、中文与分页、跨学生隔离、只读账号权限。

运行：python3 -m pytest test_six_am_pdf.py -q
"""

import datetime as _dt
import json
import os
import shutil
import sys
import tempfile
import time
import unittest

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

from flask import Flask  # noqa: E402
from sqlalchemy import create_engine, event  # noqa: E402

import app_utils  # noqa: E402
import db  # noqa: E402
from blueprints.students import bp as students_bp  # noqa: E402

_ORIG = {}
_USER_IDS = {}
_PDF_DIR = None
_SEQ = [0]


def _profile(name, grade, *, version=1, extra_questions=0):
    questions = [
        {"id": "A1.%d" % i, "ask": "关于 %s 的第 %d 个追问：最近一次自己安排学习是什么时候？" % (name, i),
         "priority": 1, "basis_rules": ["R1.2"]}
        for i in range(extra_questions)
    ]
    return {
        "schema": "6am.v0.6",
        "report_id": 1,
        "generated_at": "2026-11-20 10:00",
        "version": version,
        "rule_version": {"id": 7, "label": "v0.6-published", "status": "published"},
        "student": {"name": name, "grade": grade},
        "dimensions": {
            "A1": {"state": "At-Risk", "confidence": "Hypothesis", "level": "风险",
                   "evidence": ["Y4 A1 自主性偏低"], "hypotheses": ["家长全程安排"],
                   "next_actions": ["把一个小决定交给学生"], "avoid_actions": ["替学生做计划"]},
            "A2": {"state": "Watch", "confidence": "Supported", "level": "关注"},
            "A3": {"state": "Secure", "level": "稳固"},
            "A4": {"state": "Watch", "level": "关注"},
            "A5": {"state": "Secure", "level": "稳固"},
            "A6": {"support_ranking": {"ranked": [{"name": "可视化任务板", "top": True,
                                                   "why": ["降低启动成本"]}], "avoid": []}},
        },
        "obstacles": [{"dim": "A1", "state": "At-Risk", "priority_reason": "先解决启动意愿"}],
        "priority_order": ["A1", "A2", "A4"],
        "deferred": [{"dim": "A4", "reason": "先稳住启动"}],
        "questions": questions or [{"id": "A1.1", "ask": "最近一次自己做决定是什么时候？",
                                    "priority": 1, "basis_rules": ["R1.2"]}],
        "answers": [{"q": "A1.1", "result": "confirm", "text": "几乎都由家长安排"}],
        "gaps": {"family_complaint": {"text": "不想学"}},
    }


def setUpModule():
    global _PDF_DIR
    import questionnaire_store
    tmp_dir = tempfile.mkdtemp(prefix="six_am_pdf_test_")
    _PDF_DIR = os.path.join(tmp_dir, "pdfs")
    os.environ["SIX_AM_PDF_DIR"] = _PDF_DIR
    url = "sqlite:///%s" % os.path.join(tmp_dir, "test.db")
    engine = create_engine(url, connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _enable_fk(dbapi_connection, _record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    _ORIG.update(tmp_dir=tmp_dir, url=db.DATABASE_URL, engine=db.engine,
                 q_engine=questionnaire_store.engine)
    db.engine = engine
    db.DATABASE_URL = url
    questionnaire_store.engine = engine
    assert os.path.realpath(engine.url.database) != os.path.realpath(str(db.DEFAULT_DB))
    db.init_db()
    for key, role, advisor, scope in (
        ("admin", "admin", "", None),
        ("viewer", "viewer", "", None),
        ("front", "advisor", "", "none"),
    ):
        _USER_IDS[key] = db.create_user("t_" + key, "x" * 12, role, advisor_name=advisor,
                                        display_name="用户" + key, student_scope=scope)
    app_utils._SESSION_USER_CACHE.clear()


def tearDownModule():
    import questionnaire_store
    app_utils._SESSION_USER_CACHE.clear()
    os.environ.pop("SIX_AM_PDF_DIR", None)
    db.engine.dispose()
    db.engine = _ORIG["engine"]
    db.DATABASE_URL = _ORIG["url"]
    questionnaire_store.engine = _ORIG["q_engine"]
    shutil.rmtree(_ORIG["tmp_dir"], ignore_errors=True)


def _make_app():
    app = Flask(__name__)
    app.secret_key = "test-secret"
    app.register_blueprint(students_bp)
    return app


def _login(client, role="admin"):
    with client.session_transaction() as sess:
        sess["user_id"] = _USER_IDS[role]
        sess["role"] = role
        sess["advisor_name"] = ""
        sess["display_name"] = "用户" + role


def _new_student(name):
    sid = db.find_or_create_student(name=name, grade="高二", advisor_name="")
    st = db.get_student(sid)
    st["code"] = st["student_code"]
    rid = db.add_report(sid, _dt.date(2026, 11, 18), "report.pdf",
                        json.dumps({"student": {"name": name}, "schema_124": []}, ensure_ascii=False))
    return st, rid


class _Base(unittest.TestCase):
    def setUp(self):
        self.app = _make_app()
        self.client = self.app.test_client()
        _login(self.client, "admin")

    def _student(self, prefix="验收学生"):
        _SEQ[0] += 1
        name = "%s%03d" % (prefix, _SEQ[0])
        st, rid = _new_student(name)
        pid = db.add_six_am_profile(st["id"], rid, json.dumps(
            {**_profile(name, "高二"), "report_id": rid}, ensure_ascii=False), version=1)
        return st, rid, pid

    def _status(self, code):
        resp = self.client.get("/students/%s/api/six-am/pdf-status" % code)
        self.assertEqual(resp.status_code, 200, resp.get_data(as_text=True))
        return resp.get_json()["items"]

    def _generate(self, code, pid):
        resp = self.client.post("/students/%s/api/six-am/%d/pdf" % (code, pid))
        self.assertEqual(resp.status_code, 200, resp.get_data(as_text=True))
        return resp.get_json()["item"]


class Export(_Base):
    def test_missing_then_generate_preview_download_same_bytes(self):
        st, rid, pid = self._student()
        code = st["code"]

        items = self._status(code)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["state"], "missing")
        self.assertEqual(items[0]["version"], 1)
        self.assertEqual(items[0]["report_date"], "2026-11-18")

        self.assertEqual(self.client.get("/students/%s/api/six-am/%d/pdf/file" % (code, pid)).status_code, 404)

        item = self._generate(code, pid)
        self.assertEqual(item["state"], "ready")
        self.assertGreater(item["size"], 1000)

        again = self._generate(code, pid)
        self.assertEqual(again["state"], "ready")
        self.assertEqual(again["size"], item["size"])
        self.assertEqual(again["generated_at"], item["generated_at"])

        preview = self.client.get("/students/%s/api/six-am/%d/pdf/file" % (code, pid))
        self.assertEqual(preview.status_code, 200)
        self.assertEqual(preview.mimetype, "application/pdf")
        self.assertTrue(preview.data.startswith(b"%PDF"))
        self.assertIn("inline", preview.headers["Content-Disposition"])

        download = self.client.get("/students/%s/api/six-am/%d/pdf/file?download=1" % (code, pid))
        self.assertEqual(download.status_code, 200)
        self.assertIn("attachment", download.headers["Content-Disposition"])
        self.assertEqual(download.data, preview.data)
        self.assertIn("UTF-8''", download.headers["Content-Disposition"])

    def test_two_versions_are_independent_artifacts(self):
        st, rid, pid1 = self._student()
        pid2 = db.add_six_am_profile(st["id"], rid, json.dumps(
            {**_profile(st["name"], "高二", version=2), "report_id": rid,
             "answers": []}, ensure_ascii=False), version=2)
        a = self._generate(st["code"], pid1)
        b = self._generate(st["code"], pid2)
        self.assertEqual((a["version"], b["version"]), (1, 2))
        f1 = self.client.get("/students/%s/api/six-am/%d/pdf/file" % (st["code"], pid1)).data
        f2 = self.client.get("/students/%s/api/six-am/%d/pdf/file" % (st["code"], pid2)).data
        self.assertNotEqual(f1, f2)

    def test_stale_after_in_place_edit_requires_regenerate(self):
        st, rid, pid = self._student()
        self._generate(st["code"], pid)
        changed = {**_profile(st["name"], "高二"), "report_id": rid, "answers": []}
        db.update_six_am_profile_json(pid, json.dumps(changed, ensure_ascii=False))

        items = self._status(st["code"])
        self.assertEqual(items[0]["state"], "stale")
        resp = self.client.get("/students/%s/api/six-am/%d/pdf/file" % (st["code"], pid))
        self.assertEqual(resp.status_code, 409)

        item = self._generate(st["code"], pid)
        self.assertEqual(item["state"], "ready")

    def test_failure_is_recorded_and_retryable(self):
        st, rid, pid = self._student()
        from six_am import render_pdf
        original = render_pdf.build_six_am_pdf
        render_pdf.build_six_am_pdf = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("渲染失败"))
        try:
            item = self._generate(st["code"], pid)
        finally:
            render_pdf.build_six_am_pdf = original
        self.assertEqual(item["state"], "failed")
        self.assertIn("渲染失败", item["error"])
        self.assertEqual(self._status(st["code"])[0]["state"], "failed")
        self.assertEqual(self.client.get("/students/%s/api/six-am/%d/pdf/file" % (st["code"], pid)).status_code, 404)

        item = self._generate(st["code"], pid)
        self.assertEqual(item["state"], "ready")

    def test_concurrent_generation_reports_running(self):
        st, rid, pid = self._student()
        from six_am import pdf_store
        from pathlib import Path
        lock = pdf_store._lock_path(Path(_PDF_DIR), st["id"], pid)
        lock.parent.mkdir(parents=True, exist_ok=True)
        lock.write_text("99999 0")
        try:
            item = self._generate(st["code"], pid)
            self.assertEqual(item["state"], "running")
            self.assertEqual(self._status(st["code"])[0]["state"], "running")
        finally:
            lock.unlink()

        item = self._generate(st["code"], pid)
        self.assertEqual(item["state"], "ready")

    def test_student_without_profiles_has_empty_status(self):
        _SEQ[0] += 1
        st, _ = _new_student("无档案学生%03d" % _SEQ[0])
        self.assertEqual(self._status(st["code"]), [])
        self.assertEqual(self.client.get("/students/%s/api/six-am/pdf-status" % st["code"]).status_code, 200)

    def test_cross_student_profile_is_404(self):
        st1, _, pid1 = self._student("甲")
        st2, _, pid2 = self._student("乙")
        self.assertEqual(self.client.get("/students/%s/api/six-am/%d/pdf/file" % (st1["code"], pid2)).status_code, 404)
        resp = self.client.post("/students/%s/api/six-am/%d/pdf" % (st1["code"], pid2))
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(self.client.post("/students/%s/api/six-am/999999/pdf" % st1["code"]).status_code, 404)

    def test_viewer_can_read_but_not_generate(self):
        st, rid, pid = self._student()
        self._generate(st["code"], pid)
        _login(self.client, "viewer")
        self.assertEqual(self.client.get("/students/%s/api/six-am/pdf-status" % st["code"]).status_code, 200)
        self.assertEqual(self.client.get("/students/%s/api/six-am/%d/pdf/file" % (st["code"], pid)).status_code, 200)
        self.assertEqual(self.client.post("/students/%s/api/six-am/%d/pdf" % (st["code"], pid)).status_code, 403)

    def test_front_desk_scope_denied(self):
        st, rid, pid = self._student()
        _login(self.client, "front")
        self.assertEqual(self.client.get("/students/%s/api/six-am/pdf-status" % st["code"]).status_code, 403)
        self.assertEqual(self.client.get("/students/%s/api/six-am/%d/pdf/file" % (st["code"], pid)).status_code, 403)

    def test_chinese_text_and_pagination(self):
        st, rid = _new_student("分页验收学生")
        long_profile = {**_profile("分页验收学生", "高二", extra_questions=60), "report_id": rid}
        pid = db.add_six_am_profile(st["id"], rid, json.dumps(long_profile, ensure_ascii=False), version=1)
        self.assertEqual(self._generate(st["code"], pid)["state"], "ready")
        blob = self.client.get("/students/%s/api/six-am/%d/pdf/file" % (st["code"], pid)).data
        try:
            import pymupdf
        except ImportError:  # pragma: no cover
            self.skipTest("pymupdf 不可用")
        doc = pymupdf.open(stream=blob, filetype="pdf")
        self.assertGreaterEqual(doc.page_count, 2)
        text = "".join(page.get_text() for page in doc)
        for needle in ("分页验收学生", "六维启动档案", "A1", "紧凑摘要", "规则审计", "共"):
            self.assertIn(needle, text)
        self.assertIn("第 1 页", text)


if __name__ == "__main__":
    unittest.main()
