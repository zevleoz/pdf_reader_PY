"""会后报告核心：固定数据、管道、检查、状态流转、路由与权限。

所有 AI 调用都被替换成虚构的固定回答，不访问真实模型。
"""
from __future__ import annotations

import copy
import filecmp
import json
import logging
import re
from datetime import date
from pathlib import Path

import pytest
from flask import Flask
from sqlalchemy import select
from sqlalchemy.orm import Session

import data_points
import db as _db
import growth_talk_store as _gt
import m1.jobs as m1_jobs
import m1.store as store
from app_utils import BASE_DIR
from growth_talk.analysis import AnalysisError
from m1 import (report_checks, report_jobs, report_kb, report_pipeline, report_store,
                report_y4)
from test_m1_api import login_as
from test_m1_store import m1db  # noqa: F401  临时库与虚构学生

# 原始文件只在主工作区的 docs/audits/plans-hub/ 里（未入库）；工作树和服务器上可能没有
_SOURCE_CANDIDATES = [BASE_DIR / "docs" / "audits" / "plans-hub" / "r4-report",
                      BASE_DIR.parent.parent / "docs" / "audits" / "plans-hub" / "r4-report"]
SOURCE_DIR = next((d for d in _SOURCE_CANDIDATES if d.is_dir()), None)

TRANSCRIPT = "\n".join([
    "[00:00:10] 导师：晓雨，今天我们聊聊最近的情绪。上周有没有哪次让你特别烦？",
    "[00:00:30] 学生：上周数学小测没考好，我心跳很快，手心出汗，整个下午都很烦。",
    "[00:01:00] 导师：那你当时是怎么做的？",
    "[00:01:15] 学生：我没跟同学说，一个人趴在桌上，后来才慢慢好一点。",
    "[00:01:40] 导师：如果下次再这样，你觉得深呼吸会不会有帮助？",
    "[00:01:55] 学生：可能会吧，老师你这么说我觉得可以试试。",
    "[00:02:20] 导师：和朋友之间呢，有没有想主动求助的时候？",
    "[00:02:40] 学生：上次作业不会，我主动问了补习班的老师。",
])
Q_BODY = "我心跳很快，手心出汗，整个下午都很烦"
Q_HIDE = "我没跟同学说，一个人趴在桌上"
Q_GUIDED = "可能会吧，老师你这么说我觉得可以试试"
Q_HELP = "上次作业不会，我主动问了补习班的老师"
Q_MENTOR = "如果下次再这样，你觉得深呼吸会不会有帮助"
Q_FAKE = "我每天晚上都会反复做噩梦"


# ---------------------------------------------------------------------------
# 假模型
# ---------------------------------------------------------------------------
def _item(quote, speaker, kind, codes, interp="示例解读", limits=""):
    return {"quote": quote, "speaker": speaker, "type": kind, "ability_codes": codes,
            "interpretation": interp, "limits": limits}


class FakeModel:
    """按提示词里的「任务：」分发；``dims`` 可覆盖单项能力的输出。

    事实核对默认全部通过；``unsupported`` 里的词所在的句子会被判为没有依据，
    重写只原样返回，好让标记留下来（S2-P6 §10）。
    """

    def __init__(self):
        self.calls = []
        self.meeting_items = [
            _item(Q_BODY, "学生", "具体行为事件", ["R1.1"]),
            _item("我心跳很快 手心出汗，整个下午都很烦。", "学生", "具体行为事件", ["R1.3"]),
            # T7 §6：被长引文包含的短引文会并入长的一条，所以这里改用同一段里不重叠的一句
            _item("上周数学小测没考好", "学生", "主观感受", ["R1.2"]),
            _item(Q_HIDE, "学生", "具体行为事件", ["R2.1"]),
            _item(Q_GUIDED, "学生", "引导下表现", ["R1.2"]),
            _item(Q_HELP, "学生", "具体行为事件", ["R3.5"]),
            _item(Q_FAKE, "学生", "具体行为事件", ["R4.1"]),
            _item(Q_MENTOR, "导师", "其他观察", ["R2.1"]),
            _item("【4】" + Q_HIDE, "孙悟空", "不存在的类型", ["R2.4", "R9.9"]),
            _item("只有无效编号", "学生", "主观感受", ["R9.9"]),
        ]
        self.overrides = {}
        self.fail = None
        self.unsupported = ()
        self.profile_plan = [
            {"ability": "R1.1"}, {"ability": "R9.9"}, {"ability": "R2.1"},
            {"ability": "R3.5"}, {"ability": "R4.1"}]

    def __call__(self, prompt):
        self.calls.append(prompt)
        if self.fail:
            raise self.fail
        if prompt.startswith("任务：从逐字稿中提取证据条目"):
            return {"items": copy.deepcopy(self.meeting_items)}
        if prompt.startswith("任务：从其他资料中提取证据条目"):
            return {"items": []}
        if prompt.startswith("任务：整理一个维度的能力分析"):
            return self._dim(prompt)
        if prompt.startswith("任务：综合画像与阶段方案"):
            return self._profile()
        if prompt.startswith("你是事实核对员"):
            return self._verify(prompt)
        if prompt.startswith("下面这段文字有几处没有资料依据"):
            return self._rewrite(prompt)
        if "是否包含需要立即人工核实" in prompt:
            return {"confirmed": False, "items": []}
        raise AssertionError("未知提示词")

    def _verify(self, prompt):
        text = prompt.split("【文字】\n", 1)[1].split("\n【资料】", 1)[0]
        rows = []
        for sentence in (p.strip() for p in re.split(r"[。！？!?；;\n]+", text)):
            if not sentence:
                continue
            bad = any(word in sentence for word in self.unsupported)
            rows.append({"text": sentence, "verdict": "unsupported" if bad else "supported",
                         "problem": "与资料不符" if bad else ""})
        return {"sentences": rows}

    def _rewrite(self, prompt):
        text = prompt.split("【文字】\n", 1)[1].split("\n【问题】", 1)[0].strip()
        return {"text": text}

    def _dim(self, prompt):
        payload = json.loads(prompt.split("【能力与资料】\n", 1)[1])
        rows = []
        for ability in payload:
            code = ability["code"]
            ids = [e["id"] for e in ability["meeting_evidence"]]
            row = {"code": code, "y4_selected": [], "other_clues": "",
                   "meeting": {"sentences": []},
                   "tags": ["信息不足"], "evidence_ids": ids, "internal_note": "内部备注"}
            if code == "R1.1":
                row.update(y4_selected=["013", "999"], tags=["确认发展需求"],
                           meeting={"sentences": [{
                               "text": "学生说“心跳很快，手心出汗”，整个下午都觉得很烦。",
                               "evidence_ids": ids[:1], "kind": "fact"}]})
            elif code == "R1.2":
                row.update(tags=["确认发展需求"],
                           meeting={"sentences": [{
                               "text": "学生设想可以试试，是在老师提出建议之后。",
                               "evidence_ids": ids[-1:], "kind": "fact"}]})
            elif code == "R1.3":
                row.update(tags=["积极资源"])
            elif code == "R1.4":
                row.update(tags=["积极资源"])
            elif code == "R2.1":
                row.update(y4_selected=[], tags=["积极资源", "信息不足"],
                           meeting={"sentences": [{
                               "text": "学生选择独自待着，之后慢慢好一点。",
                               "evidence_ids": ids[:1], "kind": "fact"}]})
            elif code == "R2.2":
                row.update(tags=["乱写"])
            elif code == "R2.3":
                row.update(tags=["可能存在"],
                           meeting={"sentences": [{
                               "text": "学生可能有时会走神。",
                               "evidence_ids": [], "kind": "inference"}]})
            elif code == "R2.5":
                row.update(tags=["暂未发现"])
            row.update(self.overrides.get(code, {}))
            rows.append(row)
        return {"abilities": rows,
                "core_finding": {"sentences": [{
                    "text": "本维度的资料有限，还需要了解。",
                    "evidence_ids": [], "kind": "inference"}]},
                "context_notes": {"sentences": []}}

    def _profile(self):
        return {
            "portrait": {d: "%s 的综合观察。" % d for d in ("R1", "R2", "R3", "R4")},
            "findings": {k: {"finding": "%s 发现" % k, "meaning": "%s 意义" % k}
                         for k in ("resources", "needs", "open")},
            "plan": [dict(row, goal="目标", mentor="导师支持", family="家庭支持",
                          evidence="成长证据") for row in self.profile_plan],
            "review_advice": "回顾时注意学生是否愿意说出自己的感受。",
        }


@pytest.fixture()
def fake(monkeypatch):
    model = FakeModel()
    monkeypatch.setattr(report_pipeline, "call_model", model)
    return model


# ---------------------------------------------------------------------------
# 库 / 应用
# ---------------------------------------------------------------------------
Y4_VALUES = {"013": 6, "012": 12, "056": 5, "019": 4.0, "072": "SAE"}


@pytest.fixture()
def rdb(m1db, tmp_path, monkeypatch):  # noqa: F811
    report_store.ensure_tables(m1db.engine)
    monkeypatch.setattr(m1_jobs, "JOB_DIR", tmp_path / "jobs")
    points = [{"code": c, "value": v, "type": "string" if isinstance(v, str) else "number"}
              for c, v in Y4_VALUES.items()]
    points += [{"code": c, "value": v, "type": "number"}
               for c, v in (("073", "2"), ("074", "5"), ("075", "2"), ("076", "4"),
                            ("077", "1"), ("078", "3"))]
    with Session(m1db.engine) as sess:       # 比 m1db 自带的更晚、也更完整的一份 Y4
        sess.add(_db.Report(student_id=m1db.student_id, report_date=date(2026, 10, 1),
                            pdf_path="r.pdf",
                            data_json=json.dumps({"schema_124": points}, ensure_ascii=False)))
        sess.commit()
    m1db.prep_row = m1db.prep()
    return m1db


def make_report(rdb, transcript=TRANSCRIPT):
    report = report_store.get_or_create_report(rdb.prep_row["id"], rdb.alice_id)
    if transcript is not None:
        report_store.set_transcript(report["id"], text=transcript, filename="t.txt")
    return report_store.get_report_by_id(report["id"])


def generate(rdb, fake_model=None):
    report = make_report(rdb)
    version_id = report_pipeline.generate(rdb.prep_row["id"], actor_id=rdb.alice_id)
    return report, report_store.get_version(version_id)


@pytest.fixture()
def client(rdb, monkeypatch):
    import app_utils
    from blueprints import m1 as m1_api
    from blueprints import m1_report

    monkeypatch.setattr(app_utils, "is_authenticated", lambda: True)
    app = Flask(__name__, template_folder=str(BASE_DIR / "templates"))
    app.secret_key = "test-secret"
    app.register_blueprint(m1_api.bp)
    app.register_blueprint(m1_report.bp)
    return app.test_client()


@pytest.fixture()
def inline_jobs(monkeypatch, rdb):
    """launch_job 在测试里同步跑完生成。"""
    def launch(prep_id, report_id, *, previous_status="draft", actor_id=None):
        report_pipeline.generate(prep_id, actor_id=actor_id)
        return "a" * 32
    monkeypatch.setattr(report_jobs, "launch_job", launch)


def admin_login(client, rdb):
    login_as(client, rdb.admin_id, "admin")


def url(rdb, tail=""):
    return "/api/m1/preps/%d/report%s" % (rdb.prep_row["id"], tail)


# ---------------------------------------------------------------------------
# 固定数据
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("name", ["fixed", "mapping", "scenes"])
def test_kb_copies_identical_to_source(name):
    file_name = "r4_report_%s.json" % name
    copy_path = BASE_DIR / "m1" / "kb" / file_name
    if SOURCE_DIR is None:       # 没有原始文件可比时，至少确认副本是完整的 JSON 对象
        data = json.loads(copy_path.read_text("utf-8"))
        assert isinstance(data, dict) and data
        return
    assert filecmp.cmp(SOURCE_DIR / file_name, copy_path, shallow=False)


def test_mapping_and_scenes_have_18_entries():
    mapping = json.loads((BASE_DIR / "m1/kb/r4_report_mapping.json").read_text("utf-8"))
    scenes = json.loads((BASE_DIR / "m1/kb/r4_report_scenes.json").read_text("utf-8"))
    assert len(mapping["abilities"]) == 18 and len(scenes["scenes"]) == 18
    assert set(mapping["abilities"]) == set(scenes["scenes"]) == set(report_kb.ability_map())


def test_every_indicator_is_in_point_meta():
    for code, info in report_kb.ability_map().items():
        assert info["indicators"], code
        for indicator in info["indicators"]:
            assert indicator in data_points.POINT_META, (code, indicator)


def test_ability_map_fields_and_order():
    rows = report_kb.ability_map()
    assert list(rows)[0] == "R1.1" and len(rows) == 18
    assert set(rows["R1.1"]) == {"name", "description", "dim", "indicators", "y4_text",
                                 "gap_note", "supplement", "ask"}
    assert rows["R3.5"]["dim"] == "R3"


def test_scene_missing_returns_none(monkeypatch, tmp_path):
    assert report_kb.scene("R1.1")
    assert report_kb.scene("R9.9") is None
    monkeypatch.setattr(report_kb, "_SCENES_PATH", tmp_path / "nope.json")
    assert report_kb.scene("R1.1") is None


def test_appendix_selects_tags_once_in_code_order():
    def row(*tags):
        return {"tags": list(tags)}
    doc = {"dims": {
        "R2": {"abilities": {"R2.2": row("可能存在"), "R2.1": row("积极资源")}},
        "R1": {"abilities": {"R1.2": row("积极资源", "确认发展需求"), "R1.1": row("信息不足")}},
    }}
    result = report_kb.appendix(doc)
    assert [r["code"] for r in result] == ["R1.2", "R2.2"]
    assert result[0]["scene"] == report_kb.scene("R1.2")
    assert report_kb.appendix({}) == []


def test_missing_scene_shows_placeholder_text(monkeypatch, tmp_path):
    monkeypatch.setattr(report_kb, "_SCENES_PATH", tmp_path / "nope.json")
    doc = {"dims": {"R1": {"abilities": {"R1.1": {"tags": ["可能存在"]}}}}}
    assert report_kb.appendix(doc)[0]["scene"] == "场景原文待导入"


@pytest.mark.parametrize("tags,ok", [
    ([], True), (["积极资源"], True), (["积极资源", "确认发展需求"], True),
    (["积极资源", "可能存在"], True), (["信息不足", "积极资源"], False),
    (["暂未发现", "确认发展需求"], False), (["积极资源", "积极资源"], False),
    (["积极资源", "可能存在", "暂未发现"], False), (["随便"], False), ("积极资源", False),
    (["暂未发现", "可能存在"], False), (["确认发展需求", "可能存在"], False),
    (["积极资源", "暂未发现"], False), (["积极资源", "确认发展需求"], True),
    (["积极资源", "可能存在"], True)])
def test_tags_problem(tags, ok):
    assert (report_kb.tags_problem(tags) == "") is ok


# ---------------------------------------------------------------------------
# 文本工具
# ---------------------------------------------------------------------------
def test_make_chunks_respects_limit_and_overlap():
    paragraphs = ["第%03d段" % i + "字" * 90 for i in range(200)]
    chunks = report_pipeline.make_chunks(paragraphs, limit=1000, overlap=200)
    assert len(chunks) > 3
    assert all(len(c) <= 1000 for c in chunks)
    for left, right in zip(chunks, chunks[1:]):
        last = left.split("\n")[-1]
        assert last in right.split("\n")[:3]       # 相邻块有重叠
    assert chunks[0].startswith("第000段")
    assert report_pipeline.make_chunks(["短"]) == ["短"]
    long = report_pipeline.make_chunks(["字" * 13000])
    assert [len(c) for c in long] == [6000, 6000, 1000]


def test_text_index_locates_ignoring_punctuation():
    index = report_checks.TextIndex(TRANSCRIPT)
    assert index.locate("我心跳很快 手心出汗，整个下午都很烦。") == (2, "00:00:30")
    assert index.locate(Q_HELP) == (8, "00:02:40")
    assert index.locate("【3】" + Q_HIDE) == (4, "00:01:15")
    assert index.locate(Q_FAKE) is None and index.locate("") is None


# ---------------------------------------------------------------------------
# 管道：端到端
# ---------------------------------------------------------------------------
def test_end_to_end_generation(rdb, fake):
    steps = []
    make_report(rdb)
    version_id = report_pipeline.generate(
        rdb.prep_row["id"], progress=lambda step, state, sec: steps.append((step, state)),
        actor_id=rdb.alice_id)
    report = report_store.get_report(rdb.prep_row["id"])
    version = report_store.get_version(version_id)

    doc = version["doc"]
    assert report["status"] == "needs_check" and report["current_version_id"] == version_id
    assert version["doc"] == version["ai_doc"] and version["n"] == 1
    codes = [c for dim in doc["dims"].values() for c in dim["abilities"]]
    assert len(codes) == 18 and len(set(codes)) == 18
    assert set(doc["dims"]) == {"R1", "R2", "R3", "R4"}
    assert doc["meta"]["student_name"] == "林晓雨" and doc["meta"]["y4_date"] == "2026-10-01"
    assert doc["meta"]["report_date"] == date.today().isoformat()
    assert doc["meta"]["meeting_date"] == ""          # 不认识的字段留空
    assert doc["meta"]["evidence_sources"] == "Y4 测评、M1 First Meeting 逐字稿"
    # First Touch 步骤被跳过，不算资料缺口
    assert ("first_touch", "skipped") in steps and ("checks", "done") in steps
    assert [s for s, st in steps if st == "running"] == [k for k, _ in report_pipeline.STEP_DEFS]

    # Y4 行与评级一致
    ratings = version["y4_ratings"]
    assert ratings["013"]["rating"] == "需关注" and ratings["012"]["rating"] == "相对健康"
    row = doc["dims"]["R1"]["abilities"]["R1.1"]
    assert row["y4_selected"] == ["013"]
    from blueprints.m1_report import y4_lines
    assert y4_lines(doc, ratings)["R1.1"] == [ratings["013"]["family_line"]]
    assert "013" not in ratings["013"]["family_line"]

    # 证据记录的八个字段
    evidence = version["evidence"]
    assert evidence[0]["id"] == "e1"
    for item in evidence:
        assert set(item) == {"id", "ability_codes", "source", "location", "speaker", "type",
                             "quote", "quote_verified", "interpretation", "limits", "status"}
    manifest = version["manifest"]
    assert manifest["template_file"] and manifest["kb_version"] and "adjustments" in manifest
    # 会前准备不受影响
    assert store.get_prep(rdb.prep_row["id"])["status"] == "draft"
    assert store.list_versions(rdb.prep_row["id"]) == []


def test_meeting_items_verified_deduped_and_cleaned(rdb, fake):
    _report, version = generate(rdb)
    items = {i["quote"]: i for i in version["evidence"]}
    body = items[Q_BODY]
    assert body["quote_verified"] is True and body["location"] == "逐字稿第 2 段（00:00:30）"
    assert body["status"] == "已确认" and body["ability_codes"] == ["R1.1", "R1.3"]
    # 带段号标记的重复项并入同一条；同一段话两个发言人 → 待确认
    hide = items[Q_HIDE]
    assert hide["ability_codes"] == ["R2.1", "R2.4"] and hide["location"].startswith("逐字稿第 4 段")
    assert "孙悟空" not in json.dumps(version["evidence"], ensure_ascii=False)
    assert hide["speaker"] == "待确认" and hide["status"] == "待核实"
    assert len(version["evidence"]) == 6   # 无效编号的两条被丢掉
    # §11 规则 1：引文所在段落是导师的话，整条丢弃
    assert Q_MENTOR not in items
    fake_item = items[Q_FAKE]
    assert fake_item["quote_verified"] is False and fake_item["status"] == "待核实"
    assert fake_item["location"] == ""
    # 已核验的在前，找不到的在后
    assert version["evidence"][-1]["quote"] == Q_FAKE


def test_only_m1_items_start_confirmed(monkeypatch):
    def model(prompt):
        return {"items": [_item(Q_HELP, "学生", "其他观察", ["R3.5"])]}
    monkeypatch.setattr(report_pipeline, "call_model", model)
    text = "上次作业不会，我主动问了补习班的老师"
    m1 = report_pipeline.extract_items(text, "%s\n%s", (), "M1", "逐字稿")
    other = report_pipeline.extract_items(text, "%s\n%s", (), "OTHER", "补充问卷")
    ft = report_pipeline.extract_items(text, "%s\n%s", (), "FT", "First Touch 记录")
    assert m1[0]["quote_verified"] is True and m1[0]["speaker"] == "学生"
    assert m1[0]["status"] == "已确认"
    assert other[0]["quote_verified"] is True and other[0]["status"] == "待核实"
    assert ft[0]["quote_verified"] is True and ft[0]["status"] == "待核实"


def test_unknown_speaker_becomes_pending(rdb, fake):
    fake.meeting_items = [_item(Q_HELP, "孙悟空", "不存在的类型", ["R3.5"])]
    _r, version = generate(rdb)
    item = version["evidence"][0]
    assert item["speaker"] == "待确认" and item["type"] == "其他观察"
    assert item["status"] == "待核实"


# ---------------------------------------------------------------------------
# 管道：资料不全
# ---------------------------------------------------------------------------
def test_no_transcript_is_a_clear_error(rdb, fake):
    make_report(rdb, transcript=None)
    with pytest.raises(report_pipeline.ReportError) as exc:
        report_pipeline.generate(rdb.prep_row["id"])
    assert "逐字稿" in str(exc.value)
    assert fake.calls == []                 # 没有逐字稿时一次模型也不调


def test_no_y4_is_a_clear_error(rdb, fake):
    prep = rdb.prep(rdb.incomplete_student_id, rdb.alice_id)
    report = report_store.get_or_create_report(prep["id"])
    report_store.set_transcript(report["id"], text=TRANSCRIPT)
    with pytest.raises(report_pipeline.ReportError) as exc:
        report_pipeline.generate(prep["id"])
    assert "Y4" in str(exc.value)


def test_other_materials_become_other_items(rdb, fake, monkeypatch):
    sources_text = "家长反馈：晓雨最近遇到困难会主动找老师请教，也会跟妈妈说。"
    store.add_source(rdb.prep_row["id"], category="parent", label="家长反馈",
                     text=sources_text, status="ok")
    seen = []
    original = fake.__call__

    def spy(prompt):
        if prompt.startswith("任务：从其他资料中提取证据条目"):
            seen.append(prompt)
            return {"items": [_item("会主动找老师请教", "家长", "其他观察", ["R3.5"])]}
        return original(prompt)
    monkeypatch.setattr(report_pipeline, "call_model", spy)
    _r, version = generate(rdb)
    other = [e for e in version["evidence"] if e["source"] == "OTHER"]
    assert len(seen) == 4 and len(other) == 1      # 每个维度一次调用，结果合并成一条
    assert other[0]["quote_verified"] is True and other[0]["location"] == "其他资料：家长反馈"
    assert version["doc"]["meta"]["evidence_sources"].endswith("其他补充资料")


# ---------------------------------------------------------------------------
# 管道：代码规则
# ---------------------------------------------------------------------------
def _messages(version):
    return [c["message"] for c in report_checks.run_checks(
        report_store.get_report_by_id(version["report_id"]), version, first_touch_text="")
        if c["code"] == "code_adjusted"]


def test_rules_fire_on_ai_output(rdb, fake):
    _r, version = generate(rdb)
    rows = {c: r for d in version["doc"]["dims"].values() for c, r in d["abilities"].items()}
    # y4_selected 不在映射里的被移除
    assert rows["R1.1"]["y4_selected"] == ["013"]
    # 确认发展需求没有可用的具体行为事件 → 可能存在
    assert rows["R1.1"]["tags"] == ["确认发展需求"]            # 有学生的具体行为事件
    assert rows["R1.2"]["tags"] == ["可能存在"]
    # 积极资源没有任何非 Y4 证据 → 信息不足；暂未发现没有会议证据 → 信息不足
    assert rows["R1.4"]["tags"] == ["信息不足"] and rows["R2.5"]["tags"] == ["信息不足"]
    assert rows["R1.3"]["tags"] == ["积极资源"]                # 有可用证据，保留
    # 非法标签只留第一个有效标签；一个有效都没有则为空
    assert rows["R2.1"]["tags"] == ["积极资源"]
    assert rows["R2.2"]["tags"] == []
    # 固定说明
    assert rows["R3.1"]["meeting"]["text"] == "本次会议未获得相关信息。"
    assert rows["R3.1"]["other_clues"]["text"] == "暂无直接相关资料。"
    assert rows["R1.1"]["other_clues"]["text"] == ""         # 有 Y4 行时线索栏可以空
    # 证据 id 只保留可用的
    assert rows["R1.1"]["evidence_ids"] == ["e1"]
    # 方案：无效能力被丢掉，最多 3 行
    assert [r["ability"] for r in version["doc"]["plan"]] == ["R1.1", "R2.1", "R3.5"]
    text = "\n".join(_messages(version))
    for needle in ("R1.1：所选 Y4 指标 999", "R1.2：缺少发言人已确认", "R1.4：没有可用的非 Y4 证据",
                   "R2.5：没有可用的会议证据", "R2.1：标签不合规", "R3.1：会议核实情况为空",
                   "方案中的能力编号无效", "阶段发展重点超过 3 项"):
        assert needle in text, needle


def test_dual_tag_rules_keep_the_other_tag(rdb, fake):
    fake.overrides = {"R1.1": {"tags": ["积极资源", "确认发展需求"]},
                      "R1.4": {"tags": ["积极资源", "可能存在"]},
                      "R1.2": {"tags": ["积极资源", "确认发展需求"]}}
    _r, version = generate(rdb)
    rows = {c: r for d in version["doc"]["dims"].values() for c, r in d["abilities"].items()}
    assert rows["R1.1"]["tags"] == ["积极资源", "确认发展需求"]    # 证据齐全，原样保留
    assert rows["R1.4"]["tags"] == ["可能存在"]                   # 去掉没有证据的积极资源
    assert rows["R1.2"]["tags"] == ["积极资源", "可能存在"]       # 确认发展需求降级


def test_ai_omitting_an_ability_leaves_it_blank_and_flagged(rdb, fake, monkeypatch):
    original = fake._dim

    def drop(prompt):
        result = original(prompt)
        result["abilities"] = [a for a in result["abilities"] if a["code"] != "R4.3"]
        return result
    monkeypatch.setattr(fake, "_dim", drop)
    _r, version = generate(rdb)
    assert version["doc"]["dims"]["R4"]["abilities"]["R4.3"]["tags"] == []
    assert any("R4.3：AI 没有返回" in m for m in _messages(version))


def test_failed_model_call_surfaces(rdb, fake):
    make_report(rdb)
    fake.fail = AnalysisError("AI 服务繁忙，请稍后重试")
    with pytest.raises(AnalysisError):
        report_pipeline.generate(rdb.prep_row["id"])
    assert report_store.get_report(rdb.prep_row["id"])["current_version_id"] is None


def test_safety_hits_are_confirmed_by_model_and_stored(rdb, fake, monkeypatch):
    text = TRANSCRIPT + "\n[00:03:00] 学生：有时候我会想不想活了，但很快就过去了。"
    report = make_report(rdb, transcript=text)
    original = fake.__call__

    def with_safety(prompt):
        if "是否包含需要立即人工核实" in prompt:
            payload = json.loads(prompt.split("【安全片段】\n", 1)[1])
            return {"confirmed": True, "items": [payload[0]]}
        return original(prompt)
    monkeypatch.setattr(report_pipeline, "call_model", with_safety)
    report_pipeline.generate(rdb.prep_row["id"])
    row = report_store.get_report_by_id(report["id"])
    assert len(row["safety"]) == 1 and row["safety"][0]["source_ref"] == "逐字稿第 9 段"
    version = report_store.current_version(report["id"])
    assert "safety_unacked" in {c["code"] for c in report_checks.run_checks(
        row, version, first_touch_text="")}
    # 不写进家庭字段
    family = " ".join(t for _p, t in report_checks.family_fields(version["doc"]))
    assert "不想活" not in family


def test_job_failure_restores_status_and_writes_chinese_error(rdb, fake, tmp_path):
    report = make_report(rdb)
    report_store.set_status(report["id"], "reviewing")
    previous = report_store.begin_generation(report["id"])
    m1_jobs.write_job("b" * 32, status="queued", steps=report_jobs.new_steps())
    fake.fail = AnalysisError("AI 服务繁忙，请稍后重试")
    with pytest.raises(AnalysisError):
        report_jobs.run_job("b" * 32, {"prep_id": rdb.prep_row["id"], "report_id": report["id"],
                                       "previous_status": previous, "actor_id": rdb.alice_id})
    job = m1_jobs.read_job("b" * 32)
    assert job["status"] == "error" and job["message"].startswith("生成失败：")
    assert job["prep_id"] == rdb.prep_row["id"]
    assert report_store.get_report(rdb.prep_row["id"])["status"] == "reviewing"


def test_job_success_writes_done_and_steps(rdb, fake):
    report = make_report(rdb)
    previous = report_store.begin_generation(report["id"])
    m1_jobs.write_job("c" * 32, status="queued", steps=report_jobs.new_steps())
    version_id = report_jobs.run_job("c" * 32, {
        "prep_id": rdb.prep_row["id"], "report_id": report["id"],
        "previous_status": previous, "actor_id": rdb.alice_id})
    job = m1_jobs.read_job("c" * 32)
    assert job["status"] == "done" and job["result"] == {"version_id": version_id}
    assert [s["step"] for s in job["steps"]] == [k for k, _ in report_pipeline.STEP_DEFS]
    assert {s["state"] for s in job["steps"]} <= {"done", "skipped"}


def test_load_fixture_refuses_the_real_database(rdb, monkeypatch, tmp_path):
    from sqlalchemy import create_engine
    real = BASE_DIR / "data" / "y4_students.db"
    fake_engine = create_engine("sqlite:///%s" % real)       # 只构造，不连接
    monkeypatch.setattr(_db, "engine", fake_engine)
    path = tmp_path / "doc.json"
    path.write_text("{}", encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        report_jobs.load_fixture(rdb.prep_row["id"], str(path))
    assert "y4_students.db" in str(exc.value)


def test_load_fixture_loads_an_ai_draft(rdb, fake, tmp_path):
    _r, version = generate(rdb)
    path = tmp_path / "doc.json"
    path.write_text(json.dumps({"doc": version["doc"], "evidence": version["evidence"],
                                "y4_ratings": version["y4_ratings"]}, ensure_ascii=False),
                    encoding="utf-8")
    prep = rdb.prep(rdb.other_student_id, rdb.bob_id)
    version_id = report_jobs.load_fixture(prep["id"], str(path))
    loaded = report_store.get_version(version_id)
    assert loaded["doc"] == loaded["ai_doc"] == version["doc"]
    assert report_store.get_report(prep["id"])["status"] in ("ai_draft", "needs_check")


# ---------------------------------------------------------------------------
# 质量检查
# ---------------------------------------------------------------------------
def _clean(rdb, fake):
    """生成后把唯一的阻断问题（R2.2 没有标签）改好，得到一份没有阻断项的报告。"""
    report, version = generate(rdb)
    doc = copy.deepcopy(version["doc"])
    doc["dims"]["R2"]["abilities"]["R2.2"]["tags"] = ["信息不足"]
    doc["dims"]["R2"]["abilities"]["R2.3"]["meeting"]["text"] = "学生提到有时会走神。"
    doc["meta"]["meeting_date"] = "2026-10-20"
    return report_store.get_report_by_id(report["id"]), dict(version, doc=doc)


def _codes(report, version, level=None):
    return {c["code"] for c in report_checks.run_checks(report, version, first_touch_text="")
            if level in (None, c["level"])}


def test_generation_blocks_only_on_the_real_problem(rdb, fake):
    report, version = generate(rdb)
    blocks = [c for c in version["checks"] if c["level"] == "block"]
    assert {c["code"] for c in blocks} == {"no_tag"}
    assert blocks[0]["path"] == ["dims", "R2", "abilities", "R2.2", "tags"]


def test_clean_report_has_no_blocking_checks(rdb, fake):
    report, version = _clean(rdb, fake)
    assert _codes(report, version, "block") == set()


def _mutate(version, fn):
    version = copy.deepcopy(version)
    fn(version)
    return version


def _row(version, code):
    dim = "R%s" % code[1]
    return version["doc"]["dims"][dim]["abilities"][code]


BLOCK_CASES = {
    "missing_ability": lambda v: v["doc"]["dims"]["R3"]["abilities"].pop("R3.2"),
    "tag_invalid": lambda v: _row(v, "R1.1").update(tags=["信息不足", "积极资源"]),
    "no_tag": lambda v: _row(v, "R1.1").update(tags=[]),
    "field_empty": lambda v: v["doc"]["portrait"]["R1"].update(text=""),
    "quote_unverified": lambda v: _row(v, "R1.1")["meeting"].update(text="他说“根本没有说过的话”。"),
    "quote_speaker": lambda v: (
        v["evidence"].append({"id": "e99", "ability_codes": ["R2.1"], "source": "M1",
                              "location": "", "speaker": "导师", "type": "其他观察",
                              "quote": Q_MENTOR, "quote_verified": True, "interpretation": "",
                              "limits": "", "status": "已确认"}),
        _row(v, "R2.1")["meeting"].update(text="有人问“%s”。" % Q_MENTOR)),
    "need_speaker": lambda v: [e.update(speaker="待确认") for e in v["evidence"]
                               if "R1.1" in e["ability_codes"]],
    "old_model": lambda v: v["doc"]["review_advice"].update(text="沿用 E4 的做法。"),
}


@pytest.mark.parametrize("code", sorted(BLOCK_CASES))
def test_block_check_fires_and_clears(rdb, fake, code):
    report, good = _clean(rdb, fake)
    assert code not in _codes(report, good)
    bad = _mutate(good, BLOCK_CASES[code])
    assert code in _codes(report, bad, "block")
    assert code not in _codes(report, good)           # 改回去就消失


def test_placeholder_blocks_in_any_field(rdb, fake):
    report, good = _clean(rdb, fake)
    bad = _mutate(good, lambda v: _row(v, "R3.1")["meeting"].update(text="[ai填入]"))
    assert "field_empty" in _codes(report, bad, "block")
    bad = _mutate(good, lambda v: v["doc"]["meta"].update(school="[ai填入]"))
    assert "field_empty" in _codes(report, bad, "block")


def test_old_model_code_outside_the_18(rdb, fake):
    report, good = _clean(rdb, fake)
    bad = _mutate(good, lambda v: v["doc"]["review_advice"].update(text="关注 R1.5 与 R5.1。"))
    check = next(c for c in report_checks.run_checks(report, bad, first_touch_text="")
                 if c["code"] == "old_model")
    assert "R1.5" in check["message"] and "R5.1" in check["message"]
    ok = _mutate(good, lambda v: v["doc"]["review_advice"].update(text="关注 R1.1 与 R4.3。"))
    assert "old_model" not in _codes(report, ok)


def test_no_transcript_and_unacked_safety_block(rdb, fake):
    report, good = _clean(rdb, fake)
    assert "no_transcript" in _codes(dict(report, transcript_text=""), good, "block")
    unsafe = dict(report, safety=[{"text": "x", "source_ref": "y"}], safety_ack_at=None)
    assert "safety_unacked" in _codes(unsafe, good, "block")
    acked = dict(unsafe, safety_ack_at="2026-11-01T00:00:00")
    assert "safety_unacked" not in _codes(acked, good)


def test_scene_missing_blocks(rdb, fake, monkeypatch, tmp_path):
    report, good = _clean(rdb, fake)
    assert "scene_missing" not in _codes(report, good)
    monkeypatch.setattr(report_kb, "_SCENES_PATH", tmp_path / "nope.json")
    assert "scene_missing" in _codes(report, good, "block")


def test_quote_in_first_touch_passes():
    doc = {"dims": {"R1": {"abilities": {"R1.1": {
        "tags": ["积极资源"], "meeting": {"text": "资料写到“喜欢在放学后画画”。"}}}}}}
    version = {"doc": doc, "evidence": []}
    report = {"transcript_text": "无关内容", "safety": []}
    with_ft = report_checks.run_checks(report, version, first_touch_text="他说喜欢在放学后画画。")
    assert "quote_unverified" not in {c["code"] for c in with_ft}
    without = report_checks.run_checks(report, version, first_touch_text="")
    assert "quote_unverified" in {c["code"] for c in without}


REVIEW_CASES = {
    "y4_check": lambda v: _row(v, "R1.1").update(y4_selected=["013", "012"]) or
                          v["y4_ratings"]["012"].update(state="check"),
    "frequency_word": lambda v: _row(v, "R3.5")["meeting"].update(text="学生总是主动求助。"),
    "diagnosis_word": lambda v: v["doc"]["review_advice"].update(text="像是焦虑症。"),
    "meta_blank": lambda v: v["doc"]["meta"].update(school=""),
    "name_absent": lambda v: v["doc"]["meta"].update(student_name="王五六"),
}


@pytest.mark.parametrize("code", sorted(REVIEW_CASES))
def test_review_check_fires_without_blocking(rdb, fake, code):
    report, good = _clean(rdb, fake)
    assert code not in _codes(report, good)
    bad = _mutate(good, REVIEW_CASES[code])
    checks = report_checks.run_checks(report, bad, first_touch_text="")
    hit = [c for c in checks if c["code"] == code]
    assert hit and all(c["level"] == "review" for c in hit)
    assert "block" not in {c["level"] for c in hit}


def test_generation_flags_frequency_word_with_one_item(rdb, fake):
    # §10 会删掉没有依据的事实句，所以这里改生成后的文字：
    # R2.1 只有一条可用会议证据，用“总是”就要提示频率依据不足。
    report, good = _clean(rdb, fake)
    bad = _mutate(good, lambda v: _row(v, "R2.1")["meeting"].update(
        text="学生总是选择独自待着。"))
    hit = [c for c in report_checks.run_checks(report, bad, first_touch_text="")
           if c["code"] == "frequency_word"]
    assert hit and hit[0]["path"] == ["dims", "R2", "abilities", "R2.1", "meeting"]


def test_frequency_word_allowed_with_two_usable_items(rdb, fake):
    report, good = _clean(rdb, fake)
    for item in good["evidence"]:
        if item["quote"] in (Q_HELP, Q_BODY):
            item["ability_codes"] = ["R3.5"]
    ok = _mutate(good, lambda v: _row(v, "R3.5")["meeting"].update(text="学生总是主动求助。"))
    assert "frequency_word" not in _codes(report, ok)


def test_fake_quote_is_flagged_and_real_quote_passes(rdb, fake):
    report, good = _clean(rdb, fake)
    fake_item = next(e for e in good["evidence"] if e["quote"] == Q_FAKE)
    assert fake_item["quote_verified"] is False
    real = _mutate(good, lambda v: _row(v, "R1.1")["meeting"].update(text="他说“%s”。" % Q_BODY))
    assert "quote_unverified" not in _codes(report, real)
    fake_text = _mutate(good, lambda v: _row(v, "R1.1")["meeting"].update(text="他说“%s”。" % Q_FAKE))
    assert "quote_unverified" in _codes(report, fake_text, "block")
    # 引号里是标签名不算引文
    tagged = _mutate(good, lambda v: _row(v, "R1.1")["meeting"].update(text="判断为“可能存在”。"))
    assert "quote_unverified" not in _codes(report, tagged)
    # 三种引号都识别
    for text in ('他说"没有这回事"。', "他说「没有这回事」。"):
        bad = _mutate(good, lambda v: _row(v, "R1.1")["meeting"].update(text=text))
        assert "quote_unverified" in _codes(report, bad)


# ---------------------------------------------------------------------------
# 路由：状态流转与保存
# ---------------------------------------------------------------------------
def doc_put(client, rdb, rev, changes):
    return client.put(url(rdb, "/doc"), json={"rev": rev, "changes": changes})


def fix_tag(client, rdb, rev):
    return doc_put(client, rdb, rev, [{"path": ["dims", "R2", "abilities", "R2.2", "tags"],
                                       "value": ["信息不足"]}])


def generated_via_api(client, rdb, fake, inline_jobs):
    admin_login(client, rdb)
    res = client.post(url(rdb, "/transcript"), json={"text": TRANSCRIPT})
    assert res.status_code == 200 and res.get_json()["report"]["transcript_length"] > 100
    res = client.post(url(rdb, "/generate"), json={})
    assert res.status_code == 200 and res.get_json()["job_id"] == "a" * 32
    return client.get(url(rdb)).get_json()


def test_status_path(client, rdb, fake, inline_jobs):
    payload = generated_via_api(client, rdb, fake, inline_jobs)
    assert payload["report"]["status"] == "needs_check" and payload["report"]["label"] == "待核实"
    # 有阻断问题时不能审核通过，并带回阻断项
    res = client.post(url(rdb, "/approve"))
    assert res.status_code == 400 and res.get_json()["blocking"][0]["code"] == "no_tag"
    res = fix_tag(client, rdb, payload["report"]["rev"])
    assert res.status_code == 200 and res.get_json()["status"] == "reviewing"
    assert not [c for c in res.get_json()["checks"] if c["level"] == "block"]
    assert client.post(url(rdb, "/publish")).status_code == 409        # 还没审核通过
    res = client.post(url(rdb, "/approve"))
    assert res.status_code == 200 and res.get_json()["report"]["status"] == "approved"
    assert res.get_json()["report"]["approved_by"] == rdb.admin_id
    # 审核通过后保存 → 回到审核中
    rev = client.get(url(rdb)).get_json()["report"]["rev"]
    res = doc_put(client, rdb, rev, [{"path": ["review_advice"], "value": "改一下回顾建议。"}])
    assert res.status_code == 200 and res.get_json()["status"] == "reviewing"
    assert client.get(url(rdb)).get_json()["report"]["approved_by"] is None
    assert client.post(url(rdb, "/approve")).status_code == 200
    res = client.post(url(rdb, "/publish"))
    assert res.status_code == 200 and res.get_json()["report"]["status"] == "published"
    # 正式发布后保存被拒；重新打开后可改
    rev = client.get(url(rdb)).get_json()["report"]["rev"]
    res = doc_put(client, rdb, rev, [{"path": ["review_advice"], "value": "再改。"}])
    assert res.status_code == 409 and "重新打开" in res.get_json()["error"]
    res = client.post(url(rdb, "/reopen"))
    assert res.status_code == 200 and res.get_json()["report"]["status"] == "reviewing"
    assert client.post(url(rdb, "/reopen")).status_code == 409           # 审核中不能再 reopen
    actions = [r.action for r in Session(rdb.engine).execute(select(_gt.AuditLog)).scalars()]
    for action in ("m1.report_transcript", "m1.report_generate", "m1.report_edit",
                   "m1.report_approve", "m1.report_publish", "m1.report_reopen"):
        assert action in actions


def test_put_doc_validation_rev_and_impacts(client, rdb, fake, inline_jobs):
    payload = generated_via_api(client, rdb, fake, inline_jobs)
    rev = payload["report"]["rev"]
    bad_paths = [
        ["dims", "R1", "abilities", "R1.1", "internal_note"],
        ["dims", "R1", "abilities", "R2.1", "meeting"],
        ["dims", "R9", "core_finding"], ["meta", "unknown"], ["evidence"], ["plan", 0],
        ["dims", "R1", "abilities", "R1.1", "evidence_ids"]]
    for path in bad_paths:
        res = doc_put(client, rdb, rev, [{"path": path, "value": "x"}])
        assert res.status_code == 400, path
    for path, value in [
            (["dims", "R1", "abilities", "R1.1", "tags"], ["信息不足", "积极资源"]),
            (["dims", "R1", "abilities", "R1.1", "tags"], ["不存在"]),
            (["dims", "R1", "abilities", "R1.1", "y4_selected"], ["060"]),
            (["dims", "R1", "core_finding"], 5),
            (["plan"], []), (["plan"], [{"ability": "R9.9"}] * 2),
            (["plan"], [{"ability": "R1.1"}] * 4)]:
        assert doc_put(client, rdb, rev, [{"path": path, "value": value}]).status_code == 400
    assert doc_put(client, rdb, rev, []).status_code == 400
    # 一个坏的就整批不生效
    res = doc_put(client, rdb, rev, [{"path": ["review_advice"], "value": "好"},
                                     {"path": ["bogus"], "value": "x"}])
    assert res.status_code == 400
    assert client.get(url(rdb)).get_json()["doc"]["review_advice"]["src"] == "ai"
    # 错误的 rev
    res = doc_put(client, rdb, rev + 7, [{"path": ["review_advice"], "value": "好"}])
    assert res.status_code == 409 and res.get_json()["rev"] == rev
    assert client.put(url(rdb, "/doc"), json={"changes": []}).status_code == 400

    # 文字修改 → src 变 edited；没变的字段保持 ai
    res = doc_put(client, rdb, rev, [
        {"path": ["review_advice"], "value": "改过的建议"},
        {"path": ["meta", "meeting_date"], "value": "2026-10-20"},
        {"path": ["dims", "R1", "core_finding"], "value": "本维度的资料有限，还需要了解。"}])
    body = res.get_json()
    assert res.status_code == 200 and body["rev"] == rev + 1 and body["impacts"] == []
    doc = client.get(url(rdb)).get_json()["doc"]
    assert doc["review_advice"] == {"text": "改过的建议", "src": "edited"}
    assert doc["dims"]["R1"]["core_finding"]["src"] == "ai"
    assert doc["meta"]["meeting_date"] == "2026-10-20"

    # 标签改变 → impacts，附录随标签变化
    before = {r["code"] for r in body["appendix"]}
    res = doc_put(client, rdb, rev + 1, [
        {"path": ["dims", "R3", "abilities", "R3.2", "tags"], "value": ["可能存在"]}])
    body = res.get_json()
    assert body["impacts"] == ["综合判断已改。附录已自动更新，请检查 04 和 05 是否需要调整。"]
    assert {r["code"] for r in body["appendix"]} == before | {"R3.2"}
    row = client.get(url(rdb)).get_json()["doc"]["dims"]["R3"]["abilities"]["R3.2"]
    assert row["tags_src"] == "edited"
    # 方案：整体替换，字段变成 edited
    plan = [{"ability": "R2.1", "goal": "新目标", "mentor": {"text": "导师支持。"},
             "family": "家庭支持", "evidence": "成长证据"}]
    res = doc_put(client, rdb, rev + 2, [{"path": ["plan"], "value": plan}])
    assert res.status_code == 200
    saved = client.get(url(rdb)).get_json()["doc"]["plan"]
    assert len(saved) == 1 and saved[0]["goal"] == {"text": "新目标", "src": "edited"}
    assert saved[0]["mentor"]["src"] == "ai"        # 文字没变


def test_put_evidence(client, rdb, fake, inline_jobs):
    payload = generated_via_api(client, rdb, fake, inline_jobs)
    rev = payload["report"]["rev"]
    fake_id = next(e["id"] for e in payload["evidence"] if e["quote"] == Q_FAKE)
    path = url(rdb, "/evidence/" + fake_id)
    assert client.put(path, json={"rev": rev}).status_code == 400
    assert client.put(path, json={"rev": rev, "status": "随便"}).status_code == 400
    assert client.put(path, json={"rev": rev, "speaker": "路人"}).status_code == 400
    assert client.put(url(rdb, "/evidence/e999"), json={"rev": rev, "status": "不采用"}).status_code == 404
    assert client.put(path, json={"rev": rev + 3, "status": "不采用"}).status_code == 409
    res = client.put(path, json={"rev": rev, "status": "不采用", "speaker": "待确认"})
    assert res.status_code == 200 and res.get_json()["evidence"]["status"] == "不采用"
    assert res.get_json()["status"] == "reviewing"
    reloaded = client.get(url(rdb)).get_json()
    assert next(e for e in reloaded["evidence"] if e["id"] == fake_id)["speaker"] == "待确认"


def test_safety_ack_clears_the_block(client, rdb, fake, inline_jobs, monkeypatch):
    payload = generated_via_api(client, rdb, fake, inline_jobs)
    report = report_store.get_report(rdb.prep_row["id"])
    with Session(rdb.engine) as sess:
        row = sess.get(report_store.M1Report, report["id"])
        row.safety = json.dumps([{"text": "片段", "source_ref": "逐字稿第 9 段"}], ensure_ascii=False)
        sess.commit()
    codes = {c["code"] for c in client.get(url(rdb)).get_json()["checks"]}
    assert "safety_unacked" in codes
    res = client.post(url(rdb, "/safety-ack"))
    assert res.status_code == 200 and res.get_json()["report"]["safety_ack_by"] == rdb.admin_id
    codes = {c["code"] for c in client.get(url(rdb)).get_json()["checks"]}
    assert "safety_unacked" not in codes


def test_generate_with_edits_needs_confirmation(client, rdb, fake, inline_jobs):
    payload = generated_via_api(client, rdb, fake, inline_jobs)
    assert payload["has_edits"] is False
    # 没改过：直接再生成，新版本，旧版本保留
    assert client.post(url(rdb, "/generate"), json={}).status_code == 200
    rev = client.get(url(rdb)).get_json()["report"]["rev"]
    doc_put(client, rdb, rev, [{"path": ["review_advice"], "value": "我改过了"}])
    assert client.get(url(rdb)).get_json()["has_edits"] is True
    res = client.post(url(rdb, "/generate"), json={})
    assert res.status_code == 409 and res.get_json()["error"] == "需要确认覆盖"
    versions_before = client.get(url(rdb)).get_json()["versions"]
    assert client.get(url(rdb)).get_json()["doc"]["review_advice"]["text"] == "我改过了"
    res = client.post(url(rdb, "/generate"), json={"confirm_overwrite": True})
    assert res.status_code == 200
    after = client.get(url(rdb)).get_json()
    assert len(after["versions"]) == len(versions_before) + 1
    assert after["doc"]["review_advice"]["text"] == "回顾时注意学生是否愿意说出自己的感受。"
    assert after["report"]["status"] == "needs_check" and after["has_edits"] is False
    old = report_store.get_version(versions_before[-1]["id"])
    assert old["doc"]["review_advice"]["text"] == "我改过了"      # 旧版本还在


def test_generate_guards(client, rdb, fake, inline_jobs):
    admin_login(client, rdb)
    res = client.post(url(rdb, "/generate"), json={})
    assert res.status_code == 400 and "逐字稿" in res.get_json()["error"]
    client.post(url(rdb, "/transcript"), json={"text": TRANSCRIPT})
    report = report_store.get_report(rdb.prep_row["id"])
    report_store.set_status(report["id"], "generating")
    assert client.post(url(rdb, "/generate"), json={}).status_code == 409
    assert client.post(url(rdb, "/transcript"), json={"text": "新的"}).status_code == 409


def test_generate_launch_failure_restores_status(client, rdb, fake, monkeypatch):
    admin_login(client, rdb)
    client.post(url(rdb, "/transcript"), json={"text": TRANSCRIPT})

    def boom(*a, **k):
        raise RuntimeError("启动不了")
    monkeypatch.setattr(report_jobs, "launch_job", boom)
    res = client.post(url(rdb, "/generate"), json={})
    assert res.status_code == 500 and "启动" in res.get_json()["error"]
    assert report_store.get_report(rdb.prep_row["id"])["status"] == "draft"


def test_transcript_upload_replaces_and_validates(client, rdb):
    admin_login(client, rdb)
    import io
    res = client.post(url(rdb, "/transcript"), data={
        "file": (io.BytesIO(TRANSCRIPT.encode("utf-8")), "会议.txt")},
        content_type="multipart/form-data")
    assert res.status_code == 200
    first = report_store.get_report(rdb.prep_row["id"])
    assert first["transcript_filename"] == "会议.txt" and Path(first["transcript_path"]).exists()
    assert str(rdb.prep_row["id"]) in first["transcript_path"]
    res = client.post(url(rdb, "/transcript"), json={"text": "换成粘贴的文字"})
    second = report_store.get_report(rdb.prep_row["id"])
    assert second["transcript_text"] == "换成粘贴的文字" and second["transcript_path"] == ""
    assert not Path(first["transcript_path"]).exists()          # 旧文件被清理
    assert client.post(url(rdb, "/transcript"), json={"text": "   "}).status_code == 400
    bad = client.post(url(rdb, "/transcript"), data={
        "file": (io.BytesIO(b"x"), "会议.exe")}, content_type="multipart/form-data")
    assert bad.status_code in (400, 415, 422)
    assert "transcript_text" not in client.get(url(rdb)).get_json()["report"]


def test_get_report_payload_shape(client, rdb, fake, inline_jobs):
    payload = generated_via_api(client, rdb, fake, inline_jobs)
    assert set(payload) >= {"ok", "report", "inputs", "doc", "evidence", "ratings", "mapped",
                            "checks", "appendix", "fixed", "has_edits"}
    assert set(payload["inputs"]) == {"y4", "first_touch", "others"}
    assert payload["inputs"]["y4"]["complete"] is True
    assert payload["mapped"]["R1.1"] == ["013", "012", "056", "019"]
    assert payload["fixed"]["tags"][0]["key"] == "积极资源"
    assert {r["code"] for r in payload["appendix"]} == {"R1.1", "R1.2", "R2.3"}
    assert payload["report"]["safety"] == [] and payload["report"]["transcript_length"] > 100


def test_report_before_generation(client, rdb):
    admin_login(client, rdb)
    payload = client.get(url(rdb)).get_json()
    assert payload["doc"] is None and payload["report"]["status"] == "draft"
    assert client.post(url(rdb, "/approve")).status_code == 409
    assert doc_put(client, rdb, 1, [{"path": ["review_advice"], "value": "x"}]).status_code == 409
    assert client.get("/m1/preps/%d/report/print" % rdb.prep_row["id"]).status_code == 404


def test_report_statuses(client, rdb, fake, inline_jobs):
    generated_via_api(client, rdb, fake, inline_jobs)
    other = rdb.prep(rdb.other_student_id, rdb.bob_id)
    data = client.get("/api/m1/report-statuses").get_json()["statuses"]
    assert data[str(rdb.prep_row["id"])] == {"status": "needs_check", "label": "待核实"}
    assert data[str(other["id"])] == {"status": "draft", "label": "待生成"}
    login_as(client, rdb.alice_id, "advisor", "Alice")
    scoped = client.get("/api/m1/report-statuses").get_json()["statuses"]
    assert str(other["id"]) not in scoped and str(rdb.prep_row["id"]) in scoped


# ---------------------------------------------------------------------------
# 权限
# ---------------------------------------------------------------------------
def advisor_login(client, user_id, name, **policy):
    with client.session_transaction() as sess:
        sess["user_id"] = user_id
        sess["role"] = "advisor"
        sess["advisor_name"] = name
        sess["display_name"] = name
        sess.update(policy)


ENDPOINTS = [("get", ""), ("post", "/transcript"), ("post", "/generate"), ("put", "/doc"),
             ("put", "/evidence/e1"), ("post", "/safety-ack"), ("post", "/confirm-flag"),
             ("post", "/approve"), ("post", "/publish"), ("post", "/reopen")]


def _hit(client, rdb, method, tail):
    return getattr(client, method)(url(rdb, tail), json={"rev": 1, "text": "x", "changes": []})


def test_viewer_gets_403_everywhere(client, rdb):
    login_as(client, rdb.viewer_id, "viewer")
    for method, tail in ENDPOINTS:
        assert _hit(client, rdb, method, tail).status_code == 403, tail
    assert client.get("/api/m1/report-statuses").status_code == 403
    assert client.get("/m1/preps/%d/report" % rdb.prep_row["id"]).status_code == 403


def test_advisor_with_m1_off_gets_403(client, rdb):
    advisor_login(client, rdb.alice_id, "Alice", m1_access=0)
    for method, tail in ENDPOINTS:
        assert _hit(client, rdb, method, tail).status_code == 403, tail
    assert client.get("/m1/preps/%d/report" % rdb.prep_row["id"]).status_code == 403


def test_summary_account_gets_403(client, rdb):
    advisor_login(client, rdb.alice_id, "Alice", m1_access=1, detail_level="summary",
                  student_scope="all")
    for method, tail in ENDPOINTS:
        res = _hit(client, rdb, method, tail)
        assert res.status_code == 403, tail
        assert res.get_json()["error"] == "当前账号不能查看会后报告"
    assert client.get("/api/m1/report-statuses").status_code == 403
    for page in ("", "/print", "/evidence"):
        assert client.get("/m1/preps/%d/report%s" % (rdb.prep_row["id"], page)).status_code == 403


def test_own_students_advisor_cannot_open_another_advisors_prep(client, rdb):
    other = rdb.prep(rdb.other_student_id, rdb.bob_id)
    advisor_login(client, rdb.alice_id, "Alice", m1_access=1, detail_level="full",
                  student_scope="own")
    base = "/api/m1/preps/%d/report" % other["id"]
    for method, tail in ENDPOINTS:
        res = getattr(client, method)(base + tail, json={"rev": 1, "text": "x", "changes": []})
        assert res.status_code == 403, tail
    assert client.get("/m1/preps/%d/report" % other["id"]).status_code == 403
    assert client.get(base).status_code == 403


def test_all_scope_advisor_can_open_any_prep(client, rdb):
    other = rdb.prep(rdb.other_student_id, rdb.bob_id)
    advisor_login(client, rdb.alice_id, "Alice", m1_access=1, detail_level="full",
                  student_scope="all")
    assert client.get("/api/m1/preps/%d/report" % other["id"]).status_code == 200
    assert client.get("/m1/preps/%d/report" % other["id"]).status_code == 200


def test_missing_prep_is_404(client, rdb):
    admin_login(client, rdb)
    assert client.get("/api/m1/preps/999999/report").status_code == 404
    assert client.get("/m1/preps/999999/report").status_code == 404


def test_job_status_endpoint_checks_access(client, rdb, fake):
    report = make_report(rdb)
    previous = report_store.begin_generation(report["id"])
    m1_jobs.write_job("d" * 32, status="running", prep_id=rdb.prep_row["id"],
                      report_id=report["id"], steps=report_jobs.new_steps(),
                      previous_status=previous)
    admin_login(client, rdb)
    assert client.get("/api/m1/jobs/" + "d" * 32).get_json()["job"]["status"] == "running"
    other = rdb.prep(rdb.other_student_id, rdb.bob_id)
    m1_jobs.write_job("e" * 32, status="running", prep_id=other["id"])
    advisor_login(client, rdb.alice_id, "Alice", m1_access=1, detail_level="full",
                  student_scope="own")
    assert client.get("/api/m1/jobs/" + "e" * 32).status_code == 403


# ---------------------------------------------------------------------------
# 会前准备不受影响；日志不含内容
# ---------------------------------------------------------------------------
def test_prep_tables_untouched_by_report_flow(client, rdb, fake, inline_jobs):
    before = store.get_prep(rdb.prep_row["id"])
    generated_via_api(client, rdb, fake, inline_jobs)
    after = store.get_prep(rdb.prep_row["id"])
    for key in ("status", "rev", "current_version_id", "safety_ack_at"):
        assert before[key] == after[key]
    assert store.list_versions(rdb.prep_row["id"]) == []
    assert store.list_sources(rdb.prep_row["id"]) == []


def test_logs_contain_no_transcript_or_report_text(rdb, fake, caplog):
    caplog.set_level(logging.DEBUG)
    _report, version = generate(rdb)
    logged = "\n".join(r.getMessage() for r in caplog.records)
    texts = [Q_BODY, Q_HIDE, Q_HELP, Q_FAKE, "心跳很快", "本维度的资料有限",
             "回顾时注意学生", "晓雨", "林晓雨", "导师支持"]
    for text in texts:
        assert text not in logged, text
    assert "evidence=" in logged            # 只记录数量
    assert "m1 report generated" in logged
    report_text = " ".join(t for _p, t in report_checks.family_fields(version["doc"]))
    assert report_text and report_text not in logged


def test_report_tables_exist_on_fresh_boot(tmp_path):
    import os
    import subprocess
    import sys
    env = dict(os.environ, DATABASE_URL="sqlite:///%s" % (tmp_path / "fresh.db"),
               SECRET_KEY="boot-test")
    env.pop("Y4_ENV", None)
    env.pop("FLASK_ENV", None)
    code = ("import app, db, sqlalchemy as sa; "
            "print(sorted(t for t in sa.inspect(db.engine).get_table_names() "
            "if t.startswith('m1_report')))")
    out = subprocess.run([sys.executable, "-c", code], cwd=BASE_DIR, env=env,
                         capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr[-2000:]
    assert "['m1_report_versions', 'm1_reports']" in out.stdout
