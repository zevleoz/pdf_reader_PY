"""DP8：心有灵析换成淡紫（owner 11-12），蓝色只留在瑞士数据色。"""
from __future__ import annotations

from app_utils import BASE_DIR

M1_CSS = BASE_DIR / "static" / "m1" / "ark.css"
M1_STATIC = BASE_DIR / "static" / "m1"
M1_TEMPLATES = BASE_DIR / "templates" / "m1"
PLATFORMS = BASE_DIR / "templates" / "platforms.html"
REPORT_PRINT = BASE_DIR / "templates" / "m1" / "report_print.html"

LAVENDER = "#D6C8F0"
PURPLE = "#6E52B5"
INK = "#2B1F45"
TINT = "#F3EFFB"


def _luminance(colour: str) -> float:
    value = colour.lstrip("#")
    channels = [int(value[i:i + 2], 16) / 255 for i in (0, 2, 4)]

    def linear(channel: float) -> float:
        return channel / 12.92 if channel <= 0.03928 \
            else ((channel + 0.055) / 1.055) ** 2.4

    return 0.2126 * linear(channels[0]) + 0.7152 * linear(channels[1]) \
        + 0.0722 * linear(channels[2])


def _contrast(one: str, other: str) -> float:
    high, low = sorted((_luminance(one), _luminance(other)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def test_platform_line_uses_lavender_family():
    line = next(row for row in M1_CSS.read_text(encoding="utf-8").splitlines()
                if '.app[data-platform="m1"]{' in row)
    for colour in (LAVENDER, PURPLE, INK, TINT, "#FFFFFF"):
        assert colour in line
    assert "--shell-ink:%s" % INK in line


def test_no_blue_left_in_m1_views():
    for base in (M1_STATIC, M1_TEMPLATES):
        for path in base.rglob("*"):
            if not path.is_file() or path.suffix not in (".css", ".js", ".html"):
                continue
            text = path.read_text(encoding="utf-8").upper()
            # 唯一例外是瑞士世界的图表数据色（D2 走中性灰阶，数据色保留）。
            text = text.replace("--D3:#0B3FD6", "")
            assert "0B3FD6" not in text, path
    assert "#0B3FD6" not in PLATFORMS.read_text(encoding="utf-8").upper()


def test_info_colour_is_lavender():
    css = (M1_STATIC / "m1.css").read_text(encoding="utf-8").upper()
    assert "#1D4ED8" not in css
    assert "#EEF4FF" not in css
    assert "--INFO: #6E52B5; --INFO-SOFT: #F3EFFB;" in css


def test_platform_card_artwork_is_purple():
    html = PLATFORMS.read_text(encoding="utf-8")
    assert 'fill="%s"' % PURPLE in html


def test_report_edit_bar_is_purple():
    html = REPORT_PRINT.read_text(encoding="utf-8")
    assert ".edit-bar button.pri { background: %s; border-color: %s;" % (
        PURPLE, PURPLE) in html
    assert ".edit-bar button.link { border: 0; background: none; color: %s;" % PURPLE in html
    assert "[data-path]:focus { outline: 2px solid %s; background: %s; }" % (
        PURPLE, TINT) in html
    assert "#0B3FD6" not in html.upper()


def test_text_pairs_stay_readable():
    pairs = [(INK, LAVENDER), ("#FFFFFF", PURPLE), (PURPLE, "#FFFFFF"),
             (PURPLE, TINT)]
    for one, other in pairs:
        assert _contrast(one, other) >= 4.5, (one, other)
