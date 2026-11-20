import { guardNavigation } from './navigation';
import { useEffect, useState } from 'react';
import { attachController, type Workspace, type WorkspaceContext } from './controller';
declare global { interface Window { v2Toast?: (message: string, tone?: string) => void } }
let script: Promise<void> | undefined;
export function loadFactory(): Promise<void> {
  if (window.ftWorkspace) return Promise.resolve();
  if (!script) script = new Promise<void>((resolve, reject) => {
    const tag = document.createElement('script');
    tag.src = '/app/assets/first_touch_workspace-85f513a2be34dd0c.js';
    tag.onload = () => window.ftWorkspace ? resolve() : reject(new Error('会谈组件不可用'));
    tag.onerror = () => { tag.remove(); script = undefined; reject(new Error('无法加载会谈组件')); };
    document.head.appendChild(tag);
  });
  return script;
}
export function useWorkspace(ctx: WorkspaceContext) {
  const [controller, setController] = useState<Workspace | null>(null);
  const [error, setError] = useState('');
  const [toast, setToast] = useState('');
  const [, render] = useState(0);
  useEffect(() => {
    let active = true;
    let dispose: (() => void) | undefined;
    let queued = false;
    loadFactory().then(() => {
      if (!active) return;
      const adapter = attachController(window.ftWorkspace!(ctx), () => {
        if (!active || queued) return;
        queued = true;
        queueMicrotask(() => { queued = false; if (active) render(n => n + 1); });
      });
      dispose = adapter.dispose;
      const previousToast = window.v2Toast;
      let toastTimer: ReturnType<typeof setTimeout> | undefined;
      const showToast = (message: string) => {
        if (!active) return;
        setToast(message); clearTimeout(toastTimer);
        toastTimer = setTimeout(() => { if (active) setToast(''); }, 5000);
      };
      window.v2Toast = showToast;
      const c = adapter.controller;
      setController(c);
      c.init();
      const escape = (event: KeyboardEvent) => { if (event.key === 'Escape') { c.selectedId = null; c.drawerOpen = false; } };
      const unguard = guardNavigation(c);
      window.addEventListener('keydown', escape);
      const cleanup = dispose;
      dispose = () => {
        window.removeEventListener('keydown', escape); unguard(); cleanup();
        clearTimeout(toastTimer); if (window.v2Toast === showToast) window.v2Toast = previousToast;
      };
    }).catch(reason => { if (active) setError(reason.message); });
    return () => { active = false; dispose?.(); };
  }, [ctx]);
  return { controller, error, toast };
}
