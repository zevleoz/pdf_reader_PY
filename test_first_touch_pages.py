"""First Touch 分区外壳：首页 / 聊天中心 / 指南 / 归档 / 手动建档 / Y4 导入。"""
from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

import app_utils
import db as _db
import growth_talk_store as store
from test_copilot_routes import client, login_as, qdb  # noqa: F401


def _seed_report(qdb, student_id, day=1):
    with Session(qdb.engine) as sess:
        report = _db.Report(student_id=student_id,
                            report_date=date(2026, 10, day),
                            pdf_path="report.pdf", data_json="{}")
        sess.add(report)
        sess.commit()
        return report.id


def test_nav_group_registered():
    keys = [group["key"] for group in app_utils.ADMIN_NAV]
    assert "first_touch" in keys
    group = next(g for g in app_utils.ADMIN_NAV if g["key"] == "first_touch")
    assert [item["href"] for item in group["links"]] == [
        "/first-touch", "/first-touch/copilot", "/first-touch/guide"]


def test_home_page_renders(client, qdb):
    login_as(client, qdb)
    resp = client.get("/first-touch")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "First Touch" in html
    assert "林同学" in html


def test_home_page_hides_other_advisor_students(client, qdb):
    login_as(client, qdb)
    html = client.get("/first-touch").get_data(as_text=True)
    assert "陈同学" not in html


def test_chat_picker_redirects_home(client, qdb):
    login_as(client, qdb)
    qdb.session()
    resp = client.get("/first-touch/copilot")
    assert resp.status_code == 302
    assert resp.headers["Location"] == "/first-touch"


def test_chat_page_redirects_workspace(client, qdb):
    login_as(client, qdb)
    qdb.session()
    resp = client.get(f"/first-touch/copilot/{qdb.student_id}")
    assert resp.status_code == 302
    assert resp.headers["Location"] == f"/first-touch/students/{qdb.student_id}"


def test_guide_page_renders(client, qdb):
    login_as(client, qdb)
    resp = client.get("/first-touch/guide")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "初谈访谈与证据指南" in html
    assert "深挖校内科目" in html


def test_archive_requires_admin(client, qdb):
    login_as(client, qdb)
    resp = client.get(f"/first-touch/archive/{qdb.student_id}")
    assert resp.status_code == 403
    assert not store.list_audit(qdb.student_id, action="archive_viewed")


def test_archive_renders_and_writes_audit(client, qdb):
    login_as(client, qdb, role="admin", display_name="Admin")
    resp = client.get(f"/first-touch/archive/{qdb.student_id}")
    assert resp.status_code == 200
    assert "会谈归档" in resp.get_data(as_text=True)
    audits = store.list_audit(qdb.student_id, action="archive_viewed")
    assert audits and audits[0]["actor_id"] == qdb.alice_id


def test_manual_create_student_route_removed(client, qdb):
    login_as(client, qdb)
    resp = client.post("/api/first-touch/students",
                       json={"name": "王同学", "grade": "9"})
    assert resp.status_code in (404, 405)


def test_home_lists_y4_students(client, qdb):
    _seed_report(qdb, qdb.student_id)
    login_as(client, qdb)
    html = client.get("/first-touch").get_data(as_text=True)
    assert "从 Y4 导入" in html
    assert "Y4 1 份" in html


def test_import_y4_route_removed(client, qdb):
    _seed_report(qdb, qdb.student_id)
    login_as(client, qdb)
    resp = client.post("/api/first-touch/import-y4",
                       json={"studentIds": [qdb.student_id]})
    assert resp.status_code in (404, 405)
    assert not store.list_audit(qdb.student_id, action="first_touch_y4_imported")
