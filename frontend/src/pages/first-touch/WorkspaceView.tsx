import { Sheet, SheetContent, SheetTitle } from '@/components/ui/sheet';
import { Button } from '@/components/ui/button';
import { Fragment, type CSSProperties } from 'react';
import type { Workspace } from './controller';
function classes(base: string, value: unknown): string {
 if (Array.isArray(value)) return [base, ...value].filter(Boolean).join(' ');
 if (value && typeof value === 'object') return [base, ...Object.entries(value).filter(([,on]) => on).map(([name]) => name)].join(' ');
 return [base, value].filter(Boolean).join(' ');
}
function styleObject(value: string): CSSProperties { return Object.fromEntries(value.split(';').filter(Boolean).map(pair => { const [key, val] = pair.split(':'); return [key.replace(/-([a-z])/g, (_, x: string) => x.toUpperCase()), val]; })); }
export default function WorkspaceView({c}: {c: Workspace}) {
  const sessionId = c.sessionId;
  const code = c.code;
  const name = c.name;
  const grade = c.grade;
  const school = c.school;
  const advisorName = c.advisorName;
  const canWrite = c.canWrite;
  const canStart = c.canStart;
  const readOnly = c.readOnly;
  const role = c.role;
  const stepLabels = c.stepLabels;
  const likeLabels = c.likeLabels;
  const goodLabels = c.goodLabels;
  const step = c.step;
  const status = c.status;
  const lastEditor = c.lastEditor;
  const lastSavedAt = c.lastSavedAt;
  const loading = c.loading;
  const loadError = c.loadError;
  const createError = c.createError;
  const y4 = c.y4;
  const interests = c.interests;
  const script = c.script;
  const meetingSourceId = c.meetingSourceId;
  const meetingFileName = c.meetingFileName;
  const meetingInput = c.meetingInput;
  const confirmedReport = c.confirmedReport;
  const saving = c.saving;
  const saveFail = c.saveFail;
  const conflict = c.conflict;
  const conflictNotice = c.conflictNotice;
  const newInterest = c.newInterest;
  const editingId = c.editingId;
  const nameDraft = c.nameDraft;
  const selectedId = c.selectedId;
  const undo = c.undo;
  const undoSeconds = c.undoSeconds;
  const elapsed = c.elapsed;
  const talkBusy = c.talkBusy;
  const talkError = c.talkError;
  const uploadBusy = c.uploadBusy;
  const uploadError = c.uploadError;
  const analyzing = c.analyzing;
  const analyzeError = c.analyzeError;
  const suggestionsError = c.suggestionsError;
  const reviewBusy = c.reviewBusy;
  const summaryBusy = c.summaryBusy;
  const summaryError = c.summaryError;
  const projectsBusy = c.projectsBusy;
  const projectsError = c.projectsError;
  const previewBusy = c.previewBusy;
  const previewLoaded = c.previewLoaded;
  const previewError = c.previewError;
  const missing = c.missing;
  const confirmBusy = c.confirmBusy;
  const confirmedError = c.confirmedError;
  const drawerOpen = c.drawerOpen;
  const suggestedQuestions = c.suggestedQuestions;
  const chat = c.chat;
  const fmtEditor = c.fmtEditor.bind(c);
  const fmtDate = c.fmtDate.bind(c);
  const createSession = c.createSession.bind(c);
  const loadSession = c.loadSession.bind(c);
  const loadLatest = c.loadLatest.bind(c);
  const goStep = c.goStep.bind(c);
  const flushSave = c.flushSave.bind(c);
  const meetingChanged = c.meetingChanged.bind(c);
  const setTalkingPoint = c.setTalkingPoint.bind(c);
  const addTalkingPoint = c.addTalkingPoint.bind(c);
  const removeTalkingPoint = c.removeTalkingPoint.bind(c);
  const generateTalkingPoints = c.generateTalkingPoints.bind(c);
  const catLabel = c.catLabel.bind(c);
  const addInterest = c.addInterest.bind(c);
  const addSuggestion = c.addSuggestion.bind(c);
  const remainingSuggestions = c.remainingSuggestions;
  const beginRename = c.beginRename.bind(c);
  const commitRename = c.commitRename.bind(c);
  const cancelRename = c.cancelRename.bind(c);
  const cycleCategory = c.cycleCategory.bind(c);
  const toggleStar = c.toggleStar.bind(c);
  const deleteInterest = c.deleteInterest.bind(c);
  const undoDelete = c.undoDelete.bind(c);
  const setScore = c.setScore.bind(c);
  const setNote = c.setNote.bind(c);
  const rowClick = c.rowClick.bind(c);
  const snapshot = c.snapshot;
  const riasecRows = c.riasecRows;
  const scoredCount = c.scoredCount;
  const pendingScoreCount = c.pendingScoreCount;
  const selectedLabel = c.selectedLabel;
  const zoneClass = c.zoneClass.bind(c);
  const cellItems = c.cellItems.bind(c);
  const cellClick = c.cellClick.bind(c);
  const suggestions = c.suggestions;
  const pendingSuggestionCount = c.pendingSuggestionCount;
  const conflictRows = c.conflictRows.bind(c);
  const decisionLabel = c.decisionLabel.bind(c);
  const decideSuggestion = c.decideSuggestion.bind(c);
  const applyConflict = c.applyConflict.bind(c);
  const keepConflict = c.keepConflict.bind(c);
  const uploadTranscript = c.uploadTranscript.bind(c);
  const analyzeTranscript = c.analyzeTranscript.bind(c);
  const setSummary = c.setSummary.bind(c);
  const generateSummary = c.generateSummary.bind(c);
  const projectItems = c.projectItems;
  const projectsStale = c.projectsStale;
  const fitLabel = c.fitLabel.bind(c);
  const generateProjects = c.generateProjects.bind(c);
  const toggleProject = c.toggleProject.bind(c);
  const refreshPreview = c.refreshPreview.bind(c);
  const confirmReady = c.confirmReady;
  const needsNewVersion = c.needsNewVersion;
  const confirmReport = c.confirmReport.bind(c);
  const downloadHref = c.downloadHref.bind(c);
  const student360Href = c.student360Href;
  const toggleDrawer = c.toggleDrawer.bind(c);
  const askSuggestion = c.askSuggestion.bind(c);
  const sendChat = c.sendChat.bind(c);
  const stopChat = c.stopChat.bind(c);
  const $refs = c.$refs;
  return (<div data-ft-workspace="" className={classes("ft-page", { 'is-readonly': readOnly })}>
{loadError && <div role="alert" className="ft-error">{loadError}<button onClick={() => loadSession()}>重试</button></div>}<div className="ft-head">
<div >
<div className="ft-title">{name} · First Touch<span hidden={!readOnly} className="badge badge-neutral ft-ro-badge">只读查看</span></div>
<div className="ft-meta">{code || "—"} · {grade || "年级未填写"} · {school || "学校未填写"} · 顾问 {advisorName || "—"}</div>
</div>
<div className="ft-head-right">
{Boolean(lastEditor) && (<span className="ft-editor">
        最近编辑：<span >{lastEditor ? lastEditor.name : ''}</span>
{Boolean(lastEditor && lastEditor.at) && (<><span > · <span >{fmtEditor(lastEditor.at)}</span></span></>)}
</span>)}
<span className={classes("ft-save", { 'err': saveFail, 'warn': conflict && conflict.active })}>
<i className="ft-save-dot"></i>
{Boolean(conflict && conflict.active) && (<><span >未保存 · 有冲突</span></>)}
{Boolean(!(conflict && conflict.active) && saving) && (<><span >正在保存…</span></>)}
{Boolean(!saving && !(conflict && conflict.active) && saveFail) && (<><button type="button" onClick={($event) => { flushSave(); }}>保存失败，点此重试</button></>)}
{Boolean(!saving && !(conflict && conflict.active) && !saveFail) && (<><span >{'已自动保存 ' + lastSavedAt}</span></>)}
</span>
</div>
</div>
{Boolean(sessionId) && (<div className="ft-bar">
<div className="ft-steps" role="navigation" aria-label="会谈步骤">
{stepLabels.map((label: any, index: any) => <Fragment key={index}>
<button type="button" aria-current={step === index ? 'step' : undefined} className={classes("ft-step", { 'done': step > index })} onClick={($event) => { goStep(index); }}>
<b >{step > index ? '✓' : (index + 1)}</b>
<span >{label}</span>
</button>
</Fragment>)}
</div>
<label className="ft-meeting">会谈时间
      <input type="datetime-local" step="900" disabled={readOnly} value={meetingInput} onChange={($event) => { c.meetingInput = $event.currentTarget.value; meetingChanged(); }} />
</label>
</div>)}
{Boolean(conflict && conflict.active) && (<div className="ft-banner">
<span >其他人刚更新了这次会谈</span>
<Button variant="outline" type="button" className="btn btn-sm" onClick={($event) => { loadLatest(); }}>载入最新</Button>
</div>)}
{Boolean(conflictNotice) && (<div className="ft-notice">{conflictNotice}</div>)}
{Boolean(loading) && (<>
<div className="ft-panel"><div className="ft-body"><span className="ft-hint">正在加载会谈…</span></div></div>
</>)}
{Boolean(!loading && !sessionId) && (<>
<div className="ft-panel">
<div className="ft-body">
<p className="ft-hint" style={{"margin": "0"}}>该学生尚未开始 First Touch 会谈。</p>
{Boolean(canWrite && !canStart) && (<p className="ft-hint" style={{"margin": "6px 0 0"}}>该学生还没有完整的 Y4 报告，请先生成 Y4 报告后再开始会谈。</p>)}
{Boolean(canWrite && canStart && createError) && (<div className="ft-error">
<span >{createError}</span>
<Button variant="outline" type="button" className="btn btn-sec btn-sm" onClick={($event) => { createSession(); }}>重试</Button>
</div>)}
</div>
</div>
</>)}
{Boolean(!loading && sessionId) && (<>
<div style={{"display": "flex", "flexDirection": "column", "gap": "12px"}}>

{Boolean(step === 0) && (<div style={{"display": "flex", "flexDirection": "column", "gap": "12px"}}>
<section className="ft-panel">
<div className="ft-panel-head">
<h2 >Y4 速览</h2>
<span className="ft-sub">{snapshot ? ('来自 ' + fmtDate(snapshot.reportDate) + ' 的 Y4 报告，打开即有，无需等待 AI') : 'Y4 数据不可用'}</span>
</div>
<div className="ft-body">
{Boolean(snapshot) && (<>
<div className="ft-y4">
<div className="ft-blk">
<div className="ft-k">职业兴趣代码</div>
<div className="ft-code">{snapshot.hollandCode || '—'}</div>
{riasecRows.map((row: any) => <Fragment key={row.key}>
<div className={classes("ft-bar-row", { 'top': row.top })}>
<span >{row.label}</span>
<span className="ft-track"><span style={styleObject('width:' + row.width + '%')}></span></span>
<span className="ft-score">{row.score === null ? '—' : row.score}</span>
</div>
</Fragment>)}
<div className="ft-k" style={{"marginTop": "8px"}}>得分（按本人最高分缩放）</div>
</div>
<div className="ft-blk">
<div className="ft-k">能力优势 · 前三</div>
{Boolean(snapshot.topAbilities && snapshot.topAbilities.length) && (<>
<ol className="ft-rank">
{snapshot.topAbilities.map((item: any) => <Fragment key={item.label}>
<li ><span >{item.label}</span> <span className="ft-score">{'得分 ' + item.score}</span></li>
</Fragment>)}
</ol>
</>)}
{Boolean(!snapshot.topAbilities || !snapshot.topAbilities.length) && (<><div className="ft-hint">暂无数据</div></>)}
<div className="ft-k" style={{"marginTop": "10px"}}>相对较弱</div>
{Boolean(snapshot.weakestAbility) && (<>
<div className="ft-hint">{snapshot.weakestAbility.label + '（得分 ' + snapshot.weakestAbility.score + '）'}</div>
</>)}
{Boolean(!snapshot.weakestAbility) && (<><div className="ft-hint">暂无数据</div></>)}
</div>
<div className="ft-blk">
<div className="ft-k">职业价值观 · 前三</div>
{Boolean(snapshot.topValues && snapshot.topValues.length) && (<>
<ol className="ft-rank">
{snapshot.topValues.map((item: any) => <Fragment key={item.label}>
<li ><span >{item.label}</span> <span className="ft-score">{'得分 ' + item.score}</span></li>
</Fragment>)}
</ol>
</>)}
{Boolean(!snapshot.topValues || !snapshot.topValues.length) && (<><div className="ft-hint">暂无数据</div></>)}
</div>
</div>
</>)}
{Boolean(!snapshot) && (<><div className="ft-hint">该学生的最新 Y4 报告数据不完整，无法显示速览。</div></>)}
</div>
</section>
<section className="ft-panel">
<div className="ft-panel-head">
<h2 >会谈提示</h2>
<span className="ft-sub">可选，点一次生成，可编辑</span>
<span className="ft-spacer"></span>
<Button variant="outline" type="button" className="btn btn-sec btn-sm" disabled={readOnly || talkBusy} onClick={($event) => { generateTalkingPoints(); }}>{talkBusy ? '生成中…' : 'AI 生成提示'}</Button>
</div>
<div className="ft-body">
{Boolean(talkError) && (<div className="ft-error">
<span >{talkError}</span>
<Button variant="outline" type="button" className="btn btn-sec btn-sm" disabled={readOnly || talkBusy} onClick={($event) => { generateTalkingPoints(); }}>重试</Button>
</div>)}
{Boolean(script.talkingPoints.length) && (<>
<div >
<ol className="ft-tips">
{script.talkingPoints.map((point: any, index: any) => <Fragment key={index}>
<li className="ft-tip-row">
<span className="n">{index + 1}</span>
<input className="ft-input" aria-label={"会谈提示 " + (index + 1)} maxLength={120} value={point} disabled={readOnly} onChange={($event) => { setTalkingPoint(index, $event.currentTarget.value); }} />
<button type="button" className="ft-icon-btn" disabled={readOnly} aria-label={'删除第 ' + (index + 1) + ' 条提示'} onClick={($event) => { removeTalkingPoint(index); }}>×</button>
</li>
</Fragment>)}
</ol>
{Boolean(script.talkingPoints.length < 5) && (<Button variant="outline" type="button" className="btn btn-ghost btn-sm" disabled={readOnly} style={{"marginTop": "6px"}} onClick={($event) => { addTalkingPoint(); }}>+ 添加一条</Button>)}
{Boolean(script.talkingPoints.length >= 5) && (<span className="ft-hint" style={{"marginLeft": "6px"}}>最多 5 条</span>)}
</div>
</>)}
{Boolean(!script.talkingPoints.length) && (<>
<div className="ft-tipbox">还没有生成。也可以直接开始会谈。</div>
</>)}
<div className="ft-actions ft-pad-fab">
<span className="ft-spacer"></span>
<Button variant="outline" type="button" className="btn btn-primary" disabled={readOnly} onClick={($event) => { goStep(1); }}>开始会谈 →</Button>
</div>
</div>
</section>
</div>)}

{Boolean(step === 1) && (<div style={{"display": "flex", "flexDirection": "column", "gap": "10px"}}>
<div className="ft-cap">
<section className="ft-panel">
<div className="ft-panel-head">
<h2 >兴趣事项</h2>
<span className="ft-sub">{interests.length + ' 项 · ' + pendingScoreCount + ' 项待评'}</span>
<span className="ft-spacer"></span>
<span className="ft-timer">{'会谈 ' + elapsed}</span>
</div>
<div className="ft-body">
<form className="ft-add" onSubmit={($event) => { $event.preventDefault(); addInterest(); }}>
<input className="ft-input" aria-label="新增兴趣" ref={(element) => { c.$refs.addInput = element; }} maxLength={80} disabled={readOnly} autoComplete="off" placeholder="输入兴趣，回车添加（如：天文、羽毛球）" value={newInterest} onChange={($event) => { c.newInterest = $event.currentTarget.value; }} />
<Button variant="outline" type="submit" className="btn btn-primary" disabled={readOnly || !newInterest.trim()}>添加</Button>
</form>
{Boolean(remainingSuggestions.length) && (<div className="ft-chips">
<span className="ft-hint">Y4 话题：</span>
{remainingSuggestions.map((topic: any) => <Fragment key={topic}>
<button type="button" className="ft-chip" disabled={readOnly} onClick={($event) => { addSuggestion(topic); }}>{'+ ' + topic}</button>
</Fragment>)}
</div>)}
<div className="ft-rows">
{interests.map((row: any) => <Fragment key={row.id}>
<div className={classes("ft-row", { 'sel': selectedId === row.id })} onClick={($event) => { rowClick($event, row); }}>
<div className="ft-row-top">
{Boolean(editingId !== row.id) && (<>
<button type="button" className="ft-name" disabled={readOnly} title="双击重命名" onDoubleClick={($event) => { $event.stopPropagation(); beginRename(row); }}>{row.label}</button>
</>)}
{Boolean(editingId === row.id) && (<>
<input aria-label="兴趣名称" className="ft-input ft-name-input" maxLength={80} value={nameDraft} onClick={($event) => { $event.stopPropagation(); ; }} onBlur={($event) => { commitRename(row); }} onKeyDown={($event) => { if ($event.key === 'Enter') { $event.preventDefault(); commitRename(row); } if ($event.key === 'Escape') { $event.preventDefault(); cancelRename(); } }} onChange={($event) => { c.nameDraft = $event.currentTarget.value; }} />
</>)}
<button type="button" className="ft-cat" disabled={readOnly} title={'点击切换分类，当前：' + catLabel(row.topicType)} onClick={($event) => { $event.stopPropagation(); cycleCategory(row); }}>{catLabel(row.topicType)}</button>
<span className="ft-spacer"></span>
<button type="button" className="ft-star" aria-pressed={!!row.specialFocus} aria-label={'特别关注：' + row.label} title="特别关注" disabled={readOnly} onClick={($event) => { $event.stopPropagation(); toggleStar(row); }}>★</button>
<button type="button" className="ft-del" disabled={readOnly} aria-label={'删除 ' + row.label} onClick={($event) => { $event.stopPropagation(); deleteInterest(row); }}>删除</button>
</div>
<div className="ft-score-line">
<label >喜欢
                        <span className="ft-seg" role="group" aria-label={row.label + " 喜欢"}>
<button type="button" title="待评" aria-pressed={row.preferenceScore === null || row.preferenceScore === undefined} disabled={readOnly} onClick={($event) => { $event.stopPropagation(); setScore(row, 'preferenceScore', null); }}>–</button>
{[0, 1, 2, 3].map((value: any) => <Fragment key={'p' + value}>
<button type="button" title={likeLabels[value]} aria-pressed={row.preferenceScore === value} disabled={readOnly} onClick={($event) => { $event.stopPropagation(); setScore(row, 'preferenceScore', value); }}>{value}</button>
</Fragment>)}
</span>
</label>
<label >擅长
                        <span className="ft-seg" role="group" aria-label={row.label + " 擅长"}>
<button type="button" title="待评" aria-pressed={row.competenceScore === null || row.competenceScore === undefined} disabled={readOnly} onClick={($event) => { $event.stopPropagation(); setScore(row, 'competenceScore', null); }}>–</button>
{[0, 1, 2, 3].map((value: any) => <Fragment key={'g' + value}>
<button type="button" title={goodLabels[value]} aria-pressed={row.competenceScore === value} disabled={readOnly} onClick={($event) => { $event.stopPropagation(); setScore(row, 'competenceScore', value); }}>{value}</button>
</Fragment>)}
</span>
</label>
</div>
<input aria-label={row.label + " 备注"} className="ft-note" maxLength={2000} placeholder="备注（可选）" disabled={readOnly} value={row.note} onClick={($event) => { $event.stopPropagation(); ; }} onChange={($event) => { setNote(row, $event.currentTarget.value); }} />
</div>
</Fragment>)}
</div>
{Boolean(!interests.length) && (<div className="ft-hint">还没有记录。输入一个兴趣后按回车。</div>)}
</div>
</section>
<section className="ft-panel">
<div className="ft-panel-head">
<h2 >兴趣分型</h2>
<span className="ft-sub">{scoredCount + ' 项已评分'}</span>
</div>
<div className="ft-body">
<p className="ft-hint" style={{"margin": "0"}}>{selectedLabel ? ('已选中「' + selectedLabel + '」，点格子即可同时打两个分。') : '点左侧一项选中，再点格子同时打分。'}</p>
<div className="ft-quad" style={{"marginTop": "8px"}}>
{[3, 2, 1, 0].map((good: any) => <Fragment key={'row' + good}>
<div style={{"display": "contents"}}>
<div className="ft-qax">{'擅长 ' + good}</div>
{[0, 1, 2, 3].map((like: any) => <Fragment key={'cell' + like + good}>
<button type="button" aria-label={'喜欢 ' + like + '，擅长 ' + good} disabled={readOnly} className={classes("ft-qcell", [zoneClass(like, good), selectedId ? 'armed' : ''])} onClick={($event) => { cellClick(like, good); }}>
{cellItems(like, good).map((item: any) => <Fragment key={item.id}>
<span className="ft-qitem" title={item.label}>{(item.specialFocus ? '★ ' : '') + item.label}</span>
</Fragment>)}
</button>
</Fragment>)}
</div>
</Fragment>)}
<div ></div>
{[0, 1, 2, 3].map((like: any) => <Fragment key={'col' + like}>
<div className="ft-qax">{'喜欢 ' + like}</div>
</Fragment>)}
</div>
<div className="ft-legend">
<span ><i style={{"background": "#E8F5EC"}}></i>喜欢且擅长</span>
<span ><i style={{"background": "#FDF0E6"}}></i>喜欢</span>
<span ><i style={{"background": "#EEF2FB"}}></i>擅长</span>
<span >待评事项不进图</span>
</div>
{Boolean(selectedId) && (<div className="ft-hint" style={{"marginTop": "6px"}}>已选中，点右侧格子一次设定喜欢与擅长。</div>)}
</div>
</section>
</div>
<div className="ft-foot ft-pad-fab">
<Button variant="outline" type="button" className="btn" onClick={($event) => { goStep(0); }}>← 会前</Button>
<Button variant="outline" type="button" className="btn btn-primary" onClick={($event) => { goStep(2); }}>结束会谈，去整理 →</Button>
</div>
</div>)}

{Boolean(step === 2) && (<div className="ft-cards">
<section className="ft-panel">
<div className="ft-panel-head">
<h2 >会议转写</h2>
<span className="ft-sub">可选。保存后由 AI 查找遗漏的兴趣和评分差异</span>
<span className="ft-spacer"></span>
{Boolean(analyzing) && (<span className="ft-sub">正在分析…</span>)}
</div>
<div className="ft-body">
<div className="ft-drop">
{Boolean(meetingFileName) && (<>
<span >已保存 <b >{meetingFileName}</b></span>
</>)}
{Boolean(!meetingFileName) && (<>
<span >可上传文字稿，也可跳过并直接写总结。</span>
</>)}
<span className="ft-spacer"></span>
<input aria-label="会议转写文件" className="ft-file" type="file" ref={(element) => { c.$refs.fileInput = element; }} accept=".pdf,.docx,.txt,.md" disabled={readOnly || uploadBusy || analyzing} onChange={($event) => { uploadTranscript($event); }} />
<Button variant="outline" type="button" className="btn btn-sec btn-sm" disabled={readOnly || uploadBusy || analyzing} onClick={($event) => { $refs.fileInput?.click(); }}>{uploadBusy ? '上传中…' : (meetingFileName ? '替换文件' : '上传文件')}</Button>
{Boolean(meetingFileName) && (<Button variant="outline" type="button" className="btn btn-sm" disabled={readOnly || analyzing || uploadBusy} onClick={($event) => { analyzeTranscript(); }}>{analyzing ? '分析中…' : '重新分析'}</Button>)}
</div>
{!readOnly && (
  <div className="mt-3 flex flex-col items-start gap-2">
    <label htmlFor="ft-transcript-paste" className="font-semibold">粘贴会议文字稿</label>
    <textarea id="ft-transcript-paste" className="ft-textarea" rows={5}
      value={c.transcriptPaste} disabled={uploadBusy}
      onChange={(event) => { c.transcriptPaste = event.currentTarget.value; }} />
    <Button variant="outline" type="button" className="btn btn-sec btn-sm"
      disabled={uploadBusy || analyzing || !c.transcriptPaste.trim()}
      onClick={() => { c.submitPastedTranscript(); }}>
      {meetingFileName ? '替换文字稿并分析' : '保存文字稿并分析'}
    </Button>
  </div>
)}
{Boolean(uploadError) && (<div className="ft-error" role="alert">{uploadError}</div>)}
{Boolean(analyzeError) && (<div className="ft-error">
<span >{analyzeError}</span>
<Button variant="outline" type="button" className="btn btn-sec btn-sm" disabled={readOnly || analyzing || uploadBusy} onClick={($event) => { analyzeTranscript(); }}>重试</Button>
</div>)}
{Boolean(suggestionsError) && (<div className="ft-error">{suggestionsError}</div>)}
{Boolean(suggestions.length) && (<div className="ft-sugg">
{suggestions.map((s: any, index: any) => <Fragment key={s.sourceIndex}>
<div className={classes("ft-sug", { 'conf': s.conflicts.length > 0 })}>
<b >{s.label}</b>
<span className="ft-tag">{catLabel(s.topicType)}</span>
{Boolean(s.conflicts.length) && (<span className="ft-tag warn">评分不同</span>)}
{Boolean(!s.conflicts.length) && (<span className="ft-tag">新兴趣</span>)}
<details className="ev"><summary>{s.evidence ? String(s.evidence).slice(0, 100) + (s.evidence.length > 100 ? '…（展开原文）' : '') : '会议原文未提供证据'}</summary>{s.evidence && <p className="whitespace-pre-wrap">{s.evidence}</p>}</details>
{Boolean(s.conflicts.length && !s.decision) && (<>
<div className="ft-conflicts">
{conflictRows(s).map((conflict: any) => <Fragment key={conflict.key}>
<div className="ft-conf-row">
<span >{conflict.label + '：会议建议 ' + conflict.suggested + '，你记录的是 ' + conflict.current}</span>
<Button variant="outline" type="button" className="btn btn-sm btn-primary" disabled={readOnly || reviewBusy} onClick={($event) => { applyConflict(s, conflict); }}>改为 <span >{conflict.suggested}</span></Button>
<Button variant="outline" type="button" className="btn btn-sm" disabled={readOnly || reviewBusy} onClick={($event) => { keepConflict(s, conflict); }}>保留 <span >{conflict.current}</span></Button>
</div>
</Fragment>)}
</div>
</>)}
{Boolean(!s.conflicts.length && !s.decision) && (<>
<div className="ft-sugacts">
<Button variant="outline" type="button" className="btn btn-sm btn-primary" disabled={readOnly || reviewBusy} onClick={($event) => { decideSuggestion(s, true); }}>{s.existingId ? '保留' : '采纳'}</Button>
{Boolean(!s.existingId) && (<Button variant="outline" type="button" className="btn btn-sm" disabled={readOnly || reviewBusy} onClick={($event) => { decideSuggestion(s, false); }}>忽略</Button>)}
</div>
</>)}
{Boolean(s.decision) && (<span className="ft-tag ok">{decisionLabel(s)}</span>)}
</div>
</Fragment>)}
{Boolean(pendingSuggestionCount > 0) && (<div className="ft-hint">{'还有 ' + pendingSuggestionCount + ' 条建议待处理，处理完后自动保存。'}</div>)}
</div>)}
</div>
</section>
<section className="ft-panel">
<div className="ft-panel-head">
<h2 >会谈总结</h2>
<span className="ft-sub">写给家长和学生，可编辑</span>
<span className="ft-spacer"></span>
<Button variant="outline" type="button" className="btn btn-sec btn-sm" disabled={readOnly || summaryBusy} onClick={($event) => { generateSummary(); }}>{summaryBusy ? '起草中…' : 'AI 起草'}</Button>
</div>
<div className="ft-body">
{Boolean(summaryError) && (<div className="ft-error">
<span >{summaryError}</span>
<Button variant="outline" type="button" className="btn btn-sec btn-sm" disabled={readOnly || summaryBusy} onClick={($event) => { generateSummary(); }}>重试</Button>
</div>)}
<div className="ft-summary-wrap">
<textarea className="ft-textarea" aria-label="会谈总结" data-next-summary-editor="" rows={5} maxLength={1400} disabled={readOnly} value={script.nextSummary} placeholder="点「AI 起草」或直接输入" onChange={($event) => { setSummary($event.currentTarget.value); }}></textarea>
<div className="ft-count"><span >{script.nextSummary.length}</span> / 1400</div>
</div>
</div>
</section>
<section className="ft-panel">
<div className="ft-panel-head">
<h2 >项目建议</h2>
<span className="ft-sub">可选，点卡片切换是否放进报告</span>
<span className="ft-spacer"></span>
<Button variant="outline" type="button" className="btn btn-sec btn-sm" disabled={readOnly || projectsBusy || !meetingSourceId} onClick={($event) => { generateProjects(); }}>{projectsBusy ? '生成中…' : (projectItems.length ? '重新生成' : '生成建议')}</Button>
</div>
<div className="ft-body">
{Boolean(!meetingSourceId) && (<div className="ft-hint" style={{"marginBottom": "8px"}}>保存会议文字稿后可生成项目建议。</div>)}
{Boolean(projectsStale) && (<div className="ft-banner" style={{"marginBottom": "8px"}}>
<span >已过期，需重新生成</span>
<Button variant="outline" type="button" className="btn btn-sm" disabled={readOnly || projectsBusy || !meetingSourceId} onClick={($event) => { generateProjects(); }}>重新生成</Button>
</div>)}
{Boolean(projectsError) && (<div className="ft-error">{projectsError}</div>)}
{Boolean(projectItems.length) && (<div className="ft-proj">
{projectItems.map((item: any) => <Fragment key={item.recommendationId}>
<button type="button" aria-pressed={item.status === 'student_review'} disabled={readOnly || projectsBusy} className={classes("ft-proj-card", { 'off': item.status !== 'student_review' })} onClick={($event) => { toggleProject(item); }}>
<h5 >{item.title}</h5>
<span className="ft-tag">{fitLabel(item.fitType)}</span>
<p >{item.coreQuestion}</p>
<span className="ft-hint">{item.status === 'student_review' ? '✓ 放进报告' : '不放进报告'}</span>
</button>
</Fragment>)}
</div>)}
{Boolean(!projectItems.length && !projectsStale) && (<div className="ft-hint">还没有项目建议。</div>)}
</div>
</section>
<section className="ft-panel">
<div className="ft-panel-head">
<h2 >确认报告</h2>
{Boolean(confirmedReport) && (<span className="ft-sub">已确认报告</span>)}
</div>
<div className="ft-body">
{Boolean(confirmedReport && !needsNewVersion) && (<>
<div className="ft-confirmed">
<span className="ft-tag ok">{'已确认 · v' + confirmedReport.version}</span>
<a className="btn btn-sm" href={downloadHref('pdf')}>下载 PDF</a>
<a className="btn btn-sm" href={downloadHref('json')}>下载 JSON</a>
<a className="btn btn-ghost btn-sm" href={student360Href}>在学生 360 查看</a>
</div>
</>)}
{Boolean(confirmedReport && needsNewVersion) && (<>
<div className="ft-banner" style={{"marginBottom": "10px"}}>
<span >{'已确认 v' + confirmedReport.version + '；有新修改，确认后生成 v' + (confirmedReport.version + 1)}</span>
<a className="btn btn-sm" href={downloadHref('pdf')}>下载 PDF</a>
<a className="btn btn-sm" href={downloadHref('json')}>下载 JSON</a>
</div>
</>)}
{Boolean(canWrite && (!confirmedReport || needsNewVersion)) && (<div >
{Boolean(previewBusy) && (<div className="ft-hint">正在检查必填项…</div>)}
{Boolean(previewError) && (<div className="ft-hint">{previewError}</div>)}
{Boolean(previewLoaded) && (<ul className="ft-check">
{missing.map((item: any) => <Fragment key={item.key}>
<li >
<span className={classes('', item.required ? 'bad' : 'ok')}>{item.required ? '!' : '✓'}</span>
<span >{item.label}</span>
</li>
</Fragment>)}
{Boolean(previewLoaded && !missing.length) && (<>
<li ><span className="ok">✓</span><span >必填项已齐全，可确认报告。</span></li>
</>)}
</ul>)}
<div className="ft-actions ft-pad-fab">
<Button variant="outline" type="button" className="btn btn-primary" disabled={!confirmReady || confirmBusy} onClick={($event) => { confirmReport(); }}>{confirmBusy ? '生成中…' : (confirmedReport ? '确认并生成新版本' : '确认并生成报告')}</Button>
{Boolean(!confirmReady) && (<span className="ft-hint">完成必填项后可确认报告。</span>)}
{Boolean(previewError) && (<Button variant="outline" type="button" className="btn btn-ghost btn-sm" onClick={($event) => { refreshPreview(); }}>重试</Button>)}
</div>
{Boolean(confirmedError) && (<div className="ft-error">{confirmedError}</div>)}
</div>)}
{Boolean(readOnly && !confirmedReport) && (<div className="ft-hint">只读账号无法确认报告。</div>)}
</div>
</section>
</div>)}
</div>
</>)}
{Boolean(undo) && (<div className="ft-toastbar">
<span >{undo ? ('已删除「' + undo.item.label + '」') : ''}</span>
<button type="button" onClick={($event) => { undoDelete(); }}>撤销（<span >{undoSeconds}</span>s）</button>
</div>)}
{Boolean(sessionId) && (<Button variant="outline" type="button" className="btn btn-primary ft-fab" onClick={($event) => { toggleDrawer(); }}>问 Copilot</Button>)}
<Sheet open={drawerOpen} onOpenChange={open => { c.drawerOpen = open; }}><SheetContent className="ft-page ft-drawer !animate-none !transition-none" aria-describedby={undefined}><ChatPanel c={c} /></SheetContent></Sheet>
</div>);
}

export function ChatPanel({c}: {c: Workspace}) {
 const chat = c.chat;
 const readOnly = c.readOnly;
 const suggestedQuestions = c.suggestedQuestions;
 const askSuggestion = c.askSuggestion.bind(c);
 const sendChat = c.sendChat.bind(c);
 const stopChat = c.stopChat.bind(c);
 return (<div className="ft-chat-content">
<div className="ft-panel-head">
<SheetTitle>Copilot</SheetTitle>
<span className="ft-sub">基于 Y4 和本次记录回答，仅供参考</span>
<span className="ft-spacer"></span>
<Button variant="outline" type="button" className="btn btn-ghost btn-sm" onClick={($event) => { c.drawerOpen = false; }}>关闭</Button>
</div>
<div className="ft-drawer-body">
{chat.loading && <p role="status">正在加载对话…</p>}
{chat.history.length > 0 && <label>历史对话<select aria-label="历史对话" value={chat.chatId || ''} disabled={chat.sending} onChange={event => c.loadChat(event.currentTarget.value)}>{chat.history.map((item: any) => <option key={item.chatId} value={item.chatId}>{item.question || '历史对话'} · {c.fmtEditor(item.updatedAt)}</option>)}</select></label>}
<Button variant="outline" type="button" className="btn btn-sm" disabled={chat.loading || chat.sending} onClick={() => c.loadChats()}>刷新历史</Button>
<div className="ft-chips">
{suggestedQuestions.map((question: any) => <Fragment key={question}>
<button type="button" className="ft-chip" disabled={readOnly || chat.sending} onClick={($event) => { askSuggestion(question); }}>{question}</button>
</Fragment>)}
</div>
{Boolean(readOnly) && (<div className="ft-hint">只读账号可查看历史对话，不能发起提问。</div>)}
{Boolean(!chat.turns.length && !readOnly) && (<div className="ft-hint">还没有对话。可以点上面的问题，或直接提问。</div>)}
{chat.turns.map((turn: any, index: any) => <Fragment key={index}>
<div >
<div className="ft-msg q">{turn.question}</div>
{Boolean(turn.answer) && (<div className="ft-msg a">{turn.answer}</div>)}
{Boolean(turn.status === 'ASKED') && (<div className="ft-hint">正在回答…</div>)}
{Boolean(turn.status === 'STOPPED') && (<div className="ft-hint">已停止</div>)}
{Boolean(turn.status === 'ERROR') && (<div className="ft-hint">回答失败，请重试</div>)}
</div>
</Fragment>)}
{Boolean(chat.error) && (<div className="ft-hint">{chat.error}</div>)}
</div>
{Boolean(!readOnly) && (<div className="ft-chat-foot">
<textarea className="ft-textarea" maxLength={1000} disabled={chat.sending} aria-label="Copilot 问题" placeholder="问一个问题，回车发送，Shift+Enter 换行" value={chat.question} onKeyDown={($event) => { if ($event.key !== "Enter" || ($event.shiftKey || $event.altKey || $event.ctrlKey || $event.metaKey)) return; $event.preventDefault(); sendChat(); }} onChange={($event) => { c.chat.question = $event.currentTarget.value; }}></textarea>
{Boolean(!chat.sending) && (<Button variant="outline" type="button" className="btn btn-primary btn-sm" disabled={!chat.question.trim()} onClick={($event) => { sendChat(); }}>发送</Button>)}
{Boolean(chat.sending) && (<Button variant="outline" type="button" className="btn btn-sm" disabled={readOnly} onClick={($event) => { stopChat(); }}>停止</Button>)}
</div>)}
</div>);
}
