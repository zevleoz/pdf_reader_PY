"""B2 报告数值编辑：db.update_report_values + POST /api/reports/<id>/values。

覆盖：单值保存、未知编号/非数值/隐藏编号整批拒绝、重复保存不重复记日志、
以及保存后 regenerate 用新值重写 data/report_data.json。
"""
from __future__ import annotations

import json
from datetime import date

import pytest
from flask import Flask
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

import app_utils
import db as _db
from blueprints import reports as reports_api


class EditDB:
    def __init__(self, engine, root):
        self.engine = engine
        self.root = root
        self.student_id = None
        self.report_id = None

    def seed(self):
        points = [
            {"code": "068", "label": "学习动机-自我效能感", "type": "number",
             "value": "6.2", "source_pdf": "B3"},
            {"code": "069", "label": "学习方法与策略-学习深层方法与策略",
             "type": "number", "value": "5.4", "source_pdf": "B3"},
            {"code": "071", "label": "学习方法与策略-学习自我调节", "type": "number",
             "value": "", "source_pdf": "B3"},
            {"code": "100", "label": "职业价值观-成就感", "type": "number",
             "value": "4.1", "source_pdf": "B6"},
            {"code": "110", "label": "职业价值观排序1", "type": "string",
             "value": "成就感", "source_pdf": "B6"},
        ]
        raw = {
            "student": {"name": "林同学", "grade": "10"},
            "schema_124": points,
        }
        with Session(self.engine) as sess:
            student = _db.Student(student_code="Y4-9301", name="林同学",
                                  grade="10", advisor_name="Alice")
            sess.add(student)
            sess.commit()
            self.student_id = student.id
            report = _db.Report(
                student_id=student.id,
                report_date=date(2026, 11, 7),
                pdf_path="report.pdf",
                data_json=json.dumps(raw, ensure_ascii=False),
            )
            sess.add(report)
            sess.commit()
            self.report_id = report.id


@pytest.fixture()
def editdb(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'value_edits.db'}")

    @event.listens_for(engine, "connect")
    def _enable_fk(dbapi_connection, _record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    _db.Base.metadata.create_all(
        engine, tables=[_db.Student.__table__, _db.Report.__table__])
    monkeypatch.setattr(_db, "engine", engine)
    monkeypatch.setattr(app_utils, "is_authenticated", lambda: True)
    helper = EditDB(engine, tmp_path)
    helper.seed()
    yield helper
    engine.dispose()


@pytest.fixture()
def client(editdb):
    app = Flask(__name__)
    app.config.update(SECRET_KEY="test-secret", TESTING=True)
    app.register_blueprint(reports_api.bp)
    with app.test_client() as c:
        with c.session_transaction() as sess:
            sess["user_id"] = 1
            sess["role"] = "admin"
            sess["advisor_name"] = "Alice"
            sess["display_name"] = "测试管理员"
            sess["detail_level"] = "full"
        yield c


def _raw(report_id):
    return _db.get_report_raw(report_id)["raw"]


def _values(raw):
    return {it["code"]: it["value"] for it in raw["schema_124"]}


def _post_edits(client, report_id, edits):
    return client.post(f"/api/reports/{report_id}/values",
                       json={"edits": edits})


def test_save_changes_only_that_item_and_logs_one_edit(client, editdb):
    resp = _post_edits(client, editdb.report_id, {"068": "8.1"})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    assert body["changed"] == ["068"]

    raw = _raw(editdb.report_id)
    values = _values(raw)
    assert values["068"] == "8.1"
    assert values["069"] == "5.4"
    assert len(raw["edits"]) == 1
    entry = raw["edits"][0]
    assert entry["code"] == "068"
    assert entry["old"] == "6.2"
    assert entry["new"] == "8.1"
    assert entry["by"] == "测试管理员"
    assert entry["at"]


def test_unknown_code_is_rejected_and_nothing_changes(client, editdb):
    before = _raw(editdb.report_id)

    resp = _post_edits(client, editdb.report_id, {"999": "1"})
    assert resp.status_code == 400
    assert "999" in resp.get_json()["error"]

    after = _raw(editdb.report_id)
    assert after["schema_124"] == before["schema_124"]
    assert after.get("edits", []) == []


def test_non_number_for_number_item_is_rejected_and_nothing_changes(client, editdb):
    before = _raw(editdb.report_id)

    resp = _post_edits(client, editdb.report_id,
                       {"068": "8.1", "069": "不是数字"})
    assert resp.status_code == 400
    assert "069" in resp.get_json()["error"]

    after = _raw(editdb.report_id)
    # 整批拒绝：068 也不能被写入
    assert after["schema_124"] == before["schema_124"]
    assert after.get("edits", []) == []


def test_hidden_code_is_rejected_and_nothing_changes(client, editdb):
    before = _raw(editdb.report_id)

    resp = _post_edits(client, editdb.report_id, {"100": "9.9"})
    assert resp.status_code == 400

    after = _raw(editdb.report_id)
    assert after["schema_124"] == before["schema_124"]
    assert after.get("edits", []) == []


def test_saving_same_value_twice_adds_no_second_edit(client, editdb):
    first = _post_edits(client, editdb.report_id, {"068": "8.1"})
    assert first.status_code == 200
    assert first.get_json()["changed"] == ["068"]

    second = _post_edits(client, editdb.report_id, {"068": "8.1"})
    assert second.status_code == 200
    assert second.get_json()["changed"] == []

    raw = _raw(editdb.report_id)
    assert len(raw["edits"]) == 1
    assert _values(raw)["068"] == "8.1"


def test_regenerate_writes_edited_value_to_report_data_json(
        client, editdb, monkeypatch):
    resp = _post_edits(client, editdb.report_id, {"068": "8.1"})
    assert resp.status_code == 200

    data_dir = editdb.root / "data"
    out_dir = editdb.root / "output"
    data_dir.mkdir()
    out_dir.mkdir()
    (out_dir / "凭远Y4评测报告_林同学.pdf").write_bytes(b"%PDF-1.4")
    (out_dir / "凭远Y4评测报告_v2_林同学.pdf").write_bytes(b"%PDF-1.4")

    monkeypatch.setattr(reports_api, "DATA_DIR", data_dir)
    monkeypatch.setattr(reports_api, "OUTPUT_DIR", out_dir)
    monkeypatch.setattr(reports_api, "_job_running", lambda: False)
    monkeypatch.setattr(reports_api, "apply_report_data", lambda: {})
    monkeypatch.setattr(reports_api._generate_module, "main", lambda: None)

    regen = client.post(f"/api/reports/{editdb.report_id}/regenerate")
    assert regen.status_code == 200

    written = json.loads((data_dir / "report_data.json").read_text(encoding="utf-8"))
    assert _values(written)["068"] == "8.1"


@pytest.mark.parametrize("bad", ["nan", "inf", "-inf"])
def test_non_finite_number_rejected(editdb, bad):
    with pytest.raises(ValueError):
        _db.update_report_values(editdb.report_id, {"068": bad}, "t")
