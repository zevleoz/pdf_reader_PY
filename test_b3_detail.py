"""Y4-2 Agent A：新版 B3 明细（b3_detail）读取与编辑。视觉 API 一律 mock。"""
import copy
import json
import os
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

import b3_detail
import db as _db
import extract

FIXTURE = Path(__file__).parent / "fixtures" / "b3_detail_sample.json"
SAMPLE = os.environ.get("B3_NEW_SAMPLE")


def _fixture():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


# ---- tiers ----------------------------------------------------------------
@pytest.mark.parametrize("score,code", [
    (0, "T5"), (2.9, "T5"), (3, "T4"), (4.99, "T4"), (5, "T3"), (6.9, "T3"),
    (7, "T2"), (8.99, "T2"), (9, "T1"), (10, "T1")])
def test_tier_score_boundaries(score, code):
    assert b3_detail.tier_score(score)[0] == code


@pytest.mark.parametrize("p,code,label", [
    (100, "T1", "优势表现型"), (90, "T1", "优势表现型"), (89.9, "T2", "良好发展型"),
    (70, "T2", "良好发展型"), (69, "T3", "一般发展型"), (40, "T3", "一般发展型"),
    (39, "T4", "需要支持型"), (20, "T4", "需要支持型"), (19, "T5", "重点支持型"),
    (0, "T5", "重点支持型")])
def test_tier_percentile_boundaries(p, code, label):
    assert b3_detail.tier_percentile(p) == (code, label)


# ---- normalise --------------------------------------------------------------
def test_normalise_fixture():
    d = b3_detail.normalise(_fixture())
    assert d["format"] == "new"
    assert "source" not in d
    assert len(d["practice_items"]) + len(d["exec_items"]) == 37
    assert len(d["practice_dims"]) == 5 and len(d["exec_dims"]) == 7
    assert any(c.startswith("主动提取 ") for c in d["checks"])


def test_normalise_coerces_and_drops():
    d = b3_detail.normalise({
        "motivation_type": " 双高型 ", "bogus": 1,
        "practice_dims": [{"group": "g", "name": "n", "score": "8.5", "x": 1},
                          "junk", {"name": "m", "score": ""}],
        "exec_dims": [{"stage": "s", "name": "n", "score": None}],
    })
    assert d["motivation_type"] == "双高型" and d["method_type"] == ""
    assert d["practice_dims"][0] == {"group": "g", "name": "n", "score": 8.5}
    assert d["practice_dims"][1]["score"] is None
    assert d["exec_dims"][0]["score"] is None
    assert "bogus" not in d and d["practice_items"] == []
    assert b3_detail.normalise(None)["format"] == "new"


def test_check_threshold_is_strictly_above_two():
    base = {"practice_dims": [{"group": "g", "name": "A", "score": 6.0}],
            "practice_items": [{"dim": "A", "name": "i", "desc": "", "score": 4.0}]}
    assert b3_detail.compute_checks(base) == []
    base["practice_dims"][0]["score"] = 6.1
    assert len(b3_detail.compute_checks(base)) == 1


def test_prompt_mentions_every_field():
    p = b3_detail.build_prompt()
    for k in ("motivation_type", "method_type", "practice_dims", "practice_items",
              "exec_dims", "exec_items"):
        assert k in p


# ---- pages ------------------------------------------------------------------
@pytest.mark.skipif(not SAMPLE, reason="B3_NEW_SAMPLE not set")
def test_detail_pages_on_sample():
    assert b3_detail.detail_pages(Path(SAMPLE)) == [10, 12, 14, 15, 16, 17]


# ---- extract path -------------------------------------------------------------
@pytest.mark.skipif(not SAMPLE, reason="B3_NEW_SAMPLE not set")
def test_extract_stores_detail(monkeypatch):
    calls = []

    def fake(slot, imgs, prompt, **kw):
        calls.append((slot, len(imgs), kw))
        return _fixture()
    monkeypatch.setattr(extract, "_call_vision_with_retry", fake)
    monkeypatch.setattr(extract, "_pdf_slot", lambda p: "B3")
    out = extract._extract_b3_detail([Path(SAMPLE)])
    assert len(calls) == 1 and calls[0][1] == 6 and calls[0][2]["required_key"] is None
    assert out["format"] == "new" and len(out["exec_items"]) == 17


@pytest.mark.skipif(not SAMPLE, reason="B3_NEW_SAMPLE not set")
def test_extract_failure_is_swallowed(monkeypatch):
    monkeypatch.setattr(extract, "_pdf_slot", lambda p: "B3")
    monkeypatch.setattr(extract, "_call_vision_with_retry",
                        lambda *a, **k: None)
    assert extract._extract_b3_detail([Path(SAMPLE)]) is None

    def boom(*a, **k):
        raise RuntimeError("api down")
    monkeypatch.setattr(extract, "_call_vision_with_retry", boom)
    assert extract._extract_b3_detail([Path(SAMPLE)]) is None


def test_extract_skips_non_new_b3(monkeypatch):
    monkeypatch.setattr(extract, "_pdf_slot", lambda p: "B3")
    import b3_gauge
    monkeypatch.setattr(b3_gauge, "is_new_b3", lambda p: False)
    assert extract._extract_b3_detail([Path("x.pdf")]) is None


def test_call_vision_without_data_key(monkeypatch):
    monkeypatch.setattr(extract, "_call_dashscope_native_multi",
                        lambda *a, **k: {"content": '{"motivation_type": "双高型"}'})
    assert extract._call_vision_with_retry("s", ["x"], "p", required_key=None) \
        == {"motivation_type": "双高型"}
    monkeypatch.setattr(extract.time, "sleep", lambda s: None)
    assert extract._call_vision_with_retry("s", ["x"], "p", max_retries=0) is None


# ---- b3d.* edits --------------------------------------------------------------
@pytest.fixture()
def rid(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'b3d.db'}")

    @event.listens_for(engine, "connect")
    def _fk(c, _r):
        c.execute("PRAGMA foreign_keys=ON")
    _db.Base.metadata.create_all(
        engine, tables=[_db.Student.__table__, _db.Report.__table__])
    monkeypatch.setattr(_db, "engine", engine)
    raw = {"student": {"name": "林同学"},
           "schema_124": [{"code": "068", "type": "number", "value": "6.2",
                           "label": "x", "source_pdf": "B3"}],
           "b3_detail": b3_detail.normalise(_fixture())}
    with Session(engine) as s:
        st = _db.Student(student_code="Y4-9400", name="林同学", grade="10",
                         advisor_name="A")
        s.add(st)
        s.commit()
        r = _db.Report(student_id=st.id, report_date=date(2026, 11, 8),
                       pdf_path="r.pdf",
                       data_json=json.dumps(raw, ensure_ascii=False))
        s.add(r)
        s.commit()
        yield r.id
    engine.dispose()


def _raw(rid):
    return _db.get_report_raw(rid)["raw"]


def test_b3d_valid_edits_and_log(rid):
    before = _raw(rid)["b3_detail"]
    res = _db.update_report_values(rid, {
        "b3d.motivation_type": "内驱型", "b3d.practice_dims.0": "4.5",
        "b3d.exec_items.1": ""}, "tester")
    assert set(res["changed"]) == {"b3d.motivation_type", "b3d.practice_dims.0",
                                   "b3d.exec_items.1"}
    raw = _raw(rid)
    d = raw["b3_detail"]
    assert d["motivation_type"] == "内驱型"
    assert d["practice_dims"][0]["score"] == 4.5
    assert d["exec_items"][1]["score"] is None
    assert d["practice_dims"][1] == before["practice_dims"][1]
    log = {e["code"]: e for e in raw["edits"]}
    assert log["b3d.motivation_type"]["old"] == "双高型"
    assert log["b3d.practice_dims.0"]["new"] == "4.5" and log["b3d.practice_dims.0"]["by"] == "tester"
    # unchanged value -> no log
    n = len(raw["edits"])
    assert _db.update_report_values(rid, {"b3d.practice_dims.0": "4.5"}, "t")["changed"] == []
    assert len(_raw(rid)["edits"]) == n


@pytest.mark.parametrize("code,val", [
    ("b3d.practice_dims.99", "1"), ("b3d.exec_items.-1", "1"),
    ("b3d.practice_dims.0", "abc"), ("b3d.practice_dims.0", "nan"),
    ("b3d.practice_dims.0", "inf"), ("b3d.bogus", "1"),
    ("b3d.practice_dims", "1")])
def test_b3d_bad_edits_rejected_all_or_nothing(rid, code, val):
    before = _raw(rid)
    with pytest.raises(ValueError):
        _db.update_report_values(rid, {"068": "9.9", code: val}, "t")
    assert _raw(rid) == before


def test_b3d_missing_block(rid):
    with Session(_db.engine) as s:
        r = s.get(_db.Report, rid)
        raw = json.loads(r.data_json)
        del raw["b3_detail"]
        r.data_json = json.dumps(raw)
        s.commit()
    with pytest.raises(ValueError):
        _db.update_report_values(rid, {"b3d.method_type": "x"}, "t")
