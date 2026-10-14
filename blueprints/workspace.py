"""工作台蓝图（B 包填充内容）——A 包仅打桩。"""
from __future__ import annotations

from flask import Blueprint

from app_utils import login_required

bp = Blueprint("workspace", __name__)


@bp.route("/workspace")
@login_required
def workspace_page():
    """占位页：B 包将替换为真实工作台（待确认问卷/进行中作业/活跃学生）。"""
    return render_template_stub()


def render_template_stub():
    return ("<!DOCTYPE html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\">"
            "<title>工作台建设中 — Y4</title></head><body>"
            "<p>工作台建设中</p></body></html>")
