import type { Workspace } from './controller';
/** Block shell links before React Router, and compensate browser history on rejected Back. */
export function guardNavigation(c: Workspace): () => void {
  const question = () => !c.hasPendingSave() || window.confirm('会谈中有尚未保存的修改，确定离开？');
  const click = (event: MouseEvent) => {
    const anchor = (event.target as Element).closest?.('a[href]');
    if (!anchor || event.defaultPrevented || !c.hasPendingSave()) return;
    if (!question()) { event.preventDefault(); event.stopImmediatePropagation(); }
  };
  const previous = { url: location.href, state: history.state };
  let restoring = false;
  const pop = (event: PopStateEvent) => {
    if (restoring) { restoring = false; event.stopImmediatePropagation(); return; }
    if (question()) return;
    event.stopImmediatePropagation();
    const delta = previous.state?.idx - history.state?.idx;
    if (Number.isFinite(delta) && delta !== 0) { restoring = true; history.go(delta); }
    else history.pushState(previous.state, '', previous.url);
  };
  document.addEventListener('click', click, true);
  window.addEventListener('popstate', pop, true);
  return () => { document.removeEventListener('click', click, true); window.removeEventListener('popstate', pop, true); };
}
