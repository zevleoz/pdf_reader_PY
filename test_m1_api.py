"""M1 API 契约测试：权限、学生清单、资料、草稿并发、定稿与导出审计。

复用 ``test_m1_store`` 的临时库 fixture；Y4 证据由 P1 提供，这里不依赖其
内部实现（需要 ``raw`` 时用 monkeypatch 造一条）。
"""
from __future__ import annotations

import json

import pytest
from flask import Flask
from sqlalchemy import select
from sqlalchemy.orm import Session

import growth_talk_store as _gt
import m1.sources as sources
from app_utils import BASE_DIR
from test_m1_store import _doc, m1db  # noqa: F401  复用临时库与文档构造


# ---------------------------------------------------------------------------
# 应用 / 登录
# ---------------------------------------------------------------------------
@pytest.fixture()
def client(m1db, monkeypatch):  # noqa: F811
    import app_utils
    from blueprints import m1 as m1_api

    # 只跳过「session 用户是否仍有效」的检查；角色与 advisor 归属走真实实现
    monkeypatch.setattr(app_utils, "is_authenticated", lambda: True)
    app = Flask(__name__, template_folder=str(BASE_DIR / "templates"))
    app.secret_key = "test-secret"
    app.register_blueprint(m1_api.bp)
    return app.test_client()


def login_as(client, user_id, role, advisor_name="", display_name=None):
    with client.session_transaction() as sess:
        sess["user_id"] = user_id
        sess["role"] = role
        sess["advisor_name"] = advisor_name
        sess["display_name"] = advisor_name if display_name is None else display_name


@pytest.fixture()
def admin(client, m1db):
    login_as(client, m1db.admin_id, "admin")
    return client


@pytest.fixture()
def alice(client, m1db):
    login_as(client, m1db.alice_id, "advisor", "Alice")
    return client


def _actions(engine):
    with Session(engine) as sess:
        return [row.action for row in sess.execute(select(_gt.AuditLog)).scalars()]


# ---------------------------------------------------------------------------
# 权限
# ---------------------------------------------------------------------------
def test_viewer_gets_403_everywhere(client, m1db):
    login_as(client, m1db.viewer_id, "viewer")

    assert client.get("/api/m1/students").status_code == 403
    assert client.get("/m1").status_code == 403
    assert client.post("/api/m1/preps", json={"student_id": m1db.student_id}).status_code == 403


def test_advisor_cannot_touch_another_advisors_student(alice, m1db):
    other_prep = m1db.prep(m1db.other_student_id, m1db.bob_id)

    assert alice.get(f"/api/m1/preps/{other_prep['id']}").status_code == 403
    assert alice.patch(f"/api/m1/preps/{other_prep['id']}",
                       json={"duration": 90}).status_code == 403
    assert alice.put(f"/api/m1/preps/{other_prep['id']}/doc",
                     json={"rev": 1, "doc": _doc()}).status_code == 403
    assert alice.post(f"/api/m1/preps/{other_prep['id']}/sources",
                      json={"text": "家长反馈" * 20, "category": "parent"}).status_code == 403
    assert alice.post("/api/m1/preps",
                      json={"student_id": m1db.other_student_id}).status_code == 403


def test_missing_prep_is_404(admin):
    assert admin.get("/api/m1/preps/999999").status_code == 404
    assert admin.post("/api/m1/preps/999999/finalize").status_code == 404


# ---------------------------------------------------------------------------
# 学生清单 / prep 列表
# ---------------------------------------------------------------------------
def test_students_list_flags_incomplete_y4(admin, m1db):
    payload = admin.get("/api/m1/students").get_json()
    rows = {row["name"]: row for row in payload["students"]}
    assert set(rows) == {"林晓雨", "陈一鸣", "吴子涵"}
    assert rows["林晓雨"]["y4_complete"] is True
    assert rows["吴子涵"]["y4_complete"] is False
    assert rows["吴子涵"]["reason"] == "Y4 尚未完成"


def test_advisor_students_list_is_scoped(alice):
    names = {row["name"] for row in alice.get("/api/m1/students").get_json()["students"]}
    assert names == {"林晓雨", "吴子涵"}


def test_preps_list_scoped_and_filtered(alice, m1db):
    mine = m1db.prep(m1db.student_id, m1db.alice_id)
    m1db.prep(m1db.other_student_id, m1db.bob_id)

    rows = alice.get("/api/m1/preps").get_json()["preps"]
    assert [row["id"] for row in rows] == [mine["id"]]

    filtered = alice.get("/api/m1/preps?status=draft").get_json()["preps"]
    assert len(filtered) == 1
    assert alice.get("/api/m1/preps?status=nope").status_code == 400


# ---------------------------------------------------------------------------
# 新建 / 会议信息
# ---------------------------------------------------------------------------
def test_create_prep_auto_meta_and_reuse(admin, m1db):
    res = admin.post("/api/m1/preps", json={"student_id": m1db.student_id})
    assert res.status_code == 201
    payload = res.get_json()
    assert payload["created"] is True
    prep = payload["prep"]
    assert prep["student_id"] == m1db.student_id
    assert prep["status"] == "draft"
    assert prep["duration"] == 60
    assert prep["meeting_date"] == ""
    assert prep["attendees"] == ["林晓雨"]

    again = admin.post("/api/m1/preps", json={"student_id": m1db.student_id})
    assert again.status_code == 200
    assert again.get_json()["created"] is False
    assert again.get_json()["prep"]["id"] == prep["id"]
    # 只有一条 prep，重复点击 360 页入口不会造新记录
    assert len(admin.get("/api/m1/preps").get_json()["preps"]) == 1
    assert "m1.create_reused" in _actions(m1db.engine)


def test_create_prep_requires_complete_y4(admin, m1db):
    res = admin.post("/api/m1/preps", json={"student_id": m1db.incomplete_student_id})
    assert res.status_code == 400
    assert res.get_json()["error"] == "Y4 尚未完成"
    assert res.get_json()["reason"] == "Y4 尚未完成"


def test_create_prep_validates_input(admin, m1db):
    assert admin.post("/api/m1/preps", json={}).status_code == 400
    assert admin.post("/api/m1/preps", json={"student_id": "abc"}).status_code == 400
    assert admin.post("/api/m1/preps", json={"student_id": 999999}).status_code == 404


def test_patch_prep_meta(admin, m1db):
    prep = m1db.prep()

    res = admin.patch(f"/api/m1/preps/{prep['id']}",
                      json={"meeting_date": "2026-11-03", "duration": 90,
                            "attendees": ["李老师（M1 Mentor）", "林晓雨", "  "]})
    assert res.status_code == 200
    updated = res.get_json()["prep"]
    assert updated["meeting_date"] == "2026-11-03"
    assert updated["duration"] == 90
    assert updated["attendees"] == ["李老师（M1 Mentor）", "林晓雨"]

    assert admin.patch(f"/api/m1/preps/{prep['id']}",
                       json={"duration": 3}).status_code == 422
    assert admin.patch(f"/api/m1/preps/{prep['id']}", json={}).status_code == 400
    assert "m1.meta" in _actions(m1db.engine)


def test_patch_mentor_must_exist(admin, m1db):
    prep = m1db.prep()
    ok = admin.patch(f"/api/m1/preps/{prep['id']}", json={"mentor_user_id": m1db.bob_id})
    assert ok.status_code == 200
    assert ok.get_json()["prep"]["mentor_name"] == "Bob"
    assert admin.patch(f"/api/m1/preps/{prep['id']}",
                       json={"mentor_user_id": 999999}).status_code == 404


# ---------------------------------------------------------------------------
# 资料
# ---------------------------------------------------------------------------
def test_source_text_add_patch_delete(admin, m1db):
    prep = m1db.prep()
    text = ("2026-10-20 Case Review 会议记录。参与：田老师、王老师。"
            "课堂观察：答错后整节课低头不说话。团队假设：担心被评价。")

    res = admin.post(f"/api/m1/preps/{prep['id']}/sources",
                     json={"text": text, "category": "case_review"})
    assert res.status_code == 201
    source = res.get_json()["source"]
    assert source["category"] == "case_review"
    assert source["detected_date"] == "2026-10-20"
    assert source["status"] == "ok"

    patched = admin.patch(f"/api/m1/sources/{source['id']}",
                          json={"category": "parent", "detected_date": "2026-10-21"})
    assert patched.status_code == 200
    assert patched.get_json()["source"]["category"] == "parent"
    assert patched.get_json()["source"]["detected_date"] == "2026-10-21"

    removed = admin.delete(f"/api/m1/sources/{source['id']}")
    assert removed.status_code == 200
    assert admin.get(f"/api/m1/preps/{prep['id']}").get_json()["sources"] == []
    assert "m1.source_add" in _actions(m1db.engine)
    assert "m1.source_update" in _actions(m1db.engine)
    assert "m1.source_delete" in _actions(m1db.engine)


def test_source_upload_multipart(admin, m1db):
    prep = m1db.prep()
    res = admin.post(
        f"/api/m1/preps/{prep['id']}/sources",
        data={"category": "parent",
              "file": (__import__("io").BytesIO("妈妈 10 月 9 日微信反馈：考差会说自己笨。"
                                                "孩子回家不怎么说话。".encode("utf-8")),
                       "家长反馈.txt")},
        content_type="multipart/form-data")
    assert res.status_code == 201
    source = res.get_json()["source"]
    assert "考差会说自己笨" in source["text"]
    assert source["filename"] == "家长反馈.txt"


def test_source_validation(admin, m1db):
    prep = m1db.prep()
    assert admin.post(f"/api/m1/preps/{prep['id']}/sources",
                      json={"text": "x", "category": "nope"}).status_code == 400
    assert admin.post(f"/api/m1/preps/{prep['id']}/sources",
                      json={"text": "   ", "category": "parent"}).status_code == 400
    assert admin.patch("/api/m1/sources/999999", json={"category": "parent"}).status_code == 404
    assert admin.delete("/api/m1/sources/999999").status_code == 404


# ---------------------------------------------------------------------------
# 草稿 / 定稿 / 重新打开
# ---------------------------------------------------------------------------
def test_put_doc_conflict_returns_server_doc(admin, m1db):
    prep = m1db.prep()

    first = admin.put(f"/api/m1/preps/{prep['id']}/doc",
                      json={"rev": prep["rev"], "doc": _doc("第一版")})
    assert first.status_code == 200
    assert first.get_json()["rev"] == prep["rev"] + 1

    second = admin.put(f"/api/m1/preps/{prep['id']}/doc",
                       json={"rev": first.get_json()["rev"], "doc": _doc("第二版")})
    assert second.status_code == 200

    stale = admin.put(f"/api/m1/preps/{prep['id']}/doc",
                      json={"rev": first.get_json()["rev"], "doc": _doc("过期写入")})
    assert stale.status_code == 409
    payload = stale.get_json()
    assert payload["rev"] == second.get_json()["rev"]
    assert payload["doc"]["_block"]["text"] == "第二版"

    assert admin.put(f"/api/m1/preps/{prep['id']}/doc",
                     json={"doc": _doc()}).status_code == 400
    assert "m1.edit" in _actions(m1db.engine)


def test_finalize_blocked_by_safety_then_ack(admin, m1db):
    prep = m1db.prep()
    admin.put(f"/api/m1/preps/{prep['id']}/doc",
              json={"rev": prep["rev"],
                    "doc": _doc(safety=[{"text": "说过不想活了",
                                         "source_ref": "m1_source:1"}])})

    blocked = admin.post(f"/api/m1/preps/{prep['id']}/finalize")
    assert blocked.status_code == 409
    assert "安全提示" in blocked.get_json()["error"]
    assert admin.get(f"/api/m1/preps/{prep['id']}").get_json()["status"] == "draft"

    assert admin.post(f"/api/m1/preps/{prep['id']}/safety-ack").status_code == 200
    done = admin.post(f"/api/m1/preps/{prep['id']}/finalize")
    assert done.status_code == 200
    assert done.get_json()["version"]["kind"] == "final"
    assert done.get_json()["prep"]["status"] == "final"
    assert done.get_json()["prep"]["safety_ack_by"] == m1db.admin_id
    assert {"m1.safety_ack", "m1.final"} <= set(_actions(m1db.engine))

    # 已定稿后草稿不可直接改写
    assert admin.put(f"/api/m1/preps/{prep['id']}/doc",
                     json={"rev": done.get_json()["prep"]["rev"],
                           "doc": _doc("改定稿")}).status_code == 409


def test_reopen_keeps_final_and_allows_editing(admin, m1db):
    prep = m1db.prep()
    admin.put(f"/api/m1/preps/{prep['id']}/doc",
              json={"rev": prep["rev"], "doc": _doc("定稿内容")})
    final = admin.post(f"/api/m1/preps/{prep['id']}/finalize").get_json()["version"]

    reopened = admin.post(f"/api/m1/preps/{prep['id']}/reopen")
    assert reopened.status_code == 200
    edit = reopened.get_json()["version"]
    assert edit["kind"] == "edit"
    assert edit["n"] > final["n"]
    assert edit["doc"]["_block"]["text"] == "定稿内容"
    assert reopened.get_json()["prep"]["status"] == "review"

    rev = reopened.get_json()["prep"]["rev"]
    saved = admin.put(f"/api/m1/preps/{prep['id']}/doc",
                      json={"rev": rev, "doc": _doc("改过的草稿")})
    assert saved.status_code == 200

    # final 版本内容不受影响
    detail = admin.get(f"/api/m1/preps/{prep['id']}").get_json()
    assert detail["doc"]["_block"]["text"] == "改过的草稿"
    from m1 import store
    assert store.get_version(final["id"])["doc"]["_block"]["text"] == "定稿内容"


# ---------------------------------------------------------------------------
# 详情：KB / 固定文本 / Y4 条目（无 raw）
# ---------------------------------------------------------------------------
def test_detail_hides_y4_raw(admin, m1db, monkeypatch):
    prep = m1db.prep()
    monkeypatch.setattr(sources, "_y4", lambda student_id: {
        "report_id": 12, "date": "2026-09-02", "complete": True, "six_am": None,
        "items": [{"id": "y4-013", "source": "y4", "source_ref": "report:12",
                   "date": "2026-09-02", "kind": "indirect", "group": "Y4",
                   "text": "焦虑/安详：需关注", "quote": "",
                   "abilities": ["R2.1"], "band": "需关注", "raw": 7}],
    })

    payload = admin.get(f"/api/m1/preps/{prep['id']}").get_json()
    assert payload["ok"] is True
    assert payload["rev"] == prep["rev"]
    assert payload["status"] == "draft"

    item = payload["y4_items"][0]
    assert item == {"id": "y4-013", "text": "焦虑/安详：需关注",
                    "abilities": ["R2.1"], "band": "需关注"}
    assert "raw" not in json.dumps(payload["y4_items"])
    assert "raw" not in json.dumps(payload)

    # 知识库能力行 + 固定框架文字（P1 落地后由 load_kb 提供）
    abilities = payload["kb"]["abilities"]
    assert len(abilities) == 18
    assert set(abilities[0]) == {"code", "name", "dim", "gap_note", "ask",
                                 "indicator_note"}
    assert payload["kb"]["dims"]
    assert payload["fixed"]
    assert payload["auto"]["questionnaires"] == []


def test_detail_starts_without_doc(admin, m1db):
    prep = m1db.prep()
    payload = admin.get(f"/api/m1/preps/{prep['id']}").get_json()
    assert payload["doc"] is None
    assert payload["sources"] == []
    assert payload["auto"]["first_touch"]["present"] is False


# ---------------------------------------------------------------------------
# 导出 / 页面占位
# ---------------------------------------------------------------------------
def test_export_logs_audit(admin, m1db):
    prep = m1db.prep()
    res = admin.post(f"/api/m1/preps/{prep['id']}/export")
    assert res.status_code == 200
    assert res.get_json() == {"ok": True}
    assert "m1.export" in _actions(m1db.engine)


def test_pages_render_placeholder(alice, m1db):
    prep = m1db.prep()
    home = alice.get("/m1?student=%d" % m1db.student_id)
    assert home.status_code == 200
    assert "text/html" in home.content_type
    assert alice.get(f"/m1/preps/{prep['id']}").status_code == 200
    assert alice.get(f"/m1/preps/{prep['id']}/print").status_code == 200
    assert alice.get("/m1/preps/999999").status_code == 404
