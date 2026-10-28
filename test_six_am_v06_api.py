# -*- coding: utf-8 -*-
"""R3 验收：6AM v0.6 后端（模型 / 概览 / 档案 / 输入 / 全量重算 / 退役路由）。

运行：python3 -m pytest test_six_am_v06_api.py -q
"""

import datetime as _dt
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


def setUpModule():
    import questionnaire_store
    tmp_dir = tempfile.mkdtemp(prefix="six_am_v06_api_test_")
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
                               ("advisor2", "advisor", "顾问乙"),
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


def _make_report(student_id, autonomy="偏低"):
    """自驱力-自主性 = 偏低 → A1 风险。"""
    raw = {
        "student": {"name": "测试学生", "grade": "高二"},
        "schema_124": [
            {"code": "100", "label": "自驱力-自主性", "value": "5.2"},
            {"code": "1000", "label": "自驱力-自主性结果档位", "value": autonomy},
        ],
    }
    return db.add_report(student_id, _dt.date(2026, 10, 18), "test.pdf",
                         json.dumps(raw, ensure_ascii=False))


def _generate(report_id):
    prof = six_am.run_v06_for_report(report_id)
    assert prof is not None
    return prof


def _fresh_case(advisor_name=""):
    sid, name = _fresh_student(advisor_name)
    rid = _make_report(sid)
    return sid, name, rid


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

    def _payload(self, rid, **kwargs):
        resp = self.client.get("/api/reports/%d/six-am" % rid, **kwargs)
        self.assertEqual(resp.status_code, 200, resp.get_data(as_text=True))
        return resp.get_json()

    def _cohort(self, role="admin", advisor_name=""):
        _login(self.client, role, advisor_name)
        resp = self.client.get("/api/six-am/cohort")
        self.assertEqual(resp.status_code, 200, resp.get_data(as_text=True))
        return resp.get_json()

    def _cohort_student(self, data, student_id):
        for entry in data.get("students") or []:
            if entry.get("student_id") == student_id:
                return entry
        return None


class Model(_ApiCase):
    def test_model_json_and_markdown(self):
        _login(self.client, "admin")
        model = self.client.get("/api/six-am/model")
        self.assertEqual(model.status_code, 200)
        body = model.get_json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["model"]["version"], "v0.6")
        self.assertEqual([d["id"] for d in body["model"]["dims"]], list(DIMS))

        md = self.client.get("/api/six-am/model.md")
        self.assertEqual(md.status_code, 200)
        self.assertIn("text/markdown", md.headers["Content-Type"])
        self.assertIn("6am-mindmap-v0.6.md", md.headers["Content-Disposition"])
        self.assertTrue(md.get_data(as_text=True).startswith("# 6AM 思维导图"))

    def test_model_requires_login(self):
        self.assertEqual(self.client.get("/api/six-am/model").status_code, 401)


class Generate(_ApiCase):
    def test_generate_creates_v06_profile_and_bumps_version(self):
        _sid, _name, rid = _fresh_case()
        _login(self.client, "admin")

        first = self.client.post("/api/reports/%d/six-am/generate" % rid)
        self.assertEqual(first.status_code, 200, first.get_data(as_text=True))
        body = first.get_json()
        self.assertEqual(body["version"], 1)
        self.assertFalse(body["legacy"])
        self.assertEqual(body["profile"]["schema"], "6am.v0.6")
        self.assertEqual(body["profile"]["dims"]["A1"]["level"], "风险")
        self.assertEqual(len(body["versions"]), 1)

        second = self.client.post("/api/reports/%d/six-am/generate" % rid)
        self.assertEqual(second.status_code, 200)
        body = second.get_json()
        self.assertEqual(body["version"], 2)
        self.assertEqual(len(body["versions"]), 2)

    def test_generate_missing_report_and_viewer(self):
        _login(self.client, "admin")
        self.assertEqual(self.client.post("/api/reports/999999/six-am/generate").status_code,
                         404)
        _sid, _name, rid = _fresh_case()
        _login(self.client, "viewer")
        self.assertEqual(self.client.post("/api/reports/%d/six-am/generate" % rid).status_code,
                         403)


class Inputs(_ApiCase):
    def setUp(self):
        super().setUp()
        self.sid, self.name, self.rid = _fresh_case("顾问甲")
        _login(self.client, "admin")
        first = self.client.post("/api/reports/%d/six-am/generate" % self.rid)
        self.assertEqual(first.status_code, 200)
        self.prof = first.get_json()["profile"]

    def _post(self, body):
        return self.client.post("/api/reports/%d/six-am/inputs" % self.rid, json=body)

    def test_confirm_on_risk_dim_blocks_and_bumps_version(self):
        resp = self._post({"talks": {"A1": {"result": "confirm", "note": "会谈确认"}}})
        self.assertEqual(resp.status_code, 200, resp.get_data(as_text=True))
        body = resp.get_json()
        self.assertEqual(body["version"], 2)
        a1 = body["profile"]["dims"]["A1"]
        self.assertEqual(a1["level"], "阻塞")
        self.assertTrue(a1["blocked"])
        today = _dt.date.today().isoformat()
        self.assertEqual(body["profile"]["inputs"]["talks"]["A1"]["at"], today)

    def test_set_talk_overrides_level_and_keeps_model_level(self):
        resp = self._post({"talks": {"A1": {"result": "set", "set_level": "关注"}}})
        self.assertEqual(resp.status_code, 200, resp.get_data(as_text=True))
        a1 = resp.get_json()["profile"]["dims"]["A1"]
        self.assertEqual(a1["level"], "关注")
        self.assertEqual(a1["model_level"], "风险")
        self.assertTrue(a1["set_by_talk"])

    def test_ft_input_merges_and_keeps_talks(self):
        self.assertEqual(self._post({"talks": {"A1": {"result": "deny"}}}).status_code, 200)
        resp = self._post({"ft": {"goal": {"judgement": "不认同"}}})
        self.assertEqual(resp.status_code, 200, resp.get_data(as_text=True))
        inputs = resp.get_json()["profile"]["inputs"]
        self.assertEqual(inputs["ft"]["goal"]["judgement"], "不认同")
        self.assertEqual(inputs["talks"]["A1"]["result"], "deny")

    def test_bad_inputs_are_rejected(self):
        bad = [
            {"talks": {"A6": {"result": "confirm"}}},
            {"talks": {"A1": {"result": "maybe"}}},
            {"talks": {"A1": {"result": "set"}}},
            {"talks": {"A1": {"result": "set", "set_level": "很好"}}},
            {"talks": {"A1": {"result": "confirm", "causes": ["not_a_cause"]}}},
            {"talks": {"A1": {"result": "confirm", "note": "x" * 501}}},
        ]
        for body in bad:
            resp = self._post(body)
            self.assertEqual(resp.status_code, 400, body)
        self.assertEqual(self.client.post(
            "/api/reports/%d/six-am/inputs" % self.rid, json={"ft": "x"}).status_code, 400)

    def test_viewer_and_foreign_advisor_forbidden(self):
        _login(self.client, "viewer")
        self.assertEqual(self._post({"talks": {"A1": {"result": "confirm"}}}).status_code, 403)
        _login(self.client, "advisor", "顾问乙")
        self.assertEqual(self._post({"talks": {"A1": {"result": "confirm"}}}).status_code, 403)


class Cohort(_ApiCase):
    def test_v06_shape_and_needs_talk(self):
        sid, _name, rid = _fresh_case("顾问甲")
        _login(self.client, "admin")
        self.assertEqual(self.client.post("/api/reports/%d/six-am/generate" % rid).status_code,
                         200)
        body = self._cohort()
        self.assertEqual(body["model_version"], "v0.6")
        entry = self._cohort_student(body, sid)
        self.assertIsNotNone(entry)
        for key in ("student_id", "name", "grade", "report_id", "report_date",
                    "profile_id", "version", "legacy", "levels", "types",
                    "needs_talk", "blocked", "a6_top", "safety"):
            self.assertIn(key, entry)
        self.assertFalse(entry["legacy"])
        self.assertEqual(entry["levels"]["A1"], "风险")
        self.assertIn("A1", entry["needs_talk"])
        self.assertIsNone(entry["types"]["A1"])
        self.assertLessEqual(len(entry["a6_top"]), 4)

    def test_legacy_row_maps_states(self):
        sid, _name, rid = _fresh_case()
        legacy = {
            "schema": "six-am-profile-v3",
            "dimensions": {
                "A1": {"state": "At-Risk"}, "A2": {"state": "Watch"},
                "A3": {"state": "Secure"}, "A4": {"state": "Blocked"},
                "A5": {"state": "Watch"},
            },
            "safety_review": True,
        }
        db.add_six_am_profile(sid, rid, json.dumps(legacy, ensure_ascii=False), version=1)
        entry = self._cohort_student(self._cohort(), sid)
        self.assertTrue(entry["legacy"])
        self.assertEqual(entry["levels"], {"A1": "风险", "A2": "关注", "A3": "稳固",
                                           "A4": "阻塞", "A5": "关注"})
        self.assertEqual(set(entry["types"].values()), {None})
        self.assertEqual(entry["needs_talk"], [])
        self.assertEqual(entry["a6_top"], [])
        self.assertTrue(entry["safety"])

    def test_advisor_scope_and_viewer_read(self):
        sid_a, _na, rid_a = _fresh_case("顾问甲")
        sid_b, _nb, rid_b = _fresh_case("顾问乙")
        _login(self.client, "admin")
        self.client.post("/api/reports/%d/six-am/generate" % rid_a)
        self.client.post("/api/reports/%d/six-am/generate" % rid_b)

        only_a = self._cohort("advisor", "顾问甲")
        self.assertIsNotNone(self._cohort_student(only_a, sid_a))
        self.assertIsNone(self._cohort_student(only_a, sid_b))

        viewer = self._cohort("viewer")
        self.assertIsNotNone(self._cohort_student(viewer, sid_a))


    def test_student_without_profile_is_pending_and_no_report_counted(self):
        sid, _name, rid = _fresh_case()
        bare_sid, _bare = _fresh_student()
        body = self._cohort()
        entry = self._cohort_student(body, sid)
        self.assertTrue(entry["pending"])
        self.assertEqual(entry["report_id"], rid)
        self.assertEqual(set(entry["levels"].values()), {None})
        self.assertIsNone(self._cohort_student(body, bare_sid))
        self.assertGreaterEqual(body["no_report"], 1)
        self.assertGreaterEqual(body["pending"], 1)

    def test_newer_report_without_profile_is_pending(self):
        sid, _name, rid = _fresh_case()
        _generate(rid)
        raw = {"student": {"name": "测试学生", "grade": "高二"}, "schema_124": []}
        newer = db.add_report(sid, _dt.date(2026, 10, 25), "newer.pdf",
                              json.dumps(raw, ensure_ascii=False))
        entry = self._cohort_student(self._cohort(), sid)
        self.assertTrue(entry["pending"])
        self.assertEqual(entry["report_id"], newer)


class RerunAll(_ApiCase):
    def test_generates_students_that_never_had_a_profile(self):
        sid, _name, rid = _fresh_case()
        self.assertEqual(db.get_six_am_profiles_by_student(sid), [])
        _login(self.client, "admin")
        body = self.client.post("/api/six-am/rerun-all").get_json()
        self.assertTrue(body["ok"])
        self.assertNotIn(rid, body["failed"])
        entry = self._cohort_student(self._cohort(), sid)
        self.assertFalse(entry["pending"])
        self.assertEqual(entry["levels"]["A1"], "风险")

    def test_admin_reruns_and_advisor_forbidden(self):
        sid, _name, rid = _fresh_case()
        _login(self.client, "admin")
        self.client.post("/api/reports/%d/six-am/generate" % rid)
        before = len(db.get_six_am_profiles_by_student(sid))

        resp = self.client.post("/api/six-am/rerun-all")
        self.assertEqual(resp.status_code, 200, resp.get_data(as_text=True))
        body = resp.get_json()
        self.assertTrue(body["ok"])
        self.assertGreaterEqual(body["count"], 1)
        self.assertEqual(body["failed"], [])
        self.assertGreater(len(db.get_six_am_profiles_by_student(sid)), before)

        _login(self.client, "advisor", "顾问甲")
        self.assertEqual(self.client.post("/api/six-am/rerun-all").status_code, 403)


class RetiredRoutes(_ApiCase):
    def test_retired_api_paths_return_404(self):
        _sid, _name, rid = _fresh_case()
        _login(self.client, "admin")
        cases = [
            ("get", "/api/six-am/board"),
            ("post", "/api/six-am/board"),
            ("post", "/api/six-am/board/preview"),
            ("get", "/api/six-am/rule-versions"),
            ("post", "/api/six-am/rule-versions"),
            ("post", "/api/six-am/rule-versions/1/publish"),
            ("post", "/api/six-am/sandbox"),
            ("post", "/api/reports/%d/six-am/preview" % rid),
            ("post", "/api/reports/%d/six-am/reviews" % rid),
            ("post", "/api/reports/%d/six-am/action-overrides" % rid),
            ("post", "/api/reports/%d/six-am/answers" % rid),
            ("get", "/api/reports/%d/six-am/docx" % rid),
        ]
        for method, path in cases:
            resp = getattr(self.client, method)(path)
            self.assertEqual(resp.status_code, 404, "%s %s" % (method.upper(), path))

    def test_old_pages_redirect_to_rules_view(self):
        _login(self.client, "admin")
        for path in ("/insights/six-am/board", "/insights/six-am/rules", "/six-am/rules"):
            resp = self.client.get(path)
            self.assertEqual(resp.status_code, 302, path)
            self.assertTrue(resp.headers["Location"].endswith("/insights/six-am?view=rules"),
                            path)

    def test_old_pages_require_login(self):
        resp = self.client.get("/insights/six-am/rules")
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/login", resp.headers["Location"])


class Payload(_ApiCase):
    def test_profile_payload_and_version_selector(self):
        _sid, _name, rid = _fresh_case()
        _login(self.client, "admin")
        self.assertEqual(self.client.get("/api/reports/%d/six-am" % rid).status_code, 404)

        first = self.client.post("/api/reports/%d/six-am/generate" % rid).get_json()
        body = self._payload(rid)
        self.assertEqual(body["version"], first["version"])
        self.assertTrue(body["report_date"])
        self.assertFalse(body["legacy"])
        self.assertEqual(len(body["versions"]), 1)

        second = self.client.post("/api/reports/%d/six-am/generate" % rid).get_json()
        picked = self._payload(rid, query_string={"profile_id": first["profile_id"]})
        self.assertEqual(picked["version"], first["version"])
        self.assertEqual(picked["profile_id"], first["profile_id"])
        latest = self._payload(rid)
        self.assertEqual(latest["version"], second["version"])

    def test_json_export_still_works(self):
        _sid, _name, rid = _fresh_case()
        _login(self.client, "admin")
        self.client.post("/api/reports/%d/six-am/generate" % rid)
        resp = self.client.get("/api/reports/%d/six-am/json" % rid)
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["json"]["schema"], "6am.v0.6")
        self.assertTrue(body["filename"].endswith(".json"))


if __name__ == "__main__":
    unittest.main()
