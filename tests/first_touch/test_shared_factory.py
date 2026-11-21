"""History-independent extraction fingerprint and template/action parity."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

def test_factory_matches_published_fingerprint():
    # Both workspace entry points use this fingerprint for the shared source.
    import hashlib
    assert hashlib.sha256((ROOT / 'static/js/first_touch_workspace.js').read_bytes()).hexdigest() == 'eed98b0dcce207b817dfcc6160cddd39bb439379fb44ffa3c79b5e4bc7968f51'

def test_legacy_loads_shared_asset_once():
    template = (ROOT / 'templates/first_touch/workspace.html').read_text()
    assert template.count("filename='first_touch_workspace-eed98b0dcce207b8.js'") == 1
    assert "url_for('app_shell.app_assets'" in template
    assert (ROOT / 'frontend/public/assets/first_touch_workspace-eed98b0dcce207b8.js').resolve() == ROOT / 'static/js/first_touch_workspace.js'
    assert 'window.ftWorkspace =' not in template


def test_visible_actions_have_react_bindings():
    import re
    template = (ROOT / 'templates/first_touch/workspace.html').read_text()
    view = (ROOT / 'frontend/src/pages/first-touch/WorkspaceView.tsx').read_text()
    handlers = re.findall(r'@[\w.]+="([^"]*)"', template)
    actions = {name for handler in handlers for name in re.findall(r'(?<![.\w])([a-zA-Z]\w*)\(', handler)}
    body = view[view.index('  return ('):]
    assert all(re.search(r'\b' + name + r'\(', body) for name in actions), actions
    assert not re.search(r'\\u[0-9a-fA-F]{4}', view)


def test_built_shared_asset_equals_source():
    import hashlib
    source = (ROOT / 'static/js/first_touch_workspace.js').read_bytes()
    filename = 'first_touch_workspace-' + hashlib.sha256(source).hexdigest()[:16] + '.js'
    assert (ROOT / 'static/app/assets' / filename).read_bytes() == source
