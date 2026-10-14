"""问卷中心蓝图（C 包填充内容）——A 包仅打桩。"""
from __future__ import annotations

from flask import Blueprint

from app_utils import role_required

bp = Blueprint("questionnaires", __name__)


@bp.route("/questionnaires")
@role_required("admin", "advisor")
def questionnaires_page():
    """占位页：C 包将替换为任务列表/题库/识别规则。"""
    return ("<!DOCTYPE html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\">"
            "<title>问卷中心建设中 — Y4</title></head><body>"
            "<p>问卷中心建设中</p></body></html>")
