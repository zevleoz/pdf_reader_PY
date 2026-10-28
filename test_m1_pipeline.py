"""M1 生成管道测试：三个虚构学生、引文校验、6AM 归组、安全与原始分。

``pipeline._ask`` 全部替换为本地假模型，绝不访问网络。
"""
from __future__ import annotations

import json

import pytest
from flask import Flask

import m1.jobs as jobs
import m1.pipeline as pipeline
import m1.sources as sources
import m1.store as store
from app_utils import BASE_DIR
from m1.validate_doc import (check_no_raw_numbers, check_priority_coverage,
                             scan_placeholders)
from test_m1_store import m1db  # noqa: F401  复用临时库

FT_TEXT = ("2026-10-12 First Touch。考完数学那几天，晚上躺在床上一直在想哪道题错了。"
           "小组作业大家都不做，我就自己全做了，也没说什么。")
PARENT_TEXT = ("2026-10-09 家长反馈：考差会说自己笨，期中后回家不怎么说话，"
               "我们报了数学补习班。")
CASE_TEXT = ("2026-10-20 Case Review 会议记录。课堂观察：答错后整节课低头不说话。"
             "团队假设：担心被评价。")
OTHER_TEXT = "2026-10-21 导师记录：学生喜欢画画，愿意聊兴趣。"


# ---------------------------------------------------------------------------
# 假模型
# ---------------------------------------------------------------------------
def _section(prompt, start, end=None):
    body = prompt.split(start, 1)[1]
    if end:
        body = body.split(end, 1)[0]
    return json.loads(body.strip())


def _first_clause(text):
    for piece in __import__("re").split(r"[。！？\n]", text):
        if piece.strip():
            return piece.strip()
    return text.strip()


def _fake_ask(behaviour):
    def ask(prompt, schema_name):
        if schema_name == pipeline.SCHEMA_SAFETY:
            return behaviour.get("safety") or {"confirmed": False, "items": []}
        if schema_name == pipeline.SCHEMA_SOURCE:
            payload = _section(prompt, "【资料】")
            items = (behaviour.get("source_items") or {}).get(payload["source_ref"])
            if items is None:
                code = (payload.get("abilities") or [{"code": "R1.1"}])[0]["code"]
                items = [{"text": "资料观察", "quote": _first_clause(payload["text"]),
                          "abilities": [code], "kind": "context",
                          "independent": False}]
            return {"items": items}
        if schema_name == pipeline.SCHEMA_ABILITY:
            abilities = _section(prompt, "【能力】", "【证据】")
            evidence = _section(prompt, "【证据】")
            cites_map = behaviour.get("cites") or {}
            contradictions = behaviour.get("contradictions") or {}
            recommend = set(behaviour.get("recommend") or [])
            rows = []
            for row in abilities:
                code = row["code"]
                cites = list(cites_map.get(code) or [])
                if not cites:
                    for item in evidence:
                        if code in (item.get("abilities") or []):
                            cites.append(item["id"])
                            if len(cites) >= 2:
                                break
                rows.append({
                    "code": code,
                    "potential": ["潜在线索"] if cites else [],
                    "interference": ["需要留意的线索"] if cites else [],
                    "known": "已知线索" if cites else "",
                    "new_clues": "新线索" if cites else "",
                    "contradictions": contradictions.get(code, []),
                    "missing": ["缺少持续时间与应对方式"],
                    "check_text": "现有证据只到档位与零散叙述，需要当面确认。",
                    "recommend": code in recommend,
                    "reason": "证据有限，需要确认。" if code in recommend else "信息不足。",
                    "cites": cites,
                })
            return {"abilities": rows}
        if schema_name == pipeline.SCHEMA_PRIORITY:
            rows = _section(prompt, "【优先能力】", "【证据】")
            return {"items": [{"code": row["code"],
                               "hypothesis": "初步假设待核实",
                               "why": "证据有限，需要当面确认。"}
                              for row in rows]}
        if schema_name == pipeline.SCHEMA_PLAN:
            evidence = _section(prompt, "【事件证据】", "【优先能力】")
            priorities = _section(prompt, "【优先能力】", "【全部证据")
            events = []
            if evidence:
                cited = evidence[0]
                events = [{
                    "title": "情境 1：真实事件",
                    "evidence_ids": [cited["id"]],
                    "abilities": cited.get("abilities") or
                                 [row["code"] for row in priorities[:2]],
                    "gap": "缺少持续影响",
                    "questions": ["当时发生了什么？", "后来怎么处理的？", "现在怎么看？"],
                }]
            return {
                "events": events,
                "special": behaviour.get("special") or
                           {"conflict": "", "context": "", "attention": ""},
                "growth": {"wish": "你最希望哪里更轻松？", "next": "先做一次小练习。"},
            }
        raise AssertionError("未知 schema：%s" % schema_name)

    return ask


def _install(monkeypatch, behaviour):
    monkeypatch.setattr(pipeline, "_ask", _fake_ask(behaviour))


# ---------------------------------------------------------------------------
# 来源构造
# ---------------------------------------------------------------------------
def _y4(complete=True, six_am_state=None):
    y4 = {
        "report_id": 12 if complete else None,
        "date": "2026-09-02" if complete else None,
        "complete": complete,
        "six_am": None,
        "items": [],
    }
    if complete:
        y4["items"] = [
            {"id": "y4-013", "source": "y4", "source_ref": "report:12",
             "date": "2026-09-02", "kind": "indirect", "group": "Y4",
             "text": "焦虑/安详：需关注", "quote": "",
             "abilities": ["R1.1", "R2.1", "R2.2"], "band": "需关注", "raw": 7},
            {"id": "y4-053", "source": "y4", "source_ref": "report:12",
             "date": "2026-09-02", "kind": "indirect", "group": "Y4",
             "text": "自我概念—行为表现：偏低", "quote": "",
             "abilities": ["R1.3"], "band": "偏低", "raw": 3},
        ]
    if six_am_state:
        y4["six_am"] = {
            "profile_id": 4, "created_at": "2026-09-03T10:00:00",
            "group": "Y4", "label": "6 A.M. 档案 v1",
            "states": {"Regulate": six_am_state},
            "note": "由 Y4 衍生，不单独计为证据",
        }
    return y4


def _auto(*, complete=True, ft_text=None, questionnaires=None,
          six_am_state=None):
    return {
        "y4": _y4(complete, six_am_state),
        "first_touch": {
            "present": bool(ft_text), "date": "2026-10-12" if ft_text else "",
            "text": ft_text or "", "session_id": 3,
        },
        "questionnaires": questionnaires or [],
    }


def _questionnaires():
    return [
        {"code": "ERQ", "title": "情绪调节问卷", "status": "已完成",
         "date": "2026-10-15", "assignment_id": 5,
         "by_dimension": {"认知重评": [{"question": "我会改变想法", "answer": "不赞同"}]}},
        {"code": "ANX", "title": "焦虑问卷", "status": "未取得",
         "date": "2026-10-10", "assignment_id": 6, "by_dimension": {}},
    ]


def _behavior_all(parent_ref, case_ref, ft_ref, other_ref=""):
    items = {
        parent_ref: [{"text": "家长观察到考后自责", "quote": "考差会说自己笨",
                      "abilities": ["R4.2"], "kind": "context",
                      "independent": False}],
        case_ref: [{"text": "课堂观察", "quote": "答错后整节课低头不说话",
                    "abilities": ["R3.5"], "kind": "direct",
                    "independent": True}],
        ft_ref: [{"text": "考后反复回想", "quote": "晚上躺在床上一直在想哪道题错了",
                  "abilities": ["R2.2", "R3.3"], "kind": "direct",
                  "independent": False}],
    }
    if other_ref:
        items[other_ref] = [{"text": "兴趣线索", "quote": "学生喜欢画画",
                             "abilities": ["R3.1"], "kind": "context",
                             "independent": False}]
    return {
        "source_items": items,
        "recommend": ["R2.2", "R4.2", "R3.3", "R3.5"],
    }


def _latest_draft(prep_id):
    return store.get_latest_version(prep_id, "ai_draft")


# ---------------------------------------------------------------------------
# 学生 a：全部来源
# ---------------------------------------------------------------------------
def test_full_sources_produce_complete_doc(m1db, monkeypatch):
    auto = _auto(ft_text=FT_TEXT, questionnaires=_questionnaires(),
                 six_am_state="需关注")
    monkeypatch.setattr(pipeline.sources, "auto_sources", lambda sid: auto)
    prep = m1db.prep()
    parent = sources.add_text(prep["id"], PARENT_TEXT, "parent")
    case = sources.add_text(prep["id"], CASE_TEXT, "case_review")
    other = sources.add_text(prep["id"], OTHER_TEXT, "other")
    behaviour = _behavior_all(
        "m1_source:%s" % parent["id"], "m1_source:%s" % case["id"],
        "copilot_session:3", "m1_source:%s" % other["id"])
    _install(monkeypatch, behaviour)

    version_id = pipeline.generate(prep["id"])

    assert version_id
    assert store.get_prep(prep["id"])["status"] == "review"
    draft = _latest_draft(prep["id"])
    doc = draft["doc"]
    # R4.2 only has context evidence (no behaviour of the student) and no Y4
    # concern band, so wave 3's rule leaves it out of 2.2
    assert [row["code"] for row in doc["priority"]] == ["R2.2", "R3.3", "R3.5"] \
        or sorted(row["code"] for row in doc["priority"]) == ["R2.2", "R3.3", "R3.5"]
    assert scan_placeholders(doc) == []
    assert check_priority_coverage(doc) == []
    assert check_no_raw_numbers(doc, draft["evidence"]) == []
    assert doc["events"] and "开放探索主题" not in doc["events"][0]["title"]["text"]
    assert {row["key"] for row in doc["sources"]} == {
        "parent", "y4", "questionnaire", "first_touch", "case_review", "other"}
    assert "焦虑问卷：已发送未作答" in doc["flags"]["insufficient"]
    assert doc["flags"]["safety"] == []
    assert len(doc["appendix"]) == 18

    # AI 初稿与可编辑副本都已落库
    edit = store.get_latest_version(prep["id"], "edit")
    assert edit and edit["doc"]["priority"][0]["code"] == doc["priority"][0]["code"]


# ---------------------------------------------------------------------------
# 学生 b：只有 Y4
# ---------------------------------------------------------------------------
def test_y4_only_uses_open_topic_and_insufficient_flags(m1db, monkeypatch):
    auto = _auto()
    monkeypatch.setattr(pipeline.sources, "auto_sources", lambda sid: auto)
    prep = m1db.prep()
    _install(monkeypatch, {"recommend": ["R2.1"]})

    pipeline.generate(prep["id"])

    doc = _latest_draft(prep["id"])["doc"]
    assert 0 <= len(doc["priority"]) <= 3
    assert doc["events"][0]["title"]["text"].startswith("开放探索主题")
    assert doc["events"][0]["clue"].startswith("未取得可引用的真实事件")
    flags = "；".join(doc["flags"]["insufficient"])
    for expected in ("First Touch：未取得", "家长初始反馈：未取得",
                     "Case Review：未取得", "其他资料：未取得"):
        assert expected in flags
    assert scan_placeholders(doc) == []
    assert check_priority_coverage(doc) == []


# ---------------------------------------------------------------------------
# 学生 c：家长与 Case Review 冲突
# ---------------------------------------------------------------------------
def test_conflicting_sources_appear_in_special(m1db, monkeypatch):
    auto = _auto()
    monkeypatch.setattr(pipeline.sources, "auto_sources", lambda sid: auto)
    prep = m1db.prep()
    parent = sources.add_text(prep["id"], "期中后回家不怎么说话，和妈妈交流变少。",
                            "parent")
    case = sources.add_text(
        prep["id"],
        "2026-10-20 Case Review 记录。团队解读：Y4 母亲沟通为高，所以亲子沟通没有问题。",
        "case_review")
    conflict = "Y4 母亲沟通（高）与家长反馈「期中后回家不怎么说话」存在差异"
    behaviour = {
        "source_items": {
            "m1_source:%s" % parent["id"]: [{
                "text": "家长反馈交流变少", "quote": "期中后回家不怎么说话",
                "abilities": ["R3.2"], "kind": "context", "independent": False}],
            "m1_source:%s" % case["id"]: [{
                "text": "团队解读", "quote": "Y4 母亲沟通为高",
                "abilities": ["R3.2"], "kind": "direct", "independent": True}],
        },
        "recommend": ["R3.2"],
        "contradictions": {"R3.2": ["家长反馈与 Case Review 解读不一致"]},
        "special": {"conflict": conflict, "context": "", "attention": ""},
    }
    _install(monkeypatch, behaviour)

    pipeline.generate(prep["id"])

    draft = _latest_draft(prep["id"])
    assert draft["doc"]["special"]["conflict"]["text"] == conflict
    case_items = [item for item in draft["evidence"]
                  if item["source"] == "case_review"]
    assert case_items and case_items[0]["kind"] == "hypothesis"


# ---------------------------------------------------------------------------
# 引文 / 案例推断 / 6AM 归组
# ---------------------------------------------------------------------------
def test_fabricated_quote_is_dropped(m1db, monkeypatch):
    auto = _auto()
    monkeypatch.setattr(pipeline.sources, "auto_sources", lambda sid: auto)
    prep = m1db.prep()
    parent = sources.add_text(prep["id"], PARENT_TEXT, "parent")
    _install(monkeypatch, {
        "source_items": {"m1_source:%s" % parent["id"]: [{
            "text": "编造的观察", "quote": "这句话原文里没有",
            "abilities": ["R4.2"], "kind": "context", "independent": False}]},
        "recommend": [],
    })

    pipeline.generate(prep["id"])

    evidence = _latest_draft(prep["id"])["evidence"]
    assert not [item for item in evidence if item["source"] == "parent"]
    for item in evidence:
        if item["quote"]:
            assert item["quote"] != "这句话原文里没有"


def test_case_review_y4_interpretation_is_hypothesis(m1db, monkeypatch):
    auto = _auto()
    monkeypatch.setattr(pipeline.sources, "auto_sources", lambda sid: auto)
    prep = m1db.prep()
    case = sources.add_text(
        prep["id"],
        "2026-10-20 Case Review 记录。团队解读：Y4 依恋沟通为高，所以没有沟通困难。",
        "case_review")
    _install(monkeypatch, {
        "source_items": {"m1_source:%s" % case["id"]: [{
            "text": "团队解读 Y4", "quote": "Y4 依恋沟通为高",
            "abilities": ["R3.2"], "kind": "direct", "independent": True}]},
        "recommend": [],
    })

    pipeline.generate(prep["id"])

    items = [item for item in _latest_draft(prep["id"])["evidence"]
             if item["source"] == "case_review"]
    assert items and items[0]["kind"] == "hypothesis"


def test_six_am_never_counts_as_second_group(m1db, monkeypatch):
    auto = _auto(six_am_state="需关注")
    monkeypatch.setattr(pipeline.sources, "auto_sources", lambda sid: auto)
    prep = m1db.prep()
    _install(monkeypatch, {
        "recommend": ["R2.1"],
        "cites": {"R2.1": ["y4-013", "6am-0"]},
    })

    pipeline.generate(prep["id"])

    draft = _latest_draft(prep["id"])
    judgement = draft["ai_output"]["abilities"]["R2.1"]
    assert judgement["cites"] == ["y4-013", "6am-0"]
    assert judgement["supported"] is False


# ---------------------------------------------------------------------------
# 安全
# ---------------------------------------------------------------------------
def test_safety_keyword_sets_flag_and_blocks_finalize(m1db, monkeypatch):
    auto = _auto()
    monkeypatch.setattr(pipeline.sources, "auto_sources", lambda sid: auto)
    prep = m1db.prep()
    parent = sources.add_text(prep["id"], "家长反馈：孩子说过不想活了。", "parent")
    _install(monkeypatch, {
        "safety": {"confirmed": True,
                   "items": [{"source_ref": "m1_source:%s" % parent["id"],
                              "text": "孩子说过不想活了"}]},
        "recommend": [],
    })

    pipeline.generate(prep["id"])

    doc = _latest_draft(prep["id"])["doc"]
    assert doc["flags"]["safety"]
    assert doc["flags"]["safety"][0]["source_ref"] == "m1_source:%s" % parent["id"]

    import app_utils
    from blueprints import m1 as m1_api
    monkeypatch.setattr(app_utils, "is_authenticated", lambda: True)
    app = Flask(__name__, template_folder=str(BASE_DIR / "templates"))
    app.secret_key = "test"
    app.register_blueprint(m1_api.bp)
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = m1db.admin_id
        sess["role"] = "admin"
        sess["advisor_name"] = ""
    blocked = client.post("/api/m1/preps/%d/finalize" % prep["id"])
    assert blocked.status_code == 409
    assert "安全提示" in blocked.get_json()["error"]


# ---------------------------------------------------------------------------
# 原始分值
# ---------------------------------------------------------------------------
def test_no_raw_numbers_in_generated_doc(m1db, monkeypatch):
    auto = _auto(ft_text=FT_TEXT, questionnaires=_questionnaires())
    monkeypatch.setattr(pipeline.sources, "auto_sources", lambda sid: auto)
    prep = m1db.prep()
    parent = sources.add_text(prep["id"], PARENT_TEXT, "parent")
    case = sources.add_text(prep["id"], CASE_TEXT, "case_review")
    _install(monkeypatch, _behavior_all(
        "m1_source:%s" % parent["id"], "m1_source:%s" % case["id"],
        "copilot_session:3"))

    pipeline.generate(prep["id"])

    draft = _latest_draft(prep["id"])
    assert check_no_raw_numbers(draft["doc"], draft["evidence"]) == []
    assert all(item.get("raw") in (None, 7, 3) for item in draft["evidence"])


# ---------------------------------------------------------------------------
# 路由：generate / jobs
# ---------------------------------------------------------------------------
@pytest.fixture()
def api_client(m1db, monkeypatch):
    import app_utils
    from blueprints import m1 as m1_api

    monkeypatch.setattr(app_utils, "is_authenticated", lambda: True)
    app = Flask(__name__, template_folder=str(BASE_DIR / "templates"))
    app.secret_key = "test-secret"
    app.register_blueprint(m1_api.bp)
    return app.test_client()


def _login(client, user_id, role, advisor_name=""):
    with client.session_transaction() as sess:
        sess["user_id"] = user_id
        sess["role"] = role
        sess["advisor_name"] = advisor_name


def test_generate_route_refuses_while_generating(api_client, m1db, monkeypatch):
    prep = m1db.prep()
    store.set_status(prep["id"], "generating")
    _login(api_client, m1db.admin_id, "admin")
    res = api_client.post("/api/m1/preps/%d/generate" % prep["id"])
    assert res.status_code == 409


def test_generate_route_launches_job_and_sets_generating(api_client, m1db,
                                                          monkeypatch):
    prep = m1db.prep()
    monkeypatch.setattr(jobs, "launch_job", lambda *args, **kwargs: "a" * 32)
    _login(api_client, m1db.alice_id, "advisor", "Alice")

    res = api_client.post("/api/m1/preps/%d/generate" % prep["id"])
    assert res.status_code == 200
    assert res.get_json()["job_id"] == "a" * 32
    assert store.get_prep(prep["id"])["status"] == "generating"

    again = api_client.post("/api/m1/preps/%d/generate" % prep["id"])
    assert again.status_code == 409


def test_job_status_is_access_scoped(api_client, m1db, monkeypatch, tmp_path):
    monkeypatch.setattr(jobs, "JOB_DIR", tmp_path / "m1_jobs")
    prep = m1db.prep()
    job_id = "b" * 32
    jobs.write_job(job_id, status="done", prep_id=prep["id"], steps=jobs.new_steps())

    _login(api_client, m1db.alice_id, "advisor", "Alice")
    ok = api_client.get("/api/m1/jobs/%s" % job_id)
    assert ok.status_code == 200
    assert ok.get_json()["job"]["status"] == "done"

    _login(api_client, m1db.bob_id, "advisor", "Bob")
    assert api_client.get("/api/m1/jobs/%s" % job_id).status_code == 403
    assert api_client.get("/api/m1/jobs/%s" % ("c" * 32)).status_code == 404


def test_job_failure_restores_previous_status(m1db, monkeypatch, tmp_path):
    monkeypatch.setattr(jobs, "JOB_DIR", tmp_path / "m1_jobs")
    prep = m1db.prep()
    store.set_status(prep["id"], "generating")
    job_id = "d" * 32
    jobs.write_job(job_id, status="queued", prep_id=prep["id"],
                   previous_status="draft", steps=jobs.new_steps())

    def boom(prep_id, progress=None):
        raise RuntimeError("模型调用失败")

    monkeypatch.setattr(pipeline, "generate", boom)
    with pytest.raises(RuntimeError):
        jobs.run_job(job_id, {"prep_id": prep["id"],
                              "previous_status": "draft",
                              "actor_id": m1db.alice_id})

    assert store.get_prep(prep["id"])["status"] == "draft"
    job = jobs.read_job(job_id)
    assert job["status"] == "error"
    assert "生成失败" in job["message"]


# ---------------------------------------------------------------------------
# wave 3: priority rules found on the real model
# ---------------------------------------------------------------------------
def _ev(item_id, source, kind, abilities, band=""):
    group = "Y4" if source in ("y4", "six_am") else "m1_source:%s" % item_id
    return {"id": item_id, "source": source, "kind": kind, "group": group,
            "abilities": abilities, "band": band}


def _judged(code, cites, recommend=True):
    return {"code": code, "recommend": recommend, "cites": cites, "potential": ["p"],
            "interference": ["i"], "contradictions": [], "missing": ["m"]}


def test_y4_only_student_gets_at_most_two_priorities():
    by_id = {"y4-1": _ev("y4-1", "y4", "indirect", ["R1.1"], "偏低"),
             "y4-2": _ev("y4-2", "y4", "indirect", ["R2.1"], "需关注"),
             "y4-3": _ev("y4-3", "y4", "indirect", ["R3.1"], "偏低"),
             "y4-4": _ev("y4-4", "y4", "indirect", ["R4.1"], "相对健康")}
    judgements = {c: _judged(c, [i]) for c, i in
                  (("R1.1", "y4-1"), ("R2.1", "y4-2"), ("R3.1", "y4-3"), ("R4.1", "y4-4"))}
    chosen = pipeline._choose_priorities(judgements, by_id)
    assert len(chosen) == 2 and "R4.1" not in chosen  # no concern band, no real evidence


def test_one_dimension_cannot_take_every_slot():
    by_id = {"s-%d" % n: _ev("s-%d" % n, "parent", "direct", []) for n in range(6)}
    codes = ["R4.1", "R4.2", "R4.3", "R2.2", "R3.5"]
    judgements = {c: _judged(c, ["s-%d" % n]) for n, c in enumerate(codes)}
    chosen = pipeline._choose_priorities(judgements, by_id)
    assert sum(code.startswith("R4.") for code in chosen) == 2
    assert "R2.2" in chosen and "R3.5" in chosen


def test_context_only_evidence_does_not_qualify():
    by_id = {"s-1": _ev("s-1", "parent", "context", ["R4.3"])}
    chosen = pipeline._choose_priorities({"R4.3": _judged("R4.3", ["s-1"])}, by_id)
    assert chosen == []


def test_evidence_ids_are_stripped_from_text():
    by_id = {"y4-013": {}, "src-2-1": {}}
    text = pipeline._strip_ids("焦虑需关注（y4-013、src-2-1），家长也提到低落 y-019", by_id)
    assert "y4-013" not in text and "src-2-1" not in text and "y-019" not in text
    assert "焦虑需关注" in text and "家长也提到低落" in text
