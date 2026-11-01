"""_DISPLAY_LABELS 与 data_points.POINT_META 的亲属/同伴归属一致性。"""
import data_points
from m1 import y4_evidence

_WORDS = ("母亲", "父亲", "同伴")


def test_display_labels_keep_attachment_owner():
    for code, display in y4_evidence._DISPLAY_LABELS.items():
        meta_label = str((data_points.POINT_META.get(code) or {}).get("label") or "")
        owners = [w for w in _WORDS if w in meta_label]
        for word in owners:
            assert word in display, f"{code}: POINT_META={meta_label!r} but display={display!r}"
        for word in _WORDS:
            if word not in owners:
                assert word not in display, f"{code}: display={display!r} wrongly mentions {word}"


def test_code_030_is_father_closeness():
    assert "父亲" in y4_evidence._label("030")


def test_code_031_is_peer_closeness():
    assert "同伴" in y4_evidence._label("031")
