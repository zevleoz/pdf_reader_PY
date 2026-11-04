"""M1 会后报告 §9：AI 质量与安全诊断不阻断，完整草稿可直接最终发布。

全部使用虚构数据与假模型；不访问真实模型或服务器。
"""
from __future__ import annotations

import copy
import json

from sqlalchemy.orm import Session

from m1 import report_checks, report_kb, report_store
from test_m1_report_core import (admin_login, doc_put, generated_via_api,  # noqa: F401
                                 generate, client, fake, inline_jobs, rdb, url)
from test_m1_store import m1db  # noqa: F401

UNSUPPORTED_SENTENCE = "学生下课后在教室待着。"
UNSUPPORTED_PATH = ["dims", "R1", "abilities", "R1.1", "meeting"]


def _fact_unsupported(rdb, fake):
    """生成一份带 fact_unsupported 信息的草稿。"""
    fake.unsupported = ("下课",)
    fake.overrides = {"R1.1": {"meeting": {"sentences": [
        {"text": UNSUPPORTED_SENTENCE, "evidence_ids": ["e1"], "kind": "fact"}]}}}
    return generate(rdb)


def test_ai_and_safety_diagnostics_are_not_blocking(rdb, fake):
    _report, version = _fact_unsupported(rdb, fake)
    report = report_store.get_report(rdb.prep_row["id"])
    assert report["status"] == "ai_draft"
    shown = dict(report, safety=[{"text": "片段", "source_ref": "逐字稿第 9 段"}],
                 safety_ack_at=None)
    checks = report_checks.run_checks(shown, version, first_touch_text="")
    for code in ("fact_unsupported", "safety_unacked"):
        hits = [c for c in checks if c["code"] == code]
        assert hits and all(c["level"] == "review" for c in hits)
    assert report_checks.blocking(checks) == []


def test_publish_directly_from_ai_draft_with_diagnostics(client, rdb, fake, inline_jobs):
    _fact_unsupported(rdb, fake)
    admin_login(client, rdb)
    payload = client.get(url(rdb)).get_json()
    assert payload["report"]["status"] == "ai_draft"
    assert any(c["code"] == "fact_unsupported" and c["level"] == "review"
               for c in payload["checks"])
    res = client.post(url(rdb, "/publish"))
    assert res.status_code == 200 and res.get_json()["report"]["status"] == "published"


def test_legacy_needs_check_publish_does_not_require_safety_ack(client, rdb, fake, inline_jobs):
    payload = generated_via_api(client, rdb, fake, inline_jobs)
    report = report_store.get_report(rdb.prep_row["id"])
    with Session(rdb.engine) as sess:
        row = sess.get(report_store.M1Report, report["id"])
        row.status = "needs_check"
        row.safety = json.dumps([{"text": "片段", "source_ref": "逐字稿第 9 段"}],
                                ensure_ascii=False)
        row.safety_ack_at = None
        sess.commit()
    assert payload["report"]["safety_ack_at"] is None
    res = client.post(url(rdb, "/publish"))
    assert res.status_code == 200 and res.get_json()["report"]["status"] == "published"


def test_generating_or_missing_version_cannot_publish(client, rdb, fake, inline_jobs):
    admin_login(client, rdb)
    assert client.post(url(rdb, "/publish")).status_code == 409
    generated_via_api(client, rdb, fake, inline_jobs)
    report = report_store.get_report(rdb.prep_row["id"])
    report_store.set_status(report["id"], "generating")
    assert client.post(url(rdb, "/publish")).status_code == 409
    assert report_store.get_report(rdb.prep_row["id"])["status"] == "generating"


def test_structurally_incomplete_draft_still_cannot_publish(client, rdb, fake, inline_jobs):
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
    assert report_store.get_report(rdb.prep_row["id"])["status"] == "ai_draft"


TAGS_PATH = ["dims", "R1", "abilities", "R1.1", "tags"]


def test_manual_tags_ignore_ai_combination_rules(client, rdb, fake, inline_jobs):
    payload = generated_via_api(client, rdb, fake, inline_jobs)
    rev = payload["report"]["rev"]
    combos = [
        (["信息不足", "积极资源"], ["信息不足", "积极资源"]),
        (["积极资源", "确认发展需求"], ["积极资源", "确认发展需求"]),
        (["积极资源", "暂未发现"], ["积极资源", "暂未发现"]),
        (report_kb.tag_names(), report_kb.tag_names()),
        ([], []),
        (["可能存在", "积极资源", "可能存在"], ["可能存在", "积极资源"]),
    ]
    for value, expected in combos:
        res = doc_put(client, rdb, rev, [{"path": TAGS_PATH, "value": value}])
        assert res.status_code == 200, (value, res.get_json())
        body = res.get_json()
        rev = body["rev"]
        row = client.get(url(rdb)).get_json()["doc"]["dims"]["R1"]["abilities"]["R1.1"]
        assert row["tags"] == expected and row["tags_src"] == "edited"
        for code in ("no_tag", "tag_invalid", "need_speaker",
                     "double_tag_evidence", "tag_evidence"):
            hits = [c for c in body["checks"] if c["code"] == code
                    and c["path"][:4] == TAGS_PATH[:4]]
            assert not hits, (value, code, hits)


def test_unchanged_manual_tags_become_edited(client, rdb, fake, inline_jobs):
    generated_via_api(client, rdb, fake, inline_jobs)
    report = report_store.get_report(rdb.prep_row["id"])
    version = report_store.current_version(report["id"])
    doc = copy.deepcopy(version["doc"])
    row = doc["dims"]["R1"]["abilities"]["R1.1"]
    row["tags"] = ["信息不足", "积极资源"]
    row["tags_src"] = "ai"
    report_store.add_version(
        report["id"], y4_ratings=version["y4_ratings"], evidence=version["evidence"],
        ai_doc=copy.deepcopy(doc), doc=doc, checks=[], manifest=version["manifest"],
        status="ai_draft")

    rev = client.get(url(rdb)).get_json()["report"]["rev"]
    res = doc_put(client, rdb, rev, [{"path": TAGS_PATH, "value": ["信息不足", "积极资源"]}])
    assert res.status_code == 200, res.get_json()
    body = res.get_json()
    saved = client.get(url(rdb)).get_json()["doc"]["dims"]["R1"]["abilities"]["R1.1"]
    assert saved["tags"] == ["信息不足", "积极资源"] and saved["tags_src"] == "edited"
    for code in ("no_tag", "tag_invalid", "need_speaker",
                 "double_tag_evidence", "tag_evidence"):
        hits = [c for c in body["checks"] if c["code"] == code
                and c["path"][:4] == TAGS_PATH[:4]]
        assert not hits, (code, hits)


def test_ai_generated_tags_still_follow_protocol(rdb, fake):
    _report, version = generate(rdb)
    doc = copy.deepcopy(version["doc"])
    row = doc["dims"]["R1"]["abilities"]["R1.1"]
    row["tags"] = ["信息不足", "积极资源"]
    row["tags_src"] = "ai"
    checks = report_checks.run_checks(
        {"transcript_text": "任意文本"}, dict(version, doc=doc))
    assert any(c["code"] == "tag_invalid" for c in checks)


def test_cover_y4_source_and_internal_manifest(rdb, fake):
    _report, version = generate(rdb)
    assert version["doc"]["meta"]["evidence_sources"] == "Y4 测评"
    assert "M1 First Meeting 逐字稿" in version["manifest"]["sources"]


def test_regeneration_keeps_saved_grade_and_school(client, rdb, fake, inline_jobs):
    admin_login(client, rdb)
    _report, version = generate(rdb)
    rev = report_store.get_report(rdb.prep_row["id"])["rev"]
    res = doc_put(client, rdb, rev, [
        {"path": ["meta", "grade"], "value": "高一"},
        {"path": ["meta", "school"], "value": "新示例学校"},
    ])
    assert res.status_code == 200, res.get_json()
    _report, regenerated = generate(rdb)
    assert regenerated["doc"]["meta"]["grade"] == "高一"
    assert regenerated["doc"]["meta"]["school"] == "新示例学校"


def test_initial_cover_grade_and_school_saved_before_first_generation(client, rdb, fake, inline_jobs):
    import db as _db

    admin_login(client, rdb)
    res = doc_put(client, rdb, 1, [
        {"path": ["meta", "grade"], "value": "初三"},
        {"path": ["meta", "school"], "value": "首次生成前学校"},
    ])
    assert res.status_code == 200, res.get_json()
    with Session(rdb.engine) as sess:
        student = sess.get(_db.Student, rdb.student_id)
        assert student.grade == "初三"
        assert student.school == "首次生成前学校"
    _report, version = generate(rdb)
    assert version["doc"]["meta"]["grade"] == "初三"
    assert version["doc"]["meta"]["school"] == "首次生成前学校"
