"""S4-U3: B6 排序（087-094 / 110-124）取自 PDF 文本 + 名称校验。"""
from pathlib import Path

import pytest

try:
    import pymupdf as fitz
except ImportError:  # pragma: no cover
    import fitz

import extract

ABILITY = ["人际关系能力", "音乐能力", "内省能力", "身体运动能力",
           "语言能力", "自然能力", "逻辑数学能力", "空间能力"]


def _pdf(tmp_path, pages):
    """pages: list of list[str] (每页的文本行)。"""
    doc = fitz.open()
    for lines in pages:
        page = doc.new_page()
        y = 60
        for ln in lines:
            page.insert_text((50, y), ln, fontname="china-s", fontsize=11)
            y += 22
    p = tmp_path / "report_B6_test.pdf"
    doc.save(str(p))
    doc.close()
    return p


def _ranking_lines(names, title="我的能力优势一览表"):
    out = [title]
    for i, n in enumerate(names, 1):
        out += [f"NO.{i}", n]
    return out


def test_overview_page_gives_eight_names(tmp_path):
    p = _pdf(tmp_path, [["封面"], _ranking_lines(ABILITY)])
    assert extract.read_b6_ability_ranking(p) == ABILITY


def test_score_and_major_pages_ignored(tmp_path):
    scores = ["我的能力得分"] + [x for i in range(1, 9) for x in (f"NO.{i}", "7分")]
    majors = ["推荐专业"] + [x for i in range(1, 9) for x in (f"NO.{i}", "体育经济与管理")]
    p = _pdf(tmp_path, [scores, majors])
    assert extract.read_b6_ability_ranking(p) is None


def test_seven_repeated_unknown_give_none(tmp_path):
    assert extract.parse_b6_ability_ranking("\n".join(_ranking_lines(ABILITY[:7]))) is None
    rep = ABILITY[:7] + [ABILITY[0]]
    assert extract.parse_b6_ability_ranking("\n".join(_ranking_lines(rep))) is None
    unk = ABILITY[:7] + ["事业型"]
    assert extract.parse_b6_ability_ranking("\n".join(_ranking_lines(unk))) is None
    p = _pdf(tmp_path, [_ranking_lines(unk)])
    assert extract.read_b6_ability_ranking(p) is None


def test_text_value_wins_for_abilities():
    assert extract.b6_rank_pick("087", "语言能力", "人际关系能力", True) == "人际关系能力"


def test_without_text_page_old_behaviour_ai_valid():
    assert extract.b6_rank_pick("087", "语言能力", "人际关系能力", False) == "语言能力"


def test_career_type_dropped_for_089(capsys):
    assert extract.b6_rank_pick("089", "事业型", "内省能力", False) == "内省能力"
    assert "[B6 排序] 089 视觉值「事业型」不是能力名称，已忽略" in capsys.readouterr().out


def test_unknown_value_name_dropped():
    assert extract.b6_rank_pick("112", "乱写", "美的追求", False) == "美的追求"
    assert extract.b6_rank_pick("112", "乱写", None, False) == ""


def test_valid_ai_value_kept_for_values():
    assert extract.b6_rank_pick("110", "生活方式", "创造发明", False) == "生活方式"
    assert extract.b6_rank_pick("110", " 生活 方式 ", "创造发明", False) == " 生活 方式 ".strip()


def test_near_miss_not_fixed():
    assert not extract.b6_rank_ai_value_ok("090", "逻辑数学")


def test_other_codes_untouched():
    assert extract.b6_rank_pick("086", "x", "y", True) is None


REAL = Path(__file__).parent / "input" / "report_B6_高中.pdf"


@pytest.mark.skipif(not REAL.exists(), reason="real sample not present")
def test_real_sample():
    assert extract.read_b6_ability_ranking(REAL) == ABILITY
