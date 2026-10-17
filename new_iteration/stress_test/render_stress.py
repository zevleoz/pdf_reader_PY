#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
stress_test/render_stress.py — 异常态压力测试渲染

用构造的低分/非安全型数据 (stress_data.json) 渲染 report_v2.html，
验证警示样式（红条、! 角标、肥胖体型、低百分位 clamp 等）是否正常。
输出与正式稿完全隔离（本目录下的 stress_test.pdf / preview/）。

用法: python3 render_stress.py
"""

import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
NI = HERE.parent
sys.path.insert(0, str(NI))

import render_v2  # noqa: E402

from jinja2 import Environment, FileSystemLoader, select_autoescape  # noqa: E402


def main():
    raw = json.loads((HERE / "stress_data.json").read_text(encoding="utf-8"))
    d = {item["code"]: item["value"] for item in raw["schema_124"]}
    ctx = render_v2.build_context(raw["student"], d)

    env = Environment(
        loader=FileSystemLoader(str(NI)),
        autoescape=select_autoescape(default=True, default_for_string=True),
    )
    html = env.get_template(render_v2.TEMPLATE_NAME).render(**ctx)
    out_html = HERE / "stress_rendered.html"
    out_html.write_text(html, encoding="utf-8")

    pdf_path = HERE / "stress_test.pdf"
    chrome = render_v2.find_chrome()
    subprocess.run(
        [chrome, "--headless=new", "--disable-gpu",
         f"--print-to-pdf={pdf_path}", "--no-pdf-header-footer",
         f"file://{out_html}"],
        capture_output=True, text=True, timeout=120, check=True,
    )

    import pymupdf
    preview = HERE / "preview"
    preview.mkdir(exist_ok=True)
    doc = pymupdf.open(str(pdf_path))
    for i, page in enumerate(doc):
        page.get_pixmap(dpi=100).save(str(preview / f"page_{i+1:02d}.png"))
    print(f"done -> {pdf_path.name} ({len(doc)} 页), preview/ 已更新")


if __name__ == "__main__":
    main()
