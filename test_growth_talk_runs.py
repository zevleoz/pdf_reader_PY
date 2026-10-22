"""Growth Talk 审核动作契约测试（tmp SQLite，不联网）。"""
from __future__ import annotations

import json

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session

import db as _db
import growth_talk_store as store
from growth_talk import runs


class GTDB:
    def __init__(self, engine):
        self.engine = engine
        self.student_id = None

    def insert_student(self, name="测试学生", grade="10"):
        with Session(self.engine) as sess:
            row = _db.Student(student_code="Y4-9001", name=name, grade=grade,
                              advisor_name="Mine")
            sess.add(row)
            sess.commit()
            self.student_id = row.id
        return self.student_id


@pytest.fixture()
def qdb(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'growth_talk_runs.db'}")

    @event.listens_for(engine, "connect")
    def _enable_fk(dbapi_connection, _record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    tables = [
        _db.Student.__table__,
        store.GtSource.__table__,
        store.GtRun.__table__,
        store.GtUnderstanding.__table__,
        store.GtInterest.__table__,
        store.GtQuadrant.__table__,
        store.GtSuggestion.__table__,
        store.GtReport.__table__,
        store.ExternalIdentity.__table__,
        store.AuditLog.__table__,
        store.CrmDeliveryReceipt.__table__,
        store.CrmAppointment.__table__,
    ]
    _db.Base.metadata.create_all(engine, tables=tables)
    monkeypatch.setattr(_db, "engine", engine)

    helper = GTDB(engine)
    helper.insert_student()
    yield helper
    engine.dispose()


def _seed_run(qdb, *, statuses=("PENDING_REVIEW", "PENDING_REVIEW")):
    source = store.create_source(
        qdb.student_id, "GROWTH_TALK", "GROWTH_TALK", "会谈记录",
        "他说自己每周打篮球，也在学机器人。")
    run = store.create_run(qdb.student_id, source["id"])
    store.save_understanding(
        run["id"], "本次会议主要围绕兴趣与经历展开。他每周打篮球。",
        json.dumps([
            {"label": "篮球", "topicType": "interest", "evidence": "每周打篮球"},
            {"label": "机器人", "topicType": "interest", "evidence": "在学机器人"},
        ], ensure_ascii=False),
        json.dumps([], ensure_ascii=False), "deepseek-chat",
    )
    store.replace_interests(run["id"], [
        {"label": "篮球", "evidence": "每周打篮球", "status": statuses[0]},
        {"label": "机器人", "evidence": "在学机器人", "status": statuses[1]},
    ])
    full = store.get_run_full(run["id"])
    return full["id"], [item["id"] for item in full["interests"]]


def test_stale_revision_rejected(qdb):
    run_id, _ids = _seed_run(qdb)
    with pytest.raises(store.RevisionConflict):
        runs.apply_action(
            run_id, "edit-understanding",
            {"expected_revision": 999, "summary": "新总结。"}, "顾问A",
        )


def test_invalid_edit_rolls_back_revision(qdb):
    run_id, _ids = _seed_run(qdb)
    with pytest.raises(runs.ActionError):
        runs.apply_action(
            run_id, "edit-understanding",
            {"expected_revision": 1, "summary": "转学安排。"}, "顾问A",
        )
    assert store.get_run(run_id)["revision"] == 1


def test_special_focus_at_most_one(qdb):
    run_id, ids = _seed_run(qdb)
    runs.apply_action(
        run_id, "set-special-focus",
        {"expected_revision": 1, "interestId": ids[0]}, "顾问A",
    )
    runs.apply_action(
        run_id, "set-special-focus",
        {"expected_revision": 2, "interestId": ids[1]}, "顾问A",
    )
    full = store.get_run_full(run_id)
    focused = [item["id"] for item in full["interests"] if item["special_focus"]]
    assert focused == [ids[1]]


def test_add_interest_stales_outputs(qdb):
    run_id, _ids = _seed_run(qdb)
    store.save_quadrant(run_id, json.dumps([], ensure_ascii=False), "说明文字", "m")
    store.replace_suggestions(run_id, [
        {"title": "试试看", "introduction": "介绍", "growthValue": "价值"},
    ])
    runs.apply_action(
        run_id, "add-interest",
        {"expected_revision": 1, "label": "机器人竞赛"}, "顾问A",
    )
    full = store.get_run_full(run_id)
    assert full["quadrant"]["status"] == "STALE"
    assert all(item["status"] == "STALE" for item in full["suggestions"])


def test_select_interests_dismisses_unselected(qdb):
    run_id, ids = _seed_run(qdb, statuses=("PENDING_SELECTION", "PENDING_SELECTION"))
    runs.apply_action(
        run_id, "select-interests",
        {"expected_revision": 1, "interestIds": [ids[0]]}, "顾问A",
    )
    full = store.get_run_full(run_id)
    by_id = {item["id"]: item for item in full["interests"]}
    assert by_id[ids[0]]["status"] == "PENDING_REVIEW"
    assert by_id[ids[1]]["status"] == "DISMISSED"


def test_confirm_interests_triggers_regeneration(qdb, monkeypatch):
    run_id, ids = _seed_run(qdb)
    calls = {"quadrant": 0, "suggestions": 0}

    def fake_quadrant(input_data):
        calls["quadrant"] += 1
        assert {item["id"] for item in input_data["interests"]} == set(ids)
        return {"narrative": "第一段说明。\n\n第二段分析。"}

    def fake_suggestions(input_data):
        calls["suggestions"] += 1
        return [{
            "title": "篮球观察记录",
            "introduction": "记录一周比赛中的决策。",
            "growthValue": "练习观察与复盘。",
            "possibleOutputs": ["记录表"],
            "recommendationBasis": "会议提到每周训练",
            "interestRefs": [ids[0]],
            "explorationTags": ["观察"],
        }]

    monkeypatch.setattr(runs.analysis, "run_quadrant_analysis", fake_quadrant)
    monkeypatch.setattr(runs.analysis, "generate_suggestions", fake_suggestions)

    result = runs.apply_action(run_id, "confirm-interests", {
        "expected_revision": 1,
        "items": [
            {"interestId": ids[0], "preferenceScore": 3, "competenceScore": 2},
            {"interestId": ids[1], "preferenceScore": 2, "competenceScore": 1},
        ],
    }, "顾问A")

    assert result["revision"] == 2
    assert calls == {"quadrant": 1, "suggestions": 1}
    full = store.get_run_full(run_id)
    assert all(item["status"] == "CONFIRMED" for item in full["interests"])
    assert full["quadrant"]["status"] == "DRAFT"
    assert json.loads(full["quadrant"]["points"])[0]["quadrant"]
    assert [item["title"] for item in full["suggestions"]] == ["篮球观察记录"]


def test_confirm_interests_rejects_bad_score(qdb):
    run_id, ids = _seed_run(qdb)
    with pytest.raises(runs.ActionError, match="0 到 3"):
        runs.apply_action(run_id, "confirm-interests", {
            "expected_revision": 1,
            "items": [{"interestId": ids[0], "preferenceScore": 4,
                       "competenceScore": 1}],
        }, "顾问A")


def test_edit_understanding_stales_and_confirms(qdb):
    run_id, _ids = _seed_run(qdb)
    store.save_quadrant(run_id, "[]", "说明文字", "m")
    runs.apply_action(
        run_id, "edit-understanding",
        {"expected_revision": 1, "summary": "本次会议围绕篮球与机器人展开。"},
        "顾问A",
    )
    full = store.get_run_full(run_id)
    assert full["understanding"]["status"] == "CONFIRMED"
    assert full["quadrant"]["status"] == "STALE"


def test_save_interest_section_renames_and_syncs_topics(qdb):
    run_id, ids = _seed_run(qdb)
    result = runs.apply_action(run_id, "save-interest-section", {
        "expected_revision": 1,
        "items": [
            {"interestId": ids[0], "label": "篮球训练", "topicType": "interest",
             "specialFocus": True, "preferenceScore": 3, "competenceScore": 2},
            {"interestId": ids[1], "label": "机器人", "topicType": "interest",
             "specialFocus": False, "preferenceScore": None,
             "competenceScore": None},
        ],
        "removedInterestIds": [],
        "selectCandidates": False,
    }, "顾问A")
    assert result["revision"] == 2
    full = store.get_run_full(run_id)
    renamed = next(item for item in full["interests"] if item["id"] == ids[0])
    assert renamed["label"] == "篮球训练"
    assert renamed["status"] == "CONFIRMED"
    topics = json.loads(full["understanding"]["topics"])
    assert {topic["label"] for topic in topics} == {"篮球训练", "机器人"}


def test_edit_suggestions_adds_and_removes(qdb):
    run_id, _ids = _seed_run(qdb)
    store.replace_suggestions(run_id, [
        {"title": "旧建议", "introduction": "介绍", "growthValue": "价值"},
    ])
    full = store.get_run_full(run_id)
    kept_id = full["suggestions"][0]["id"]
    result = runs.apply_action(run_id, "edit-suggestions", {
        "expected_revision": 1,
        "items": [
            {"suggestionId": kept_id, "title": "新标题", "introduction": "介绍",
             "growthValue": "价值"},
            {"suggestionId": None, "title": "第二条", "introduction": "介绍",
             "growthValue": "价值"},
        ],
    }, "顾问A")
    titles = [item["title"] for item in result["patch"]["suggestions"]]
    assert titles == ["新标题", "第二条"]
    assert all(item["status"] == "DRAFT" for item in result["patch"]["suggestions"])


def test_discover_interests_appends_candidates(qdb, monkeypatch):
    run_id, _ids = _seed_run(qdb)
    monkeypatch.setattr(
        runs.analysis, "discover_additional_interests",
        lambda content, existing: [{
            "label": "排球", "topicType": "interest", "subtopic": None,
            "evidence": "也提到排球", "sourceRound": "会议原文",
            "evidenceStrength": "中", "uncertainty": None,
            "preferenceScore": None, "competenceScore": None,
        }],
    )
    result = runs.apply_action(
        run_id, "discover-interests", {"expected_revision": 1}, "顾问A")
    assert result["added_count"] == 1
    assert result["revision"] == 2
    full = store.get_run_full(run_id)
    added = next(item for item in full["interests"] if item["label"] == "排球")
    assert added["status"] == "PENDING_SELECTION"


def test_regenerate_suggestions(qdb, monkeypatch):
    run_id, _ids = _seed_run(qdb)
    # 直接铺已确认兴趣，避免依赖上一步的模型打桩。
    with Session(qdb.engine) as sess:
        rows = sess.execute(
            select(store.GtInterest).where(store.GtInterest.run_id == run_id)
        ).scalars().all()
        for item in rows:
            item.status = "CONFIRMED"
            item.preference_score = 2
            item.competence_score = 1
        sess.commit()
    monkeypatch.setattr(
        runs.analysis, "generate_suggestions",
        lambda input_data: [{
            "title": "建议A", "introduction": "介绍", "growthValue": "价值",
            "possibleOutputs": [], "recommendationBasis": "依据",
            "interestRefs": [], "explorationTags": [],
        }],
    )
    result = runs.apply_action(
        run_id, "regenerate", {"expected_revision": 1, "stage": "suggestions"},
        "顾问A")
    assert [item["title"] for item in result["patch"]["suggestions"]] == ["建议A"]
