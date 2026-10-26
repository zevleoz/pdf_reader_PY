# -*- coding: utf-8 -*-
"""P3 验收：6AM 2.0 概览 / 预览 / 团队评议 API 与档案 payload 扩展。

运行：python3 -m pytest test_six_am_v2_api.py -q
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


_ORIG = {}
_USER_IDS = {}
_NAME_SEQ = [0]
DIMS = ("A1", "A2", "A3", "A4", "A5")
STATES = ("Secure", "Watch", "At-Risk", "Blocked")


def setUpModule():
    import questionnaire_store
    tmp_dir = tempfile.mkdtemp(prefix="six_am_v2_api_test_")
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
                               ("advisor2", "advisor", "顾问乙"), ("viewer", "viewer", "")):
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


def _make_report(student_id):
    raw = {
        "student": {"name": "测试学生", "grade": "高二"},
        "schema_124": [
            {"code": "009", "label": "情绪稳定性总分", "value": "55"},
            {"code": "066", "label": "学习动机-深层动机", "value": "3.2"},
            {"code": "128", "label": "学习动机-深层动机常模", "value": "3.0"},
        ],
    }
    import datetime as _dt
    return db.add_report(student_id, _dt.date(2026, 10, 18), "test.pdf",
                         json.dumps(raw, ensure_ascii=False))


def _make_profile(report_id):
    prof = six_am.run_for_report(report_id)
    assert prof is not None
    return prof


def _stored_profile(profile_id):
    return json.loads(db.get_six_am_profile(profile_id)["profile_json"])


def _force_state(profile_id, dim, state):
    prof = _stored_profile(profile_id)
    dims = prof.setdefault("dimensions", {})
    dims.setdefault(dim, {})["state"] = state
    db.update_six_am_profile_json(profile_id, json.dumps(prof, ensure_ascii=False))


def _fresh_case(advisor_name=""):
    sid, name = _fresh_student(advisor_name)
    rid = _make_report(sid)
    prof = _make_profile(rid)
    return sid, name, rid, prof


def _make_app():
    app = Flask(__name__)
    app.secret_key = "test-secret"
    app.register_blueprint(insights_bp)
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

    def _cohort(self, role="admin", advisor_name=""):
        _login(self.client, role, advisor_name)
        return self.client.get("/api/six-am/cohort")

    def _cohort_student(self, data, student_id):
        for entry in data.get("students") or []:
            if entry.get("student_id") == student_id:
                return entry
        return None


class CohortScope(_ApiCase):
    """概览：角色可见范围、分布计数、评议状态流转。"""

    def test_admin_sees_all_advisor_scope_and_viewer_reads(self):
        sid_a, name_a = _fresh_student("顾问甲")
        rid_a = _make_report(sid_a)
        _make_profile(rid_a)
        sid_b, name_b = _fresh_student("顾问乙")
        rid_b = _make_report(sid_b)
        _make_profile(rid_b)

        admin = self._cohort()
        self.assertEqual(admin.status_code, 200)
        body = admin.get_json()
        self.assertTrue(body["ok"])
        self.assertIsNotNone(self._cohort_student(body, sid_a))
        self.assertIsNotNone(self._cohort_student(body, sid_b))

        only_a = self._cohort("advisor", "顾问甲").get_json()
        self.assertIsNotNone(self._cohort_student(only_a, sid_a))
        self.assertIsNone(self._cohort_student(only_a, sid_b))

        viewer = self._cohort("viewer")
        self.assertEqual(viewer.status_code, 200)

    def test_distribution_matches_students(self):
        _fresh_case("顾问甲")
        body = self._cohort().get_json()
        expected = {dim: {state: 0 for state in STATES} for dim in DIMS}
        for entry in body["students"]:
            for dim in DIMS:
                expected[dim][entry["states"][dim]] += 1
        self.assertEqual(body["distribution"], expected)

    def test_review_status_pending_then_reviewed(self):
        sid, _name, rid, prof = _fresh_case()
        _force_state(prof["profile_id"], "A1", "At-Risk")

        entry = self._cohort_student(self._cohort().get_json(), sid)
        self.assertEqual(entry["review_status"], "pending")
        at_risk = [dim for dim in DIMS
                   if entry["states"][dim] in ("At-Risk", "Blocked")]
        self.assertIn("A1", at_risk)

        _login(self.client, "admin")
        for dim in at_risk:
            resp = self.client.post("/api/reports/%d/six-am/reviews" % rid, json={
                "profile_id": prof["profile_id"], "dim": dim, "verdict": "agree"})
            self.assertEqual(resp.status_code, 200, resp.get_data(as_text=True))

        entry = self._cohort_student(self._cohort().get_json(), sid)
        self.assertEqual(entry["review_status"], "reviewed")


class Preview(_ApiCase):
    """预览：返回视图模型与变化行，且不落库。"""

    def test_preview_does_not_save(self):
        sid, _name, rid, prof = _fresh_case()
        before = len(db.get_six_am_profiles_by_student(sid))

        _login(self.client, "admin")
        resp = self.client.post("/api/reports/%d/six-am/preview" % rid,
                                json={"gaps": {"standard_task": {"can_split": False}}})
        self.assertEqual(resp.status_code, 200, resp.get_data(as_text=True))
        body = resp.get_json()
        self.assertTrue(body["ok"])
        self.assertIsInstance(body["changes"], list)
        self.assertTrue(body["view_model"]["cards"])
        self.assertEqual(len(db.get_six_am_profiles_by_student(sid)), before)


class Reviews(_ApiCase):
    """团队评议：权限、校验与 payload 回读。"""

    def setUp(self):
        super().setUp()
        self.sid, self.name, self.rid, self.prof = _fresh_case("顾问甲")

    def _post(self, **body):
        body.setdefault("profile_id", self.prof["profile_id"])
        return self.client.post("/api/reports/%d/six-am/reviews" % self.rid, json=body)

    def test_viewer_forbidden_and_foreign_advisor_forbidden(self):
        _login(self.client, "viewer")
        self.assertEqual(self._post(dim="A1", verdict="agree").status_code, 403)

        _login(self.client, "advisor", "顾问乙")
        self.assertEqual(self._post(dim="A1", verdict="agree").status_code, 403)

    def test_adjust_requires_adjusted_state(self):
        _login(self.client, "admin")
        self.assertEqual(self._post(dim="A1", verdict="adjust").status_code, 400)
        bad = self._post(dim="A1", verdict="adjust", adjusted_state="Unknown")
        self.assertEqual(bad.status_code, 400)

    def test_valid_post_appears_in_profile_payload(self):
        _login(self.client, "admin", display_name="管理员")
        resp = self._post(dim="A2", verdict="adjust", adjusted_state="Watch",
                          note="团队判断偏轻", owner="顾问甲", due_date="2026-11-01")
        self.assertEqual(resp.status_code, 200, resp.get_data(as_text=True))
        review = resp.get_json()["review"]
        self.assertEqual(review["author"], "管理员")
        self.assertEqual(review["adjusted_state"], "Watch")

        payload = self.client.get("/api/reports/%d/six-am" % self.rid).get_json()
        latest = payload["reviews"]["A2"]
        self.assertEqual(latest["verdict"], "adjust")
        self.assertEqual(latest["adjusted_state"], "Watch")
        self.assertEqual(latest["owner"], "顾问甲")


class Payload(_ApiCase):
    """档案 payload：report_date / can_write / previous_states / versions[].changes。"""

    def test_previous_states_and_timeline(self):
        sid, _name, rid, prof = _fresh_case()

        _login(self.client, "admin")
        first = self.client.get("/api/reports/%d/six-am" % rid).get_json()
        self.assertIsNone(first["previous_states"])
        self.assertEqual(len(first["versions"]), 1)
        self.assertTrue(first["versions"][0]["changes"])
        self.assertTrue(first["can_write"])
        self.assertTrue(first["report_date"])

        stored = _stored_profile(prof["profile_id"])
        a1 = stored.setdefault("dimensions", {}).setdefault("A1", {})
        a1["state"] = "Blocked" if a1.get("state") != "Blocked" else "Secure"
        db.add_six_am_profile(sid, rid, json.dumps(stored, ensure_ascii=False),
                              version=prof["version"] + 1)

        second = self.client.get("/api/reports/%d/six-am" % rid).get_json()
        self.assertEqual(second["version"], prof["version"] + 1)
        self.assertIsNotNone(second["previous_states"])
        self.assertEqual(len(second["versions"]), 2)
        self.assertEqual(second["versions"][0]["version"], prof["version"] + 1)
        self.assertTrue(second["versions"][0]["changes"])

    def test_viewer_cannot_write(self):
        _sid, _name, rid, _prof = _fresh_case()
        _login(self.client, "viewer")
        payload = self.client.get("/api/reports/%d/six-am" % rid).get_json()
        self.assertFalse(payload["can_write"])


if __name__ == "__main__":
    unittest.main()
