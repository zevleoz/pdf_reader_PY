"""M1R-P7：会后报告界面不再有 AI 复核 / 安全确认的必经步骤，只保留一个正式发布。

全部使用虚构数据与假模型；不访问真实模型或服务器。
"""
from __future__ import annotations

import copy

from sqlalchemy.orm import Session

from app_utils import BASE_DIR
from m1 import report_store
from test_m1_report_core import (admin_login, generated_via_api, client, fake,  # noqa: F401
                                 inline_jobs, rdb, url)
from test_m1_report_screen import _login, _seed_report
from test_m1_report_screen import client as screen_client  # noqa: F401
from test_m1_store import m1db  # noqa: F401

WORKSPACE_JS = (BASE_DIR / "static" / "m1" / "report_workspace.js").read_text(encoding="utf-8")
EDIT_JS = (BASE_DIR / "static" / "m1" / "report_edit.js").read_text(encoding="utf-8")


def test_workspace_html_has_only_final_publish(screen_client, m1db):  # noqa: F811
    prep = _seed_report(m1db)
    report = report_store.get_report(prep["id"])
    with Session(m1db.engine) as sess:
        sess.get(report_store.M1Report, report["id"]).status = "ai_draft"
        sess.commit()
    _login(screen_client, m1db.admin_id, "admin")
    html = screen_client.get(f"/m1/preps/{prep['id']}/report").get_data(as_text=True)
    assert 'id="r4Publish"' in html
    assert "r4Approve" not in html
    assert "r4SafetyAck" not in html
    assert "已知悉并人工核实" not in html
    assert "正式发布前导出的 PDF" in html


def test_workspace_js_has_no_mandatory_review_steps():
    for text in ("已知悉并人工核实", "我已核对这条，确认保留", "r4Approve",
                 "r4SafetyAck", "/approve", "/safety-ack", "/confirm-flag"):
        assert text not in WORKSPACE_JS, text
    assert "'ai_draft', 'needs_check', 'reviewing', 'approved'].indexOf(status)" in WORKSPACE_JS
    assert "报告还不完整（" in WORKSPACE_JS
    assert "可以导出草稿，也可以直接正式发布。" in WORKSPACE_JS


def test_edit_js_diagnostics_are_information_only():
    assert "/confirm-flag" not in EDIT_JS
    assert "confirmFlag" not in EDIT_JS
    assert "仅供参考" in EDIT_JS
    assert "没有必须补全的地方" in EDIT_JS


def test_api_ai_draft_publishes_without_ack(client, rdb, fake, inline_jobs):  # noqa: F811
    generated_via_api(client, rdb, fake, inline_jobs)
    assert report_store.get_report(rdb.prep_row["id"])["status"] == "ai_draft"
    res = client.post(url(rdb, "/publish"))
    assert res.status_code == 200
    assert res.get_json()["report"]["status"] == "published"


def test_api_structural_block_still_refused(client, rdb, fake, inline_jobs):  # noqa: F811
    generated_via_api(client, rdb, fake, inline_jobs)
    report = report_store.get_report(rdb.prep_row["id"])
    version = report_store.current_version(report["id"])
    doc = copy.deepcopy(version["doc"])
    doc["portrait"]["R1"]["text"] = ""
    report_store.add_version(
        report["id"], y4_ratings=version["y4_ratings"], evidence=version["evidence"],
        ai_doc=doc, doc=copy.deepcopy(doc), checks=[], manifest=version["manifest"],
        status="ai_draft")
    res = client.post(url(rdb, "/publish"))
    assert res.status_code == 400
    assert "阻断" in res.get_json()["error"]
