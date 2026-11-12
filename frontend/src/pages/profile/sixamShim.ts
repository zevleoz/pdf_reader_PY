// 6AM 思维导图脚本（static/js/six_am/mindmap.js）只依赖 window.SA 的 esc / sev / LEVELS。
// 这里照 six_am 目录里的 common.js 原样复制这三样；不加载它
// （它一加载就挂 popstate 路由、抢走地址栏）。

export const SA_LEVELS: string[] = ["稳固", "关注", "风险", "阻塞"];
const SEV: Record<string, number> = { 稳固: 0, 关注: 1, 风险: 2, 阻塞: 3 };
const ESC_MAP: Record<string, string> = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" };

export function saEsc(s: unknown): string {
  return String(s == null ? "" : s).replace(/[&<>"]/g, (c) => ESC_MAP[c]);
}

export function saSev(level: unknown): number {
  return SEV[String(level)] == null ? -1 : SEV[String(level)];
}

// mindmap.js 的 ?v= 与 templates/six_am.html 保持一致
export const MINDMAP_VERSION = "20261104";
const MINDMAP_SRC = "/js/six_am/mindmap.js?v=" + MINDMAP_VERSION;

type SAGlobal = {
  esc?: (s: unknown) => string;
  sev?: (level: unknown) => number;
  LEVELS?: string[];
  mindmap?: { dim: (model: unknown, dim: string, state: { profile: unknown; writable: boolean }) => string };
};

function saWindow(): Window & { SA?: SAGlobal } {
  return window as Window & { SA?: SAGlobal };
}

/** 已有 window.SA 就不覆盖，只补缺的三样。 */
export function ensureSA(): SAGlobal {
  const w = saWindow();
  if (!w.SA) w.SA = {};
  const sa = w.SA;
  if (!sa.esc) sa.esc = saEsc;
  if (!sa.sev) sa.sev = saSev;
  if (!sa.LEVELS) sa.LEVELS = SA_LEVELS;
  return sa;
}

let loading: Promise<void> | null = null;

/** 只加载一次 mindmap.js；失败后允许重试。 */
export function loadMindmap(): Promise<void> {
  ensureSA();
  if (saWindow().SA?.mindmap) return Promise.resolve();
  if (!loading) {
    loading = new Promise<void>((resolve, reject) => {
      const tag = document.createElement("script");
      tag.src = MINDMAP_SRC;
      tag.async = true;
      tag.onload = () => (saWindow().SA?.mindmap ? resolve() : reject(new Error("思维导图脚本未就绪")));
      tag.onerror = () => {
        tag.remove();
        reject(new Error("思维导图脚本加载失败"));
      };
      document.head.appendChild(tag);
    });
    loading.catch(() => {
      loading = null;
    });
  }
  return loading;
}

export function mindmapHTML(model: unknown, dim: string, profile: unknown, writable: boolean): string {
  const mm = saWindow().SA?.mindmap;
  return mm ? mm.dim(model, dim, { profile, writable }) : "";
}
