# -*- coding: utf-8 -*-
"""Q4 验收：6AM 规则板后端（页面 / 读取 / 草稿保存 / 预览）。

运行：python3 -m pytest test_six_am_board_api.py -q
"""

import json
import os
import shutil
import sys
import tempfile
import unittest

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

from sqlalchemy import create_engine, event  # noqa: E402

import app_utils  # noqa: E402
import db  # noqa: E402
import six_am  # noqa: E402
from flask import Flask  # noqa: E402
from blueprints.insights import bp as insights_bp  # noqa: E402
from six_am.spec import DEFAULT_SPEC  # noqa: E402


_ORIG = {}
_USER_IDS = {}
_NAME_SEQ = [0]


def setUpModule():
    import questionnaire_store
    tmp_dir = tempfile.mkdtemp(prefix="six_am_board_api_test_")
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
    assert os.path.realpath(engine.url.database) != os.path.realpath(
        str(db.DEFAULT_DB)), "测试不得连接真实库"
    db.init_db()
    for key, role, advisor in (("admin", "admin", ""), ("advisor", "advisor", "顾问甲"),
                               ("viewer", "viewer", "")):
        _USER_IDS[key] = db.create_user("t_" + key, "x" * 12, role,
                                        advisor_name=advisor,
                                        display_name="用户" + key)
    app_utils._SESSION_USER_CACHE.clear()


def tearDownModule():
    import questionnaire_store
    app_utils._SESSION_USER_CACHE.clear()
    db.engine.dispose()
    db.engine = _ORIG["engine"]
    db.DATABASE_URL = _ORIG["url"]
    questionnaire_store.engine = _ORIG["q_engine"]
    shutil.rmtree(_ORIG["tmp_dir"], ignore_errors=True)


# ── 测试夹具 ────────────────────────────────────────────────────
def _fresh_student(advisor_name=""):
    _NAME_SEQ[0] += 1
    name = "学生%03d" % _NAME_SEQ[0]
    sid = db.find_or_create_student(name=name, grade="高二", advisor_name=advisor_name)
    return sid, name


def _make_report(student_id, schema_124=None):
    raw = {
        "student": {"name": "测试学生", "grade": "高二"},
        "schema_124": schema_124 or [
            {"code": "009", "label": "情绪稳定性总分", "value": "55"},
            {"code": "066", "label": "学习动机-深层动机", "value": "3.2"},
            {"code": "128", "label": "学习动机-深层动机常模", "value": "3.0"},
        ],
    }
    import datetime as _dt
    return db.add_report(student_id, _dt.date(2026, 10, 18), "test.pdf",
                         json.dumps(raw, ensure_ascii=False))


def _make_app():
    app = Flask(__name__)
    app.secret_key = "test-secret"
    app.register_blueprint(insights_bp)
    app_utils.register_admin_context(app)
    app.context_processor(lambda: {"csrf_token": app_utils.get_csrf_token})
    return app


def _login(client, role="admin", advisor_name="", display_name=""):
    with client.session_transaction() as sess:
        sess["user_id"] = _USER_IDS[role]
        sess["role"] = role
        sess["advisor_name"] = advisor_name
        sess["display_name"] = display_name


class _ApiCase(unittest.TestCase):
    def setUp(self):
        self.app = _make_app()
        self.client = self.app.test_client()

    def _post(self, payload, url="/api/six-am/board"):
        return self.client.post(url, data=json.dumps(payload),
                                content_type="application/json")


class BoardPage(_ApiCase):
    def test_can_edit_flag_follows_role(self):
        _login(self.client, "admin")
        res = self.client.get("/insights/six-am/board")
        self.assertEqual(res.status_code, 200)
        self.assertIn('data-can-edit="true"', res.get_data(as_text=True))

        _login(self.client, "viewer")
        res = self.client.get("/insights/six-am/board")
        self.assertEqual(res.status_code, 200)
        self.assertIn('data-can-edit="false"', res.get_data(as_text=True))


class BoardRead(_ApiCase):
    def test_viewer_gets_default_spec_and_signals(self):
        _login(self.client, "viewer")
        res = self.client.get("/api/six-am/board")
        self.assertEqual(res.status_code, 200)
        body = res.get_json()
        self.assertTrue(body["ok"])
        self.assertFalse(body["can_edit"])
        self.assertEqual(body["spec"], DEFAULT_SPEC)
        self.assertIsNone(body["published"])
        self.assertTrue(body["signals"])
        self.assertIn("control_low_max", body["param_meta"])


class BoardWrite(_ApiCase):
    def test_non_admin_forbidden(self):
        spec = {"params": {"top_n_values": 6}}
        for role in ("viewer", "advisor"):
            _login(self.client, role)
            res = self._post({"spec": spec})
            self.assertEqual(res.status_code, 403, role)

    def test_unknown_supporting_signal_rejected(self):
        _login(self.client, "admin")
        res = self._post({"spec": {"dimensions": {"A1": {"supporting": ["no_such_signal"]}}}})
        self.assertEqual(res.status_code, 400)
        body = res.get_json()
        self.assertFalse(body["ok"])
        self.assertTrue(body["errors"])

    def test_main_edit_ignored_and_valid_save_round_trips(self):
        _login(self.client, "admin")
        res = self._post({
            "label": "测试草稿",
            "spec": {
                "dimensions": {"A1": {"main": ["control_low"]}},
                "params": {"top_n_values": 7},
            },
        })
        self.assertEqual(res.status_code, 200)
        vid = res.get_json()["version_id"]

        got = self.client.get("/api/six-am/board?version_id=%d" % vid).get_json()
        self.assertEqual(got["spec"]["params"]["top_n_values"], 7)
        self.assertEqual(got["spec"]["dimensions"]["A1"]["main"], ["autonomy"])
        self.assertEqual(got["version"]["id"], vid)
        self.assertEqual(got["version"]["status"], "draft")
        self.assertIn(vid, [d["id"] for d in got["drafts"]])


class BoardPreview(_ApiCase):
    def test_removing_control_low_shifts_a1_and_never_saves(self):
        sid, _name = _fresh_student()
        rid = _make_report(sid, schema_124=[
            {"code": "060", "label": "自驱力-自主性", "value": "2.0"},
            {"code": "125", "label": "自驱力-自主性常模", "value": "3.5"},
            {"code": "013", "label": "情绪稳定性-无力感掌控感", "value": "4"},
        ])
        self.assertIsNotNone(six_am.run_for_report(rid))
        rows_before = len(db.get_six_am_profiles_by_student(sid))

        _login(self.client, "admin")
        res = self._post({"spec": {"dimensions": {"A1": {"supporting": ["indep_boss_top5"]}}}},
                         url="/api/six-am/board/preview")
        self.assertEqual(res.status_code, 200)
        body = res.get_json()
        self.assertTrue(body["ok"])

        hit = [c for c in body["changed"] if c["report_id"] == rid]
        self.assertTrue(hit, body["changed"])
        self.assertEqual(hit[0]["dims"]["A1"], ["At-Risk", "Watch"])
        self.assertGreaterEqual(body["published_distribution"]["A1"]["At-Risk"], 1)
        self.assertGreaterEqual(body["distribution"]["A1"]["Watch"], 1)

        rows_after = len(db.get_six_am_profiles_by_student(sid))
        self.assertEqual(rows_before, rows_after)


if __name__ == "__main__":
    unittest.main()
