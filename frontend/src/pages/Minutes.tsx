import * as React from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { useBoot, csrfToken } from '@/lib/boot';
import { getJSON, postJSON, putJSON, deleteJSON, errorText } from '@/lib/api';
import { Button } from '@/components/ui/button';
import PageHeader from '@/shell/PageHeader';
import { saveResponse } from './profile/common';
import Markdown from './minutes/Markdown';
import { changed, fillMetadata, draftKey, displayedText, emptyDraft, readDraft, type Draft, type Student, type Minute } from './minutes/model';
type Report = {
  id: number;
  report_date?: string;
};
type Result = {
  ok: boolean;
  error?: string;
  summary: string;
  minutes_id: number | null;
  student_name?: string;
  student_grade?: string;
  student_gender?: string;
};
function check<T extends {
  ok?: boolean;
  error?: string;
}>(r: T): T {
  if (r.ok === false)
    throw Error(r.error || '操作失败'); return r;
}
export default function Minutes() {
  const boot = useBoot();
  if (!['admin', 'advisor'].includes(boot.user.role) || boot.policy.detail_level === 'summary')
    return <>
      <PageHeader title="解读会纪要" />
      <p>当前账号不显示纪要内容。</p>
    </>;
  return <Editor />;
}
function Editor() {
  const location = useLocation(), navigate = useNavigate();
  const query = new URLSearchParams(location.search);
  const sid = query.get('student_id') || '', rid = query.get('report_id') || '';
  const [userId, setUserId] = React.useState<number | null>(null);
  const [identityReady, setIdentityReady] = React.useState(false);
  const key = userId === null ? '' : draftKey(userId, sid, rid);
  const [students, setStudents] = React.useState<Student[]>([]);
  const [reports, setReports] = React.useState<Report[]>([]);
  const [history, setHistory] = React.useState<Minute[]>([]);
  const [draft, setDraft] = React.useState<Draft>(emptyDraft);
  const [activeKey, setActiveKey] = React.useState('');
  const [search, setSearch] = React.useState('');
  const [error, setError] = React.useState('');
  const [busy, setBusy] = React.useState('');
  const [ready, setReady] = React.useState(false);
  const [restricted, setRestricted] = React.useState(false);
  const [revision, setRevision] = React.useState(0);
  const epoch = React.useRef(0), current = React.useRef(draft), accepted = React.useRef(location), bypass = React.useRef(false);
  current.current = draft;
  const student = students.find(s => String(s.id) === sid);
  const selectedStudent = React.useRef(student);
  selectedStudent.current = student;
  const confirmDiscard = () => !changed(current.current) || window.confirm('当前内容尚未保存，确认切换或放弃编辑？');
  const move = (url: string) => {
    if (confirmDiscard()) {
      epoch.current++;
      bypass.current = true;
      navigate(url);
    }
  };
  React.useEffect(() => {
    let live = true;
    getJSON<{
      authenticated: boolean;
      user_id: number;
    }>('/api/admin/check')
      .then(r => {
        if (live && r.authenticated && Number.isInteger(r.user_id) && r.user_id > 0)
          setUserId(r.user_id);
      })
      .catch(() => { })
      .finally(() => {
        if (live)
          setIdentityReady(true);
      });
    return () => { live = false; };
  }, []);
  React.useEffect(() => {
    let live = true; getJSON<{
      students: Student[];
    }>('/api/students').then(r => {
      if (live)
        setStudents(r.students);
    }).catch(e => {
      if (live)
        setError(errorText(e));
    }); return () => { live = false; };
  }, []);
  // Guard browser back/forward and hash changes as well as picker-driven navigation.
  React.useEffect(() => {
    if (!identityReady)
      return;
    const previous = accepted.current;
    if (previous.key !== location.key && !bypass.current && !confirmDiscard()) {
      bypass.current = true;
      navigate(previous.pathname + previous.search + previous.hash, { replace: true });
      return;
    }
    bypass.current = false;
    accepted.current = location;
    const token = ++epoch.current;
    setError('');
    setBusy('');
    setReady(false);
    setRestricted(false);
    setReports([]);
    setHistory([]);
    const restored = key ? readDraft(key) : null;
    setActiveKey(key);
    setDraft(restored || { ...emptyDraft(), name: student?.name || '', grade: student?.grade || '', gender: student?.gender || '' });
    async function loadContext() {
      try {
        let rows: Minute[] = [];
        if (sid) {
          const [r, m] = await Promise.all([getJSON<{
            ok: boolean;
            reports: Report[];
          }>('/api/students/' + encodeURIComponent(sid) + '/reports'), getJSON<{
            ok: boolean;
            minutes: Minute[];
            restricted?: boolean;
          }>('/api/students/' + encodeURIComponent(sid) + '/minutes')]);
          if (token !== epoch.current)
            return;
          check(r);
          check(m);
          setReports(r.reports);
          rows = m.minutes;
          setHistory(rows);
          if (m.restricted) {
            setRestricted(true);
            return;
          }
          if (rid && !r.reports.some(r => String(r.id) === rid))
            throw Error('所选报告不属于当前学生，请重新选择报告');
        }
        else if (rid)
          throw Error('请先选择学生，再关联报告');
        const match = location.hash.match(/^#m(\d+)$/);
        if (match) {
          const id = Number(match[1]);
          if (!sid || !rows.some(m => m.id === id))
            throw Error('当前学生下找不到这份纪要');
          const r = check(await getJSON<Minute & {
            ok: boolean;
          }>('/api/minutes/' + id));
          if (token !== epoch.current)
            return;
          if (String(r.student_id) !== sid)
            throw Error('纪要不属于当前学生');
          if (restored?.id !== id)
            setDraft({ ...emptyDraft(), id: r.id, transcript: r.transcript_text || '', text: r.minutes_text || '', savedText: r.minutes_text || '', savedTranscript: r.transcript_text || '', name: r.student_name || selectedStudent.current?.name || '', grade: r.student_grade || selectedStudent.current?.grade || '', gender: r.student_gender || selectedStudent.current?.gender || '' });
        }
        if (token === epoch.current)
          setReady(true);
      }
      catch (e) {
        if (token === epoch.current)
          setError(errorText(e));
      }
    }
    void loadContext();
    return () => { epoch.current++; };
    // Student metadata arrives independently; context changes alone control draft restoration.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [location.key, revision, identityReady, userId]);
  React.useEffect(() => {
    if (identityReady && key && activeKey === key)
      try {
        sessionStorage.setItem(key, JSON.stringify(draft));
      }
      catch { /* Storage is optional. */ }
  }, [draft, activeKey, key, identityReady]);
  React.useEffect(() => {
    if (student && String(student.id) === sid && activeKey === key) {
      setDraft(d => fillMetadata(d, student));
    }
  }, [student, sid, activeKey, key]);
  React.useEffect(() => {
    const f = (e: BeforeUnloadEvent) => {
      if (changed(current.current)) {
        e.preventDefault();
        e.returnValue = '';
      }
    }; window.addEventListener('beforeunload', f); return () => window.removeEventListener('beforeunload', f);
  }, []);
  const update = (field: keyof Draft, value: string) => setDraft(d => ({ ...d, [field]: value }));
  async function action(label: string, fn: (token: number) => Promise<void>) {
    const token = ++epoch.current; setBusy(label); setError(''); try {
      await fn(token);
    }
      catch (e) {
        if (token === epoch.current)
          setError(errorText(e));
      }
      finally {
        if (token === epoch.current)
          setBusy('');
      }
  }
  async function save(token: number) {
    if (!draft.id)
      throw Error('未保存：请复制或导出当前结果');
    check(await putJSON<{
      ok: boolean;
    }>('/api/minutes/' + draft.id, { minutes_text: draft.text, transcript_text: draft.transcript }));
    if (token === epoch.current)
      setDraft(d => ({ ...d, savedText: draft.text, savedTranscript: draft.transcript }));
  }
  const text = displayedText(draft), field = 'mt-2 w-full rounded-none border border-line bg-white px-3 py-2 text-sm focus-visible:outline focus-visible:outline-2 focus-visible:outline-ink';
  return <div>
    <PageHeader title="解读会纪要" sub="会议原文、生成纪要与历史记录" actions={student?.student_code ? <a className="underline" href={'/app/students/' + encodeURIComponent(student.student_code)} onClick={e => {
      if (!confirmDiscard())
        e.preventDefault();
    }}>{student.name} · 返回学生档案</a> : undefined} />
    <div className="mb-6 grid gap-4 md:grid-cols-3">
      <label>搜索学生<input className={field} value={search} onChange={e => setSearch(e.target.value)} placeholder="输入姓名或编号" />
      </label>
      <label>关联学生<select className={field} value={sid} onChange={e => move(e.target.value ? '?student_id=' + e.target.value : '?')}>
        <option value="">未关联学生</option>{students.filter(s => String(s.id) === sid || (s.name + ' ' + s.student_code).includes(search)).map(s => <option key={s.id} value={s.id}>{s.name} · {s.student_code}</option>)}</select>
      </label>
      <label>关联报告<select className={field} value={rid} disabled={!sid || !!busy} onChange={e => move('?student_id=' + sid + (e.target.value ? '&report_id=' + e.target.value : ''))}>
        <option value="">不绑定报告</option>{reports.map(r => <option key={r.id} value={r.id}>{r.report_date || '报告'} · #{r.id}</option>)}</select>
      </label>
    </div>
    {!sid ? <p className="mb-5 border-y border-line py-3">未关联学生：生成内容不会保存到学生档案。选择学生后才会关联保存。</p> : <p className="mb-5 text-sm">当前学生：{student?.name || '#' + sid} · {rid ? '关联报告 #' + rid : '未绑定报告'}</p>}
    {error ? <div role="alert" className="mb-4 border border-ink p-3">{error} <button className="underline" onClick={() => {
      if (confirmDiscard())
        setRevision(v => v + 1);
    }}>重新载入</button>
    </div> : null}
    {restricted ? <p>当前账号不显示纪要内容。</p> : <>
      {!ready && !error ? <p role="status">正在载入关联资料…</p> : null}{busy ? <p role="status" className="mb-4">{busy}…</p> : null}
      <fieldset disabled={!!busy || !ready} className="min-w-0">
        <legend className="sr-only">纪要工作区</legend>
        <div className="mb-6 grid gap-4 md:grid-cols-3">{(['name', 'grade', 'gender'] as const).map((k, i) => <label key={k}>{['学生姓名', '年级', '性别'][i]}<input className={field} value={draft[k]} onChange={e => update(k, e.target.value)} />
        </label>)}</div>
        <div className="grid gap-8 md:grid-cols-2">
          <section className="min-w-0 space-y-4">
            <h2 className="border-b border-ink pb-3 text-xl font-bold">01 / 会议原文</h2>
            <label className="block" htmlFor="minutes-source">逐字稿 <span className="text-mute">{draft.transcript.length} 字</span>
            </label>
            <textarea id="minutes-source" className={field + ' min-h-80'} value={draft.transcript} onChange={e => update('transcript', e.target.value)} />
            <details>
              <summary className="cursor-pointer">自定义提示词（可选）</summary>
              <textarea aria-label="自定义提示词" className={field + ' min-h-32'} value={draft.prompt} onChange={e => update('prompt', e.target.value)} />
            </details>
            <Button disabled={draft.transcript.trim().length < 50} onClick={() => {
              if (draft.text && !confirmDiscard())
                return;
              void action('正在生成纪要', async (token) => {
                const r = check(await postJSON<Result>('/api/transcript', { transcript: draft.transcript, student_name: draft.name || student?.name || '', student_grade: draft.grade, student_gender: draft.gender, ...(sid ? { student_id: Number(sid) } : {}), ...(rid ? { report_id: Number(rid) } : {}), ...(draft.prompt ? { custom_prompt: draft.prompt } : {}) }));
                if (token !== epoch.current)
                  return;
                if (!r.summary)
                  throw Error('未返回生成内容');
                setDraft(d => ({ ...d, text: r.summary, savedText: r.minutes_id ? r.summary : '', savedTranscript: r.minutes_id ? d.transcript : '', id: r.minutes_id || null, name: r.student_name || d.name, grade: r.student_grade || d.grade, gender: r.student_gender || d.gender }));
                if (!r.minutes_id)
                  setError('未保存：生成内容已保留，可以复制、TXT 或 DOCX 导出。');
                else {
                  const m = check(await getJSON<{
                    ok: boolean;
                    minutes: Minute[];
                  }>('/api/students/' + sid + '/minutes'));
                  if (token === epoch.current)
                    setHistory(m.minutes);
                }
              });
            }}>生成纪要</Button>
            <p className="text-sm text-mute">至少输入 50 字。恢复的草稿不会自动生成。</p>
          </section>
          <section className="min-w-0 space-y-4">
            <h2 className="border-b border-ink pb-3 text-xl font-bold">02 / 纪要 <span className="text-sm font-normal">{draft.id ? (changed(draft) ? '有未保存编辑' : '已保存') : '未保存'}</span>
            </h2>{text ? <Markdown text={text} /> : <p className="py-8 text-mute">生成纪要，或从下方选择历史记录。</p>}<details>
              <summary className="cursor-pointer">编辑纪要文字</summary>
              <label htmlFor="minutes-edit" className="sr-only">纪要文字</label>
              <textarea id="minutes-edit" className={field + ' min-h-80'} value={draft.text} onChange={e => update('text', e.target.value)} />
            </details>
            <div className="flex flex-wrap gap-3">
              <Button variant="outline" disabled={!draft.id || !changed(draft)} onClick={() => void action('正在保存', save)}>保存编辑</Button>
              <Button variant="outline" disabled={!text} onClick={() => void action('正在复制', async () => navigator.clipboard.writeText(text))}>复制</Button>
              <Button variant="outline" disabled={!text} onClick={() => void action('正在导出', async () => saveResponse(new Response(text), '解读会纪要.txt'))}>TXT</Button>
              <Button variant="outline" disabled={!text} onClick={() => void action('正在导出 DOCX', async (token) => {
                if (draft.id && changed(draft))
                  await save(token);
                if (token !== epoch.current)
                  return;
                const response = await fetch('/api/transcript/docx', { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrfToken() }, body: JSON.stringify(draft.id ? { minutes_id: draft.id } : { summary: text, student_name: draft.name, student_grade: draft.grade, student_gender: draft.gender }) });
                if (response.status === 401) {
                  window.location.href = '/login';
                  throw Error('请重新登录');
                }
                if (!response.ok)
                  throw Error('DOCX 导出失败');
                if (token === epoch.current)
                  await saveResponse(response, '解读会纪要.docx');
              })}>DOCX</Button>
              <Button variant="outline" onClick={() => {
                if (confirmDiscard()) {
                  setDraft(emptyDraft());
                  try {
                    sessionStorage.removeItem(key);
                  }
                  catch { }
                  ;
                  if (location.hash) {
                    bypass.current = true;
                    navigate(location.search, { replace: true });
                  }
                }
              }}>清空草稿</Button>
            </div>
          </section>
        </div>
      </fieldset>
      <section className="mt-10 border-t border-ink pt-4">
        <h2 className="mb-4 text-xl font-bold">历史纪要</h2>{!history.length ? <p className="text-mute">{sid ? '暂无历史纪要' : '选择学生后查看历史纪要'}</p> : history.map(m => <div key={m.id} className="flex flex-wrap items-center justify-between gap-3 border-b border-line py-4">
          <button className="text-left underline" disabled={!!busy} onClick={() => move('?student_id=' + sid + (m.report_id ? '&report_id=' + m.report_id : '') + '#m' + m.id)}>#{m.id} · {m.created_at || '纪要'} · {m.report_id ? '报告 #' + m.report_id : '未绑定报告'}</button>
          <Button variant="outline" size="sm" disabled={!!busy} onClick={() => {
            if (!window.confirm('确认删除这份纪要？此操作无法撤销。') || (draft.id === m.id && !confirmDiscard()))
              return; void action('正在删除', async (token) => {
                check(await deleteJSON<{
                  ok: boolean;
                }>('/api/minutes/' + m.id)); if (token !== epoch.current)
                  return; setHistory(h => h.filter(v => v.id !== m.id)); if (draft.id === m.id) {
                    setDraft(emptyDraft());
                    bypass.current = true;
                    navigate(location.search, { replace: true });
                  }
              });
          }}>删除</Button>
        </div>)}</section>
    </>}
  </div>;
}
