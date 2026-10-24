"""生产配置加固测试（F10）：SECRET_KEY fail-fast 与会话 Cookie 标记。

每个用例在独立子进程里 ``import app``，避免污染 pytest 进程的全局环境；
子进程使用临时 SQLite（DATABASE_URL），绝不触碰 data/y4_students.db。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent

_PROBE = """
import json
import app as app_module

cfg = app_module.app.config
print(json.dumps({
    "secret_is_dev_default": cfg.get("SECRET_KEY") == "dev-key-change-in-production",
    "secure": cfg["SESSION_COOKIE_SECURE"],
    "httponly": cfg["SESSION_COOKIE_HTTPONLY"],
    "samesite": cfg["SESSION_COOKIE_SAMESITE"],
}))
"""


def _probe(monkeypatch, tmp_path, *, production_var=None, secret_key=None,
           cookie_secure=None):
    """在子进程中导入 app，返回 CompletedProcess。"""
    for name in ("Y4_ENV", "FLASK_ENV", "SECRET_KEY", "Y4_COOKIE_SECURE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'probe.db'}")
    if production_var:
        monkeypatch.setenv(production_var, "production")
    if secret_key is not None:
        monkeypatch.setenv("SECRET_KEY", secret_key)
    if cookie_secure is not None:
        monkeypatch.setenv("Y4_COOKIE_SECURE", cookie_secure)

    return subprocess.run(
        [sys.executable, "-c", _PROBE],
        cwd=str(REPO_ROOT),
        env=os.environ.copy(),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )


def _probe_config(result):
    """子进程成功启动时，取最后一行 JSON 配置。"""
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_production_without_secret_key_refuses_to_start(monkeypatch, tmp_path):
    result = _probe(monkeypatch, tmp_path, production_var="Y4_ENV")

    assert result.returncode != 0
    assert "SECRET_KEY" in result.stderr
    assert "生产环境必须设置强随机 SECRET_KEY" in result.stderr


def test_production_with_dev_default_secret_key_refuses_to_start(monkeypatch, tmp_path):
    result = _probe(monkeypatch, tmp_path, production_var="Y4_ENV",
                    secret_key="dev-key-change-in-production")

    assert result.returncode != 0
    assert "SECRET_KEY" in result.stderr


def test_flask_env_production_is_also_accepted(monkeypatch, tmp_path):
    """旧部署脚本写的是 FLASK_ENV=production，也要触发 fail-fast。"""
    result = _probe(monkeypatch, tmp_path, production_var="FLASK_ENV")

    assert result.returncode != 0
    assert "SECRET_KEY" in result.stderr


def test_production_with_strong_secret_key_hardens_cookies(monkeypatch, tmp_path):
    result = _probe(monkeypatch, tmp_path, production_var="Y4_ENV",
                    secret_key="strong-random-secret-for-test")

    config = _probe_config(result)
    assert config["secret_is_dev_default"] is False
    assert config["secure"] is True
    assert config["httponly"] is True
    assert config["samesite"] == "Lax"


def test_local_dev_keeps_fallback_and_non_secure_cookie(monkeypatch, tmp_path):
    result = _probe(monkeypatch, tmp_path)

    config = _probe_config(result)
    assert config["secret_is_dev_default"] is True
    assert config["secure"] is False
    assert config["httponly"] is True
    assert config["samesite"] == "Lax"
    # 开发回退只警告一次
    assert result.stderr.count("使用开发默认值") == 1


def test_production_cookie_secure_can_be_overridden(monkeypatch, tmp_path):
    result = _probe(monkeypatch, tmp_path, production_var="Y4_ENV",
                    secret_key="strong-random-secret-for-test", cookie_secure="0")

    config = _probe_config(result)
    assert config["secure"] is False
    assert config["samesite"] == "Lax"
