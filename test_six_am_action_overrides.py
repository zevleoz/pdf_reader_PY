# -*- coding: utf-8 -*-
"""Task 4：当前版本行动修订 API 与重跑继承测试（unittest 风格）。

执行裁定（ledger）：环境无 pytest，统一用 python3.11 -m unittest 运行：
    python3.11 -m unittest test_six_am_action_overrides -v

覆盖（实施计划 Task 4 Step 1 / Step 6）：
- db.update_six_am_profile_json：只改 profile_json、不改 version/created_at；
  记录不存在返回 False；传入 session 时不提交（供 Task 8 迁移批量覆盖）。
- POST /api/reports/<id>/six-am/action-overrides：
  未登录 401、viewer 403、advisor 越权 403；非法维度 / 非字符串或空条目 /
  超 8 条 / 单条超 300 字 → 400；profile 不属于该 report → 404；
  成功后版本号不变、view_model 反映修订。
- 继承：POST answers 重跑产生新版本，action_overrides 从已解析的旧档案继承
  （显式 source_profile 与 _latest_profile_dict fallback 两条路径）。
"""

import json
import os
import sys
import tempfile
import unittest

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

# 必须在 import db 之前指向临时库，避免触碰真实数据
_TMP_DIR = tempfile.mkdtemp(prefix="six_am_overrides_test_")
os.environ["DATABASE_URL"] = "sqlite:///%s" % os.path.join(_TMP_DIR, "test.db")

import db  # noqa: E402

db.init_db()

import six_am  # noqa: E402
from flask import Flask  # noqa: E402
from blueprints.insights import bp as insights_bp  # noqa: E402


# ── 测试夹具 ────────────────────────────────────────────────────
def _make_student(advisor_name=""):
    return db.find_or_create_student(name="测试学生", grade="高二",
                                     advisor_name=advisor_name)


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


def _make_profile(student_id, report_id, extra=None):
    prof = six_am.run_for_report(report_id)
    assert prof is not None
    if extra:
        prof.update(extra)
        stored = {k: v for k, v in prof.items()
                  if k not in ("profile_id", "version")}
        db.update_six_am_profile_json(
            prof["profile_id"], json.dumps(stored, ensure_ascii=False))
    return prof


def _make_app():
    app = Flask(__name__)
    app.secret_key = "test-secret"
    app.register_blueprint(insights_bp)
    return app


def _login(client, role="admin", advisor_name=""):
    with client.session_transaction() as sess:
        sess["user_id"] = 1
        sess["role"] = role
        sess["advisor_name"] = advisor_name


OVERRIDE = {"next_actions": ["和家长协商一个可修改的目标"],
            "avoid_actions": ["本周不追加任何监督"]}


# ── DB 更新函数 ─────────────────────────────────────────────────
class UpdateSixAmProfileJson(unittest.TestCase):
    """db.update_six_am_profile_json：就地更新，不新建版本。"""

    def setUp(self):
        self.student_id = _make_student()
        self.report_id = _make_report(self.student_id)
        self.prof = _make_profile(self.student_id, self.report_id)
        self.pid = self.prof["profile_id"]

    def test_update_changes_profile_json_only(self):
        before = db.get_six_am_profile(self.pid)
        new_prof = json.loads(before["profile_json"])
        new_prof["action_overrides"] = {"A1": dict(OVERRIDE)}
        ok = db.update_six_am_profile_json(
            self.pid, json.dumps(new_prof, ensure_ascii=False))
        self.assertTrue(ok)
        after = db.get_six_am_profile(self.pid)
        saved = json.loads(after["profile_json"])
        self.assertEqual(saved["action_overrides"]["A1"]["next_actions"],
                         OVERRIDE["next_actions"])
        # version / created_at 不变
        self.assertEqual(after["version"], before["version"])
        self.assertEqual(after["created_at"], before["created_at"])

    def test_update_missing_profile_returns_false(self):
        self.assertFalse(db.update_six_am_profile_json(999999, "{}"))

    def test_update_with_session_does_not_commit(self):
        """传入 session 时只执行 update、不提交（Task 8 迁移在同一事务批量覆盖）。"""
        from sqlalchemy.orm import Session
        before = db.get_six_am_profile(self.pid)
        with Session(db.engine) as sess:
            ok = db.update_six_am_profile_json(self.pid, '{"probe": 1}', session=sess)
            self.assertTrue(ok)
            sess.rollback()  # 若 helper 已提交，rollback 无法撤回
        after = db.get_six_am_profile(self.pid)
        self.assertEqual(after["profile_json"], before["profile_json"])

    def test_update_with_session_visible_after_caller_commit(self):
        from sqlalchemy.orm import Session
        with Session(db.engine) as sess:
            db.update_six_am_profile_json(self.pid, '{"probe": 2}', session=sess)
            sess.commit()
        after = db.get_six_am_profile(self.pid)
        self.assertEqual(json.loads(after["profile_json"]), {"probe": 2})


# ── 行动修订 API ────────────────────────────────────────────────
class ActionOverridesAPI(unittest.TestCase):
    """POST /api/reports/<id>/six-am/action-overrides 的鉴权与校验。"""

    @classmethod
    def setUpClass(cls):
        cls.app = _make_app()

    def setUp(self):
        self.client = self.app.test_client()
        self.student_id = _make_student()
        self.report_id = _make_report(self.student_id)
        self.prof = _make_profile(self.student_id, self.report_id)
        self.pid = self.prof["profile_id"]
        self.url = "/api/reports/%d/six-am/action-overrides" % self.report_id

    def _payload(self, **kw):
        data = {"profile_id": self.pid, "dim": "A1",
                "next_actions": list(OVERRIDE["next_actions"]),
                "avoid_actions": list(OVERRIDE["avoid_actions"])}
        data.update(kw)
        return data

    # ── 鉴权 ──
    def test_unauthenticated_returns_401(self):
        r = self.client.post(self.url, json=self._payload())
        self.assertEqual(r.status_code, 401)

    def test_viewer_role_forbidden(self):
        _login(self.client, role="viewer")
        r = self.client.post(self.url, json=self._payload())
        self.assertEqual(r.status_code, 403)

    def test_advisor_scope_forbidden_for_other_advisors_student(self):
        other_student = _make_student(advisor_name="顾问乙")
        other_report = _make_report(other_student)
        prof = _make_profile(other_student, other_report)
        _login(self.client, role="advisor", advisor_name="顾问甲")
        r = self.client.post(
            "/api/reports/%d/six-am/action-overrides" % other_report,
            json={"profile_id": prof["profile_id"], "dim": "A1",
                  "next_actions": ["x"], "avoid_actions": []})
        self.assertEqual(r.status_code, 403)

    # ── 校验 ──
    def test_invalid_dim_returns_400(self):
        _login(self.client)
        for bad in ("A7", "B1", "", "a1"):
            r = self.client.post(self.url, json=self._payload(dim=bad))
            self.assertEqual(r.status_code, 400, bad)

    def test_too_many_actions_returns_400(self):
        _login(self.client)
        r = self.client.post(self.url,
                             json=self._payload(next_actions=["条目%d" % i
                                                              for i in range(9)]))
        self.assertEqual(r.status_code, 400)

    def test_too_long_action_returns_400(self):
        _login(self.client)
        r = self.client.post(self.url,
                             json=self._payload(next_actions=["长" * 301]))
        self.assertEqual(r.status_code, 400)

    def test_empty_or_non_string_item_returns_400(self):
        _login(self.client)
        for bad_list in ([""], ["   "], [123], [None]):
            r = self.client.post(self.url,
                                 json=self._payload(next_actions=bad_list))
            self.assertEqual(r.status_code, 400, repr(bad_list))

    def test_missing_profile_returns_404(self):
        _login(self.client)
        r = self.client.post(self.url, json=self._payload(profile_id=999999))
        self.assertEqual(r.status_code, 404)

    def test_profile_report_mismatch_returns_404(self):
        _login(self.client)
        other_student = _make_student()
        other_report = _make_report(other_student)
        # self.pid 属于 self.report_id，不属于 other_report
        r = self.client.post(
            "/api/reports/%d/six-am/action-overrides" % other_report,
            json=self._payload())
        self.assertEqual(r.status_code, 404)

    # ── 成功路径：版本不变 + view_model 反映修订 ──
    def test_save_override_keeps_version_and_returns_view_model(self):
        _login(self.client)
        before = db.get_six_am_profile(self.pid)
        r = self.client.post(self.url, json=self._payload())
        self.assertEqual(r.status_code, 200, r.get_json())
        body = r.get_json()
        self.assertTrue(body["ok"])
        # 版本不变
        self.assertEqual(body["version"], before["version"])
        after = db.get_six_am_profile(self.pid)
        self.assertEqual(after["version"], before["version"])
        self.assertEqual(after["created_at"], before["created_at"])
        # profile_json 已持久化 override
        saved = json.loads(after["profile_json"])
        self.assertEqual(saved["action_overrides"]["A1"], OVERRIDE)
        # 响应含 view_model，且 A1 卡反映修订
        vm = body.get("view_model") or {}
        self.assertIn("cards", vm)
        cards = {c["dim"]: c for c in vm["cards"]}
        self.assertEqual(cards["A1"]["next_actions"], OVERRIDE["next_actions"])
        self.assertEqual(cards["A1"]["avoid_actions"], OVERRIDE["avoid_actions"])
        self.assertTrue(cards["A1"]["manually_edited"])
        # GET 同一 profile：版本号不变且内容已更新
        r2 = self.client.get("/api/reports/%d/six-am?profile_id=%d"
                             % (self.report_id, self.pid))
        self.assertEqual(r2.status_code, 200)
        body2 = r2.get_json()
        self.assertEqual(body2["version"], before["version"])
        cards2 = {c["dim"]: c for c in body2["view_model"]["cards"]}
        self.assertEqual(cards2["A1"]["next_actions"], OVERRIDE["next_actions"])


# ── 重跑继承 ────────────────────────────────────────────────────
class RerunInheritance(unittest.TestCase):
    """保存追问/缺口触发新版本时必须继承旧档案的 action_overrides。"""

    @classmethod
    def setUpClass(cls):
        cls.app = _make_app()

    def setUp(self):
        self.client = self.app.test_client()
        self.student_id = _make_student()
        self.report_id = _make_report(self.student_id)
        self.prof = _make_profile(self.student_id, self.report_id,
                                  extra={"action_overrides": {"A1": dict(OVERRIDE)}})
        self.pid = self.prof["profile_id"]

    def test_rerun_inherits_overrides_via_latest_fallback(self):
        """_build 从 _latest_profile_dict fallback 解析 prev 时也要继承。"""
        new_prof = six_am.run_for_report(
            self.report_id, answers=[{"q": "Q1.3", "result": "confirm"}])
        self.assertIsNotNone(new_prof)
        self.assertEqual(new_prof["version"], self.prof["version"] + 1)
        self.assertEqual(new_prof.get("action_overrides"),
                         {"A1": dict(OVERRIDE)})
        # 深拷贝：改新版本不影响旧记录
        new_prof["action_overrides"]["A1"]["next_actions"].append("篡改")
        old = json.loads(db.get_six_am_profile(self.pid)["profile_json"])
        self.assertEqual(old["action_overrides"]["A1"]["next_actions"],
                         OVERRIDE["next_actions"])

    def test_rerun_inherits_overrides_via_explicit_source_profile(self):
        prev = json.loads(db.get_six_am_profile(self.pid)["profile_json"])
        new_prof = six_am.run_for_report(self.report_id, source_profile=prev)
        self.assertEqual(new_prof.get("action_overrides"),
                         {"A1": dict(OVERRIDE)})

    def test_rerun_without_prev_overrides_has_none(self):
        student_id = _make_student()
        report_id = _make_report(student_id)
        prof = six_am.run_for_report(report_id)  # v1，无 override
        new_prof = six_am.run_for_report(report_id)  # v2 重跑
        self.assertEqual(new_prof["version"], prof["version"] + 1)
        self.assertFalse(new_prof.get("action_overrides"))

    def test_post_answers_rerun_inherits_overrides(self):
        """POST answers → 新版本继承 override，view_model 反映修订。"""
        _login(self.client)
        r = self.client.post("/api/reports/%d/six-am/answers" % self.report_id,
                             json={"answers": [{"q": "Q1.3", "result": "confirm"}]})
        self.assertEqual(r.status_code, 200, r.get_json())
        body = r.get_json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["version"], self.prof["version"] + 1)
        saved = json.loads(db.get_six_am_profile(body["profile_id"])["profile_json"])
        self.assertEqual(saved.get("action_overrides"), {"A1": dict(OVERRIDE)})
        cards = {c["dim"]: c for c in body["view_model"]["cards"]}
        self.assertEqual(cards["A1"]["next_actions"], OVERRIDE["next_actions"])
        self.assertTrue(cards["A1"]["manually_edited"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
