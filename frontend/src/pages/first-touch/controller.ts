import { observable } from './observable';

export interface WorkspaceContext {
  sid: number; code: string; name: string; grade: string; school: string;
  advisorName: string; sessionId: number | null; canStart: boolean;
  canWrite: boolean; readOnly: boolean; role: string;
}
// The shared, unmodified JavaScript owns all domain state and actions.
export type Workspace = import('./workspace-contract').Workspace;
declare global { interface Window { ftWorkspace?: (ctx: WorkspaceContext) => Workspace } }
const stopped = () => new DOMException('已停止', 'AbortError');

export function attachController(raw: Workspace, notify: () => void) {
  let active = true;
  const lifetime = new AbortController();
  const waits = new Set<() => void>();
  const ticks = new Set<ReturnType<typeof setTimeout>>();
  const request = raw.request;
  const pollingSignals = new Map<string, AbortSignal>();
  const pollJob = raw.pollJob;
  raw.pollJob = async function(jobId: string, signal?: AbortSignal) {
    if (!active || signal?.aborted) throw stopped();
    if (signal) pollingSignals.set('/api/v2/copilot/jobs/' + jobId, signal);
    try { return await pollJob.call(this, jobId, signal); }
    finally { pollingSignals.delete('/api/v2/copilot/jobs/' + jobId); }
  };
  raw.request = async function (path: string, options: RequestInit = {}) {
    if (!active) throw stopped();
    const combined = new AbortController();
    const signal = options.signal || pollingSignals.get(path);
    const abort = () => combined.abort();
    lifetime.signal.addEventListener('abort', abort, { once: true });
    signal?.addEventListener('abort', abort, { once: true });
    if (signal?.aborted) combined.abort();
    try {
      if (!active || combined.signal.aborted) throw stopped();
      const headers = new Headers(options.headers);
      if (options.method && options.method !== 'GET') {
        const token = document.querySelector<HTMLMetaElement>('meta[name="csrf-token"]')?.content;
        if (token) headers.set('X-CSRF-Token', token);
      }
      const result = await request.call(this, path, { ...options, headers, signal: combined.signal });
      if (!active || combined.signal.aborted) throw stopped();
      return result;
    } finally {
      lifetime.signal.removeEventListener('abort', abort);
      signal?.removeEventListener('abort', abort);
    }
  };
  raw.delay = (ms: number, signal?: AbortSignal) => new Promise<void>((resolve, reject) => {
    if (!active || signal?.aborted) { reject(stopped()); return; }
    const finish = (error?: Error) => {
      clearTimeout(timer); waits.delete(cancel);
      signal?.removeEventListener('abort', cancel);
      error ? reject(error) : resolve();
    };
    const cancel = () => finish(stopped());
    const timer = setTimeout(() => finish(), ms);
    waits.add(cancel);
    signal?.addEventListener('abort', cancel, { once: true });
  });
  // DOM references are an imperative shim, not observable domain data.
  raw.$refs = Object.create({});
  raw.$nextTick = (callback: () => void) => {
    if (!active) return;
    const timer = setTimeout(() => { ticks.delete(timer); if (active) callback(); }, 0);
    ticks.add(timer);
  };
  // Guard action entry as well as fetch: stale continuations cannot create timers.
  const descriptors = Object.getOwnPropertyDescriptors(raw);
  for (const [key, descriptor] of Object.entries(descriptors)) {
    if (typeof descriptor.value !== 'function' || ['request', 'delay', 'destroy', '$nextTick'].includes(key)) continue;
    const fn = descriptor.value;
    Object.defineProperty(raw, key, { ...descriptor, value: function (this: Workspace, ...args: unknown[]) {
      if (!active) return;
      return fn.apply(this, args);
    } });
  }
  const controller = observable(raw, notify, () => active);
  return {
    controller,
    dispose() {
      if (!active) return;
      raw.destroy.call(controller);
      raw.stopChat.call(controller);
      active = false;
      lifetime.abort();
      waits.forEach(cancel => cancel());
      ticks.forEach(clearTimeout); ticks.clear();
      for (const key of ['timerId', 'saveTimer', 'undoTimer', 'undoInterval', 'previewTimer'] as const) {
        clearTimeout(raw[key]); clearInterval(raw[key]);
      }
      raw.$refs = Object.create({});
    },
  };
}
