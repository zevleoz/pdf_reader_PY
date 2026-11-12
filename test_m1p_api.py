"""M1P-P1：资料分栏、列表摘要、学生页 overview、定稿不再被核对标记拦住。

10 个用例对应 README 的 10 条夹具要求；库与文档辅助函数复用
``test_m1_store``，登录方式复用 ``test_m1_pipeline``。
"""
from __future__ import annotations

import json

import pytest
from flask import Flask

import m1.report_pipeline as report_pipeline
import m1.report_store as rstore
import m1.sources as sources
import m1.store as store
from app_utils import BASE_DIR
from test_m1_pipeline import _login
from test_m1_store import _doc, m1db  # noqa: F401  临时库与文档构造


@pytest.fixture()
def client(m1db, monkeypatch):  # noqa: F811
    import app_utils
    from blueprints import m1 as m1_api
    from blueprints import m1_report

    monkeypatch.setattr(app_utils, "is_authenticated", lambda: True)
    app = Flask(__name__, template_folder=str(BASE_DIR / "templates"))
    app.secret_key = "test-secret"
    app.register_blueprint(m1_api.bp)
    app.register_blueprint(m1_report.bp)
    return app.test_client()


def _auto():
    return {
        "y4": {"complete": True, "date": "2026-09-02"},
        "first_touch": {"present": True, "date": "2026-10-12"},
        "questionnaires": [{"code": "ERQ", "status": "已完成"},
                           {"code": "ANX", "status": "未取得"}],
    }


def _overview(client, prep_id):
    return client.get("/api/m1/preps/%d/overview" % prep_id).get_json()


# ---------------------------------------------------------------------------
# 1. 列表摘要
# ---------------------------------------------------------------------------
def test_list_carries_me_materials_and_report_state(client, m1db, monkeypatch):
    prep = m1db.prep()
    sources.add_text(prep["id"], "家长反馈：最近状态还行。", "parent")
    rstore.get_or_create_report(prep["id"], m1db.alice_id)
    monkeypatch.setattr(sources, "_first_touch",
                        lambda sid: {"present": True, "date": "2026-10-12",
                                     "text": "x", "session_id": 3})
    _login(client, m1db.alice_id, "advisor", "Alice")

    body = client.get("/api/m1/preps").get_json()
    assert body["me"] == m1db.alice_id
    row = [item for item in body["preps"] if item["id"] == prep["id"]][0]
    assert row["materials"] == ["Y4", "First Touch", "家长反馈"]
    assert row["report"] == {"status": "draft", "label": "未开始", "started": False}


# ---------------------------------------------------------------------------
# 2–3. 建会接受会议信息
# ---------------------------------------------------------------------------
def test_create_without_meeting_info_still_works(client, m1db):
    _login(client, m1db.alice_id, "advisor", "Alice")
    res = client.post("/api/m1/preps", json={"student_id": m1db.student_id})

    assert res.status_code == 201
    prep = res.get_json()["prep"]
    assert prep["meeting_date"] == "" and prep["duration"] == 60


def test_create_rejects_bad_meeting_date_and_duration(client, m1db):
    _login(client, m1db.alice_id, "advisor", "Alice")
    assert client.post("/api/m1/preps", json={
        "student_id": m1db.student_id, "meeting_date": "10/20"}).status_code == 400
    assert client.post("/api/m1/preps", json={
        "student_id": m1db.student_id, "duration": "90"}).status_code == 400

    res = client.post("/api/m1/preps", json={
        "student_id": m1db.student_id, "meeting_date": "2026-10-20", "duration": 90})
    assert res.status_code == 201
    saved = store.get_prep(res.get_json()["prep"]["id"])
    assert saved["meeting_date"] == "2026-10-20" and saved["duration"] == 90


# ---------------------------------------------------------------------------
# 4. 定稿返回未核对数量
# ---------------------------------------------------------------------------
def test_finalize_returns_the_open_flag_count_and_ack_clears_it(client, m1db):
    prep = m1db.prep()
    doc = _doc()
    doc["fact_flags"] = [{"id": "ff1", "kind": "unsupported",
                          "sentence": "待核对：某一句。", "block_id": "b1",
                          "acked": False}]
    store.save_doc(prep["id"], store.get_prep(prep["id"])["rev"], doc)
    _login(client, m1db.alice_id, "advisor", "Alice")

    res = client.post("/api/m1/preps/%d/finalize" % prep["id"])
    assert res.status_code == 200, res.get_json()
    assert res.get_json()["open_flags"] == 1

    assert client.post("/api/m1/preps/%d/reopen" % prep["id"]).status_code == 200
    ack = client.post("/api/m1/preps/%d/fact-flags/ff1/ack" % prep["id"])
    assert ack.status_code == 200 and ack.get_json()["ok"]

    res = client.post("/api/m1/preps/%d/finalize" % prep["id"])
    assert res.status_code == 200, res.get_json()
    assert res.get_json()["open_flags"] == 0


# ---------------------------------------------------------------------------
# 5–6. overview：自动来源与会前准备
# ---------------------------------------------------------------------------
def test_overview_explains_a_draft_prep_without_a_doc(client, m1db, monkeypatch):
    prep = m1db.prep()
    monkeypatch.setattr(sources, "auto_sources", lambda sid: _auto())
    _login(client, m1db.alice_id, "advisor", "Alice")

    body = _overview(client, prep["id"])
    assert body["auto"] == {
        "y4": {"complete": True, "date": "2026-09-02"},
        "first_touch": {"present": True, "date": "2026-10-12"},
        "questionnaires": {"done": 1, "total": 2},
    }
    part = body["prep_part"]
    assert part["status"] == "draft" and part["label"] == "待生成"
    assert part["has_doc"] is False and part["version_n"] == 0
    assert part["priority"] == []
    assert part["materials"] == ["Y4", "First Touch", "补充问卷 1/2"]


def test_overview_returns_priority_names_from_the_kb(client, m1db, monkeypatch):
    prep = m1db.prep()
    monkeypatch.setattr(sources, "auto_sources", lambda sid: _auto())
    doc = _doc()
    doc["priority"] = [{"code": "R1.1", "hypothesis": {"id": "h1", "text": "x"}},
                       {"code": "R9.9"}]
    store.save_doc(prep["id"], store.get_prep(prep["id"])["rev"], doc)
    _login(client, m1db.alice_id, "advisor", "Alice")

    body = _overview(client, prep["id"])
    assert body["prep_part"]["priority"] == [
        {"code": "R1.1", "name": "情绪识别与身体觉察"}]
    assert body["prep_part"]["has_doc"] is True
    assert body["prep_part"]["version_n"] >= 1


# ---------------------------------------------------------------------------
# 7. overview：操作记录
# ---------------------------------------------------------------------------
def test_overview_activity_lists_this_preps_history(client, m1db, monkeypatch):
    monkeypatch.setattr(sources, "auto_sources", lambda sid: _auto())
    _login(client, m1db.alice_id, "advisor", "Alice")
    res = client.post("/api/m1/preps", json={"student_id": m1db.student_id})
    prep = res.get_json()["prep"]
    store.save_doc(prep["id"], store.get_prep(prep["id"])["rev"], _doc())
    assert client.post("/api/m1/preps/%d/finalize" % prep["id"]).status_code == 200

    body = _overview(client, prep["id"])
    assert [(row["text"], row["auto"]) for row in body["activity"]] == [
        ("定稿会前准备", False), ("添加到心有灵析", False)]
    assert all(row["actor"] == "Alice" for row in body["activity"])


# ---------------------------------------------------------------------------
# 8. overview：会后报告
# ---------------------------------------------------------------------------
def test_overview_keeps_the_transcript_out_of_the_payload(client, m1db, monkeypatch):
    prep = m1db.prep()
    monkeypatch.setattr(sources, "auto_sources", lambda sid: _auto())
    report = rstore.get_or_create_report(prep["id"], m1db.alice_id)
    rstore.set_transcript(report["id"], text="逐字稿正文", filename="t.txt")
    _login(client, m1db.alice_id, "advisor", "Alice")

    body = _overview(client, prep["id"])
    part = body["report_part"]
    assert part["started"] is True
    assert part["status"] == "draft" and part["label"] == "待生成"
    assert part["transcript_filename"] == "t.txt"
    assert part["has_version"] is False and part["updated_at"]
    assert "逐字稿" in part["materials"]

    payload = client.get("/api/m1/preps/%d/report" % prep["id"]).get_json()
    assert payload["inputs"]["others"] == []
    assert "transcript_text" not in json.dumps(body, ensure_ascii=False)


# ---------------------------------------------------------------------------
# 9. 资料分栏
# ---------------------------------------------------------------------------
def test_report_uploads_stay_out_of_the_prep_and_cannot_move_in(client, m1db):
    prep = m1db.prep()
    src = sources.add_text(prep["id"], "会后补充资料", "report_other")
    with pytest.raises(ValueError):
        store.update_source(src["id"], category="parent")
    _login(client, m1db.alice_id, "advisor", "Alice")

    body = client.get("/api/m1/preps/%d" % prep["id"]).get_json()
    assert body["ok"] is True
    assert [row["category"] for row in body["sources"]] == []


# ---------------------------------------------------------------------------
# 10. 报告输入带问卷进度
# ---------------------------------------------------------------------------
def test_report_inputs_count_uploaded_questionnaires(client, m1db, monkeypatch):
    prep = m1db.prep()
    monkeypatch.setattr(sources, "auto_sources", lambda sid: _auto())
    _login(client, m1db.alice_id, "advisor", "Alice")

    body = client.get("/api/m1/preps/%d/report" % prep["id"]).get_json()
    assert body["inputs"]["questionnaires"] == {"done": 1, "total": 2}


# ---------------------------------------------------------------------------
# 11. 会前准备的资料不再进入会后报告（D2）
# ---------------------------------------------------------------------------
def test_prep_uploads_no_longer_reach_the_report(client, m1db, monkeypatch):
    prep = m1db.prep()
    sources.add_text(prep["id"], "家长反馈：会前上传标记。", "parent")
    monkeypatch.setattr(sources, "auto_sources", lambda sid: _auto())
    report = rstore.get_or_create_report(prep["id"], m1db.alice_id)
    rstore.set_transcript(report["id"], text="逐字稿正文", filename="t.txt")
    report = rstore.get_report(prep["id"])

    check = report_pipeline.step_check(prep, report)
    assert check["uploads"] == []
    assert "其他补充资料" not in check["source_labels"]

    _login(client, m1db.alice_id, "advisor", "Alice")
    body = client.get("/api/m1/preps/%d/report" % prep["id"]).get_json()
    assert body["inputs"]["others"] == []


# ---------------------------------------------------------------------------
# 12. 路由层禁止跨文档移动资料
# ---------------------------------------------------------------------------
def test_patch_cannot_move_a_prep_source_to_the_report(client, m1db):
    prep = m1db.prep()
    src = sources.add_text(prep["id"], "家长反馈：会前上传标记。", "parent")
    _login(client, m1db.alice_id, "advisor", "Alice")

    res = client.patch("/api/m1/sources/%d" % src["id"],
                       json={"category": "report_other"})
    assert res.status_code == 422
    assert res.get_json()["error"] == "不能把资料移到另一份文档"
    assert store.get_source(src["id"])["category"] == "parent"


# ---------------------------------------------------------------------------
# 13. 复用未定稿准备时保留原有会议信息
# ---------------------------------------------------------------------------
def test_reused_prep_keeps_its_meeting_info(client, m1db):
    _login(client, m1db.alice_id, "advisor", "Alice")
    first = client.post("/api/m1/preps", json={
        "student_id": m1db.student_id, "meeting_date": "2026-11-09"})
    assert first.status_code == 201

    reused = client.post("/api/m1/preps", json={
        "student_id": m1db.student_id, "meeting_date": "2026-12-01", "duration": 90})
    assert reused.status_code == 200
    body = reused.get_json()
    assert body["created"] is False

    saved = store.get_prep(body["prep"]["id"])
    assert saved["meeting_date"] == "2026-11-09"
    assert saved["duration"] == 60


# ---------------------------------------------------------------------------
# 14. overview 的权限与不存在
# ---------------------------------------------------------------------------
def test_overview_access_checks(client, m1db):
    prep = m1db.prep()

    _login(client, m1db.viewer_id, "viewer")
    assert client.get("/api/m1/preps/%d/overview" % prep["id"]).status_code == 403

    other_prep = m1db.prep(m1db.other_student_id, m1db.bob_id)
    _login(client, m1db.alice_id, "advisor", "Alice")
    assert client.get("/api/m1/preps/%d/overview" % other_prep["id"]).status_code == 403
    assert client.get("/api/m1/preps/999999/overview").status_code == 404


# ---------------------------------------------------------------------------
# 15. 安全提示只提示，不拦截定稿（README D6）
# ---------------------------------------------------------------------------
def test_finalize_still_requires_safety_ack(client, m1db):
    prep = m1db.prep()
    store.save_doc(prep["id"], store.get_prep(prep["id"])["rev"],
                   _doc(safety=[{"text": "说过不想活了",
                                 "source_ref": "m1_source:1"}]))
    _login(client, m1db.alice_id, "advisor", "Alice")

    done = client.post("/api/m1/preps/%d/finalize" % prep["id"])
    assert done.status_code == 200
    assert done.get_json()["safety_unacked"] is True
    assert done.get_json()["prep"]["status"] == "final"
    assert done.get_json()["prep"]["safety_ack_at"] is None
