"""History-independent extraction fingerprint and template/action parity."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

def test_factory_is_unchanged():
    # Original inline factory extracted from baseline 3e3b9b3, UTF-8 bytes.
    import hashlib
    assert hashlib.sha256((ROOT / 'static/js/first_touch_workspace.js').read_bytes()).hexdigest() == '85f513a2be34dd0c18201c6f08a647cc42ddbfd5f7ab8812373c06e8e16dc97d'

def test_legacy_loads_shared_asset_once():
    template = (ROOT / 'templates/first_touch/workspace.html').read_text()
    assert template.count("filename='first_touch_workspace-85f513a2be34dd0c.js'") == 1
    assert "url_for('app_shell.app_assets'" in template
    assert (ROOT / 'frontend/public/assets/first_touch_workspace-85f513a2be34dd0c.js').resolve() == ROOT / 'static/js/first_touch_workspace.js'
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
