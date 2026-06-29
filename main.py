"""入口脚本：依次调用 提取 → 校验 → 生成 PDF。

用法：
  python main.py              # 完整流程（需要 input/*.pdf + OPENAI_API_KEY）
  python main.py --fake       # 不读 PDF/不调 GPT，直接用 fake_data.py 内的假数据
  python main.py --skip-validate
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import extract
import validate
import generate
from fake_data import build_fake_report

BASE_DIR = Path(__file__).resolve().parent


def _run(stage_name: str, fn, *args, **kwargs) -> int:
    print(f"\n{'='*60}")
    print(f"▶ 阶段：{stage_name}")
    print("=" * 60)
    try:
        return fn(*args, **kwargs)
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="124 项综合测评报告生成器")
    parser.add_argument("--fake", action="store_true",
                        help="不读 PDF/不调 GPT，直接用 fake_data.py 内的假数据")
    parser.add_argument("--skip-extract", action="store_true",
                        help="复用已有的 data/report_data.json")
    parser.add_argument("--skip-validate", action="store_true",
                        help="不做数据校验")
    args = parser.parse_args()

    for d in ("input", "templates", "pages", "output", "data"):
        (BASE_DIR / d).mkdir(parents=True, exist_ok=True)

    # 如果 --fake，直接构造假数据
    if args.fake:
        print("\n[main] 使用 fake_data.py 中的假数据。")
        report_data = build_fake_report()
    else:
        # 步骤①②：提取
        if not args.skip_extract:
            argv_backup = sys.argv
            sys.argv = ["extract.py"]
            rc = _run("提取数据（PDF → GPT Vision）", extract.main)
            sys.argv = argv_backup
            if rc != 0:
                print(f"[main] extract 返回 {rc}，使用假数据继续。")
                report_data = build_fake_report()
            else:
                # 读取 data/report_data.json
                data_file = BASE_DIR / "data" / "report_data.json"
                import json
                try:
                    with open(data_file, "r", encoding="utf-8") as f:
                        report_data = json.load(f)
                except Exception as e:
                    print(f"[main] 读取 {data_file} 失败：{e}，使用假数据继续。")
                    report_data = build_fake_report()
        else:
            data_file = BASE_DIR / "data" / "report_data.json"
            import json
            try:
                with open(data_file, "r", encoding="utf-8") as f:
                    report_data = json.load(f)
            except Exception as e:
                print(f"[main] 读取 {data_file} 失败：{e}，使用假数据继续。")
                report_data = build_fake_report()

    # 步骤③：校验
    if not args.skip_validate:
        rc = _run("数据完整性校验", validate.main)
        if rc != 0:
            print(f"[main] validate 返回 {rc}，继续生成。")

    # 步骤④：生成 PDF
    rc = _run("Jinja2 + WeasyPrint 渲染 PDF", generate.main, report_data)
    if rc != 0:
        print("[main] 生成阶段失败")
        return rc

    pdf = BASE_DIR / "output" / "report.pdf"
    html = BASE_DIR / "output" / "report.html"
    print("\n" + "=" * 60)
    print(f"✅ 完成 → {pdf}")
    print(f"   HTML预览 → {html}")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
