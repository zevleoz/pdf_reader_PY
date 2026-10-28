"""Y4 → M1 证据条目的规则测试（临时 SQLite，不触碰真实库）。"""
from __future__ import annotations

import json
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import data_points
import db as _db
import evaluation_rules
from m1 import y4_evidence

# 一份覆盖知识库全部指标的完整 Y4（值为原始分，测试里只用于推导档位）
BASE_VALUES = {
    "004": 82,
    "011": 7,
    "012": 10,
    "013": 6,
    "014": 12,
    "016": 4.0,
    "017": 3.2,
    "019": 3.8,
    "022": "安全型",
    "023": 30,
    "025": 12,
    "026": 33,
    "027": 20,
    "028": 9,
    "030": 25,
    "053": 5,
    "054": 7,
    "056": 3,
    "060": 3.6,
    "061": 3.0,
    "062": 3.8,
    "063": 88,
    "065": 96,
    "068": 3.2,
    "071": 2.4,
    "079": 5,
    "084": 6,
    "085": 7,
    # 常模平均数
    "125": 3.0, "126": 3.0, "127": 3.0,
    "128": 3.0, "129": 3.0, "130": 3.0,
    "131": 3.0, "132": 3.0, "133": 3.0,
}


class Y4DB:
    def __init__(self, engine):
        self.engine = engine
        self.student_id = None


@pytest.fixture()
def y4db(tmp_path, monkeypatch):
    engine = create_engine("sqlite:///%s" % (tmp_path / "m1_y4.db"))
    _db.Base.metadata.create_all(engine, tables=[
        _db.Student.__table__, _db.Report.__table__, _db.SixAmProfile.__table__,
    ])
    monkeypatch.setattr(_db, "engine", engine)

    helper = Y4DB(engine)
    with Session(engine) as sess:
        student = _db.Student(student_code="Y4-9101", name="测试学生",
                              grade="初二", advisor_name="测试顾问")
        sess.add(student)
        sess.commit()
        helper.student_id = student.id
    yield helper
    engine.dispose()


def _seed_report(helper, overrides=None, day=date(2026, 9, 2)) -> int:
    values = dict(BASE_VALUES)
    values.update(overrides or {})
    schema = [{"code": "072", "value": "SAE"}]
    for code in ("073", "074", "075", "076", "077", "078"):
        schema.append({"code": code, "value": "5"})
    for code, value in values.items():
        schema.append({"code": code, "value": str(value)})
    with Session(helper.engine) as sess:
        report = _db.Report(student_id=helper.student_id, report_date=day,
                            pdf_path="report.pdf",
                            data_json=json.dumps({"student": {}, "schema_124": schema}))
        sess.add(report)
        sess.commit()
        return report.id


def _items(student_id):
    result = y4_evidence.build_y4_evidence(student_id)
    return result, {item["id"]: item for item in result["items"]}


def test_bands_match_evaluation_rules(y4db):
    _seed_report(y4db)
    _result, items = _items(y4db.student_id)
    for code in ("004", "011", "013", "016", "019", "023", "026", "053", "063", "079"):
        label = data_points.POINT_META[code]["label"]
        expected, _note = evaluation_rules.derive_evaluation(
            code, label, BASE_VALUES[code])
        assert items["y4-" + code]["band"] == expected, code


def test_report_level_field_wins(y4db):
    _seed_report(y4db, {"023": 12, "032": "高"})
    _result, items = _items(y4db.student_id)
    # 12 分本身是「偏低」，报告自带档位「高」优先
    assert items["y4-023"]["band"] == "高"


def test_attachment_type_uses_raw_text(y4db):
    _seed_report(y4db)
    _result, items = _items(y4db.student_id)
    assert items["y4-022"]["band"] == "安全型"
    assert items["y4-022"]["text"] == "依恋—同伴类型：安全型"


@pytest.mark.parametrize("raw,band", [
    (9, "高"), (8.9, "较好"), (7.5, "较好"), (6.66, "不低"),
    (5, "偏低"), (4.99, "明显偏低"),
])
def test_career_value_bands_at_boundaries(raw, band):
    assert y4_evidence.band_for("095", {"095": raw}) == band


@pytest.mark.parametrize("code,raw", [
    ("023", 60),      # 依恋信任 1–50
    ("026", 46),      # 依恋沟通 1–45
    ("030", 0),       # 依恋亲近 1–30
    ("009", 61),      # 情绪稳定性总分 0–60
    ("013", 16),      # 情绪稳定性分项 0–15
    ("019", 5.2),     # Big Five 1–5
    ("056", 11),      # 自我概念 0–10
    ("004", 101),     # 百分位 0–100
])
def test_out_of_range_is_unreadable(code, raw):
    assert y4_evidence.band_for(code, {code: raw}) == "无法判读"


def test_missing_norm_is_unreadable(y4db):
    _seed_report(y4db, {"125": ""})
    _result, items = _items(y4db.student_id)
    assert items["y4-060"]["band"] == "无法判读"
    # 同组 061/062 的常模仍在，照常判读
    assert items["y4-061"]["band"] == "不低"


def test_item_shape(y4db):
    _seed_report(y4db)
    result = y4_evidence.build_y4_evidence(y4db.student_id)
    assert result["complete"] is True
    assert result["date"] == "2026-09-02"
    assert result["report_id"] is not None
    for item in result["items"]:
        assert item["source"] == "y4"
        assert item["group"] == "Y4"
        assert item["kind"] == "indirect"
        assert item["quote"] == ""
        assert item["abilities"]
        assert item["source_ref"].startswith("report:")
        assert item["text"].endswith("：" + item["band"])


def test_item_text_has_no_raw_values(y4db):
    _seed_report(y4db)
    result = y4_evidence.build_y4_evidence(y4db.student_id)
    for item in result["items"]:
        raw = item["raw"]
        if isinstance(raw, (int, float)) and not isinstance(raw, bool):
            assert str(raw) not in item["text"], item["text"]


def test_no_complete_report_returns_empty(y4db):
    with Session(y4db.engine) as sess:
        student = _db.Student(student_code="Y4-9102", name="无报告学生")
        sess.add(student)
        sess.commit()
        student_id = student.id
    result = y4_evidence.build_y4_evidence(student_id)
    assert result == {"report_id": None, "date": None, "items": [],
                      "six_am": None, "complete": False}


def test_six_am_summary_is_y4_group(y4db):
    report_id = _seed_report(y4db)
    _db.add_six_am_profile(y4db.student_id, report_id,
                           json.dumps({"dimensions": {"A1": {"state": "Watch"}}}),
                           version=3)
    result = y4_evidence.build_y4_evidence(y4db.student_id)
    assert result["six_am"]["group"] == "Y4"
    assert result["six_am"]["version"] == 3
    assert result["six_am"]["states"]["A1"] == "Watch"
    assert "不单独计为证据" in result["six_am"]["note"]


def test_no_six_am_profile_is_none(y4db):
    _seed_report(y4db)
    result = y4_evidence.build_y4_evidence(y4db.student_id)
    assert result["six_am"] is None
