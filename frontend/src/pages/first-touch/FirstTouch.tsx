import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { useBoot } from '@/lib/boot';
import { bootstrap } from './bootstrap';
import { useWorkspace } from './useWorkspace';
import type { WorkspaceContext } from './controller';
import WorkspaceView from './WorkspaceView';
import './workspace.css';
function Session({ ctx }: { ctx: WorkspaceContext }) {
  const { controller, error, toast } = useWorkspace(ctx);
  if (error) return <p role="alert">{error}</p>;
  return <><div className="mb-4 flex flex-wrap gap-4 text-sm underline"><Link to={'/students/' + encodeURIComponent(ctx.code) + '?tab=y4'}>Y4 报告 / 学生档案</Link><a href={'/first-touch/students/' + ctx.sid}>原版会谈</a><a href="/first-touch">会谈列表</a><a href="/first-touch/guide">使用指南</a>{ctx.role === "admin" && <a href={"/first-touch/archive/" + ctx.sid}>归档</a>}</div>{toast && <p role="status" className="my-3 border p-3">{toast}</p>}{controller ? <WorkspaceView c={controller} /> : <p>正在加载会谈…</p>}</>;
}
export default function FirstTouch() {
  const { sid = '' } = useParams();
  const boot = useBoot();
  const [state, setState] = useState<{ ctx?: WorkspaceContext; error?: string; restricted?: boolean }>({});
  useEffect(() => {
    const abort = new AbortController(); setState({});
    bootstrap(sid, boot, abort.signal).then(ctx => { if (!abort.signal.aborted) setState(ctx ? { ctx } : { restricted: true }); })
      .catch(error => { if (!abort.signal.aborted) setState({ error: error.message }); });
    return () => abort.abort();
  }, [sid, boot]);
  if (state.restricted) return <p>当前账号不能查看 First Touch 内容。</p>;
  if (state.error) return <p role="alert">{state.error}</p>;
  return state.ctx ? <Session key={sid} ctx={state.ctx} /> : <p>正在加载学生…</p>;
}
