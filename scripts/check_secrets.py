"""拦截写进代码的 API key。仓库是公开的：key 只能放在环境变量或仓库外的文件里。

用法：
    python3 scripts/check_secrets.py            # 检查所有已跟踪文件
    python3 scripts/check_secrets.py --staged   # 只检查本次要提交的内容（pre-commit 钩子用）

只输出“文件:行号”和匹配类型，从不输出 key 本身。发现问题时退出码为 1。
钩子安装（每个 clone 一次）：git config core.hooksPath .githooks
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path
from typing import Iterable, List, Tuple

PATTERNS = (
    ("api-key", re.compile(r"\bsk-[A-Za-z0-9._-]{20,}")),
    ("assigned-secret", re.compile(
        r"(?i)\b[A-Z0-9_]*(?:api_?key|secret|token|passwd|password)[A-Z0-9_]*"
        r"\s*[:=]\s*[\"']([A-Za-z0-9._\-]{24,})[\"']")),
)
# 明显的示例值不算泄漏
PLACEHOLDER = re.compile(r"(?i)your_|_here|example|placeholder|dummy|xxxx|test")
# 有意公开、不是密钥的值（如开发默认值），在同一行注释里写明这个标记
ALLOW_MARK = "not-a-secret"
BINARY_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".docx", ".xlsx",
                   ".db", ".sqlite", ".woff", ".woff2", ".ttf", ".otf", ".zip"}


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True,
                          check=True).stdout


def _paths(staged: bool) -> List[str]:
    if staged:
        out = _git("diff", "--cached", "--name-only", "--diff-filter=ACMR")
    else:
        out = _git("ls-files")
    return [p for p in out.splitlines()
            if p and Path(p).suffix.lower() not in BINARY_SUFFIXES]


def _read(path: str, staged: bool) -> str:
    try:
        if staged:
            return _git("show", ":" + path)
        return Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError, subprocess.CalledProcessError):
        return ""


def scan_text(text: str) -> List[Tuple[int, str]]:
    """→ [(行号, 匹配类型)]，不含匹配到的值。"""
    found = []
    for number, line in enumerate(text.splitlines(), start=1):
        if ALLOW_MARK in line:
            continue
        for kind, pattern in PATTERNS:
            for match in pattern.finditer(line):
                value = match.group(match.lastindex or 0)
                if PLACEHOLDER.search(value):
                    continue
                found.append((number, kind))
    return found


def scan(paths: Iterable[str], staged: bool) -> List[Tuple[str, int, str]]:
    results = []
    for path in paths:
        for number, kind in scan_text(_read(path, staged)):
            results.append((path, number, kind))
    return results


def main(argv: List[str]) -> int:
    staged = "--staged" in argv
    results = scan(_paths(staged), staged)
    if not results:
        return 0
    print("发现疑似 API key（值已隐藏）：", file=sys.stderr)
    for path, number, kind in results:
        print("  %s:%d  %s" % (path, number, kind), file=sys.stderr)
    print("请删掉这些值，改为从环境变量读取（如 DASHSCOPE_API_KEY）。"
          "如果 key 已经推送过，请到控制台作废并重新生成。", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
