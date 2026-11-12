# -*- coding: utf-8 -*-
"""S4-SA1：档案页 6AM tab 内嵌 6AM 学生视图。

- 垫片 window.SA 的 esc / sev / LEVELS 与 static/js/six_am/common.js 一致
- 构建产物不引用 common.js（它一加载就挂 popstate 路由）
- tab 不再链到 /insights/six-am?view=student，mindmap.js 的 ?v= 与 six_am.html 一致
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

BASE = os.path.dirname(os.path.abspath(__file__))
TAB = os.path.join(BASE, "frontend", "src", "pages", "profile")
COMMON_JS = os.path.join(BASE, "static", "js", "six_am", "common.js")
SHIM = os.path.join(TAB, "sixamShim.ts")


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


_PROBES = ["", None, 0, "a&b", "<b>\"x\"</b>", "稳固", "关注", "风险", "阻塞", "未知", "'", 12, "&amp;"]

_NODE_COMMON = r"""
const vm = require('vm'), fs = require('fs');
const win = { addEventListener() {} };
const doc = { readyState: 'loading', addEventListener() {}, getElementById() { return null; } };
const ctx = { window: win, document: doc, location: {}, history: {}, URLSearchParams };
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[1], 'utf8'), ctx);
const SA = win.SA, probes = JSON.parse(process.argv[2]);
console.log(JSON.stringify({ LEVELS: SA.LEVELS, esc: probes.map(p => SA.esc(p)), sev: probes.map(p => SA.sev(p)) }));
"""

_NODE_SHIM = r"""
const probes = JSON.parse(process.argv[3]);
globalThis.window = {};
const m = await import(process.argv[2]);
const SA = m.ensureSA();
const keep = {}; globalThis.window.SA = keep; m.ensureSA();
console.log(JSON.stringify({ LEVELS: SA.LEVELS, esc: probes.map(p => SA.esc(p)), sev: probes.map(p => SA.sev(p)),
  keptExisting: keep.esc === m.saEsc && globalThis.window.SA === keep }));
"""


@unittest.skipUnless(shutil.which("node"), "需要 node")
class ShimMatchesCommonJs(unittest.TestCase):
    def _run(self, args):
        out = subprocess.run(args, capture_output=True, text=True, timeout=60, cwd=tempfile.gettempdir())
        self.assertEqual(out.returncode, 0, out.stderr)
        return json.loads(out.stdout)

    def test_esc_sev_levels_match(self):
        probes = json.dumps(_PROBES)
        a = self._run(["node", "-e", _NODE_COMMON, COMMON_JS, probes])
        b = self._run_shim(probes)
        self.assertEqual(a["LEVELS"], ["稳固", "关注", "风险", "阻塞"])
        self.assertEqual(a["LEVELS"], b["LEVELS"])
        self.assertEqual(a["esc"], b["esc"])
        self.assertEqual(a["sev"], b["sev"])
        self.assertTrue(b["keptExisting"], "已有 window.SA 不得被覆盖")

    def _run_shim(self, probes):
        d = tempfile.mkdtemp(prefix="sixam_shim_")
        try:
            script = os.path.join(d, "run.mjs")
            with open(script, "w", encoding="utf-8") as fh:
                fh.write(_NODE_SHIM)
            return self._run(["node", script, "file://" + SHIM, probes])
        finally:
            shutil.rmtree(d, ignore_errors=True)


class TabSource(unittest.TestCase):
    def test_no_link_to_student_view_or_old_buttons(self):
        src = _read(os.path.join(TAB, "SixAmTab.tsx"))
        self.assertNotIn("view=student", src)
        self.assertNotIn("打开 6AM 思维导图", src)
        self.assertNotIn("打开 6AM 档案", src)

    def test_mindmap_version_matches_template(self):
        tpl = _read(os.path.join(BASE, "templates", "six_am.html"))
        want = re.search(r"/js/six_am/mindmap\.js\?v=(\w+)", tpl).group(1)
        got = re.search(r'MINDMAP_VERSION = "(\w+)"', _read(SHIM)).group(1)
        self.assertEqual(got, want)

    def test_common_js_not_loaded(self):
        self.assertNotIn("/js/six_am/common.js", _read(SHIM))
        self.assertNotIn("/js/six_am/common.js", _read(os.path.join(TAB, "SixAmTab.tsx")))


class BuiltBundle(unittest.TestCase):
    def test_bundle_loads_mindmap_not_common(self):
        assets = os.path.join(BASE, "static", "app", "assets")
        js = "".join(_read(os.path.join(assets, n)) for n in os.listdir(assets) if n.endswith(".js"))
        self.assertIn("/js/six_am/mindmap.js", js)
        self.assertNotIn("/js/six_am/common.js", js)
        self.assertNotIn("common.js", js)
        self.assertNotIn("view=student", js)


if __name__ == "__main__":
    unittest.main()
