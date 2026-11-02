"""仓库里不能有写死的 API key（仓库是公开的）。"""
from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest

import extract

ROOT = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("check_secrets", ROOT / "scripts" / "check_secrets.py")
check_secrets = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_secrets)


def _tracked() -> list:
    try:
        out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True,
                             text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("不是 git 仓库")
    return [p for p in out.splitlines()
            if p and Path(p).suffix.lower() not in check_secrets.BINARY_SUFFIXES]


def test_no_key_in_tracked_files():
    found = []
    for path in _tracked():
        try:
            text = (ROOT / path).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        found += ["%s:%d %s" % (path, n, kind) for n, kind in check_secrets.scan_text(text)]
    assert found == []


def test_no_builtin_dashscope_key():
    assert extract.DEFAULT_DASHSCOPE_KEY == ""


def test_scanner_catches_a_key_and_hides_it():
    fake = "sk-" + "a1b2c3d4" * 4
    result = check_secrets.scan_text('API_KEY = "%s"\n' % fake)
    assert result and all(fake not in str(row) for row in result)


def test_scanner_ignores_placeholders():
    assert check_secrets.scan_text("DASHSCOPE_API_KEY=your_dashscope_api_key_here") == []


def test_pre_commit_hook_runs_the_scanner():
    hook = (ROOT / ".githooks" / "pre-commit").read_text(encoding="utf-8")
    assert "scripts/check_secrets.py --staged" in hook
