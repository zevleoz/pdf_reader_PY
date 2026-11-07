"""新版 B3（2026-11）读取：校验 / 置空逻辑。样本 PDF 含学生信息，不入库；
设置 B3_NEW_SAMPLE=<pdf 路径> 可额外跑真实图形测量。"""
import os
from pathlib import Path

import pytest

import b3_gauge
import extract

MEASURED = {"066": 8.39, "067": 5.95, "128": 6.39, "129": 5.81,
            "069": 7.13, "070": 3.59, "131": 6.07, "132": 5.2}


def test_norms_taken_when_scores_agree():
    vision = {"066": "8.4", "067": "6.0", "069": "7.2", "070": "3.6",
              "128": "9.9", "068": "7.7", "071": "6.6"}
    upd, warn = b3_gauge.reconcile(vision, MEASURED)
    assert upd["128"] == "6.4" and upd["129"] == "5.8"
    assert upd["131"] == "6.1" and upd["132"] == "5.2"
    for code in ("068", "071", "130", "133"):   # 新版没有，模型编的也要清掉
        assert upd[code] == ""
    assert "134" not in upd and "135" not in upd   # 新分项保留视觉结果
    assert not warn


def test_norms_blank_when_score_mismatch():
    vision = {"066": "5.0", "067": "6.0", "069": "7.2", "070": "3.6"}
    upd, warn = b3_gauge.reconcile(vision, MEASURED)
    assert upd["128"] == "" and upd["129"] == ""
    assert upd["131"] == "6.1"
    assert any("066" in w for w in warn)


def test_prompt_old_b3_unchanged():
    old = extract._build_slot_prompt("B3")
    assert old == extract._build_slot_prompt("B3", new_b3=False)
    assert "068 学习动机-自我效能感" in old


def test_prompt_new_b3():
    prompt = extract._build_slot_prompt("B3", new_b3=True)
    lines = [ln for ln in prompt.splitlines()
             if extract._SCHEMA_ITEM_LINE_RE.match(ln)]
    assert len(lines) == 17
    by_code = {ln[:3]: ln for ln in lines}
    assert "学习方法实践与提升" in by_code["134"] and "得分 X/10" in by_code["134"]
    assert "学习策略执行与优化" in by_code["135"] and "得分 X/10" in by_code["135"]
    assert "一律输出" in by_code["068"] and "一律输出" in by_code["071"]
    for code, new_line in b3_gauge.NEW_LAYOUT_PROMPT_LINES.items():
        assert by_code[code] == new_line


@pytest.mark.skipif(not os.environ.get("B3_NEW_SAMPLE"), reason="needs sample PDF")
def test_real_sample():
    p = Path(os.environ["B3_NEW_SAMPLE"])
    assert b3_gauge.is_new_b3(p)
    m = b3_gauge.read_gauges(p)
    for code, printed in (("066", 8.4), ("067", 6.0), ("069", 7.2), ("070", 3.6)):
        assert abs(m[code] - printed) <= 0.15
