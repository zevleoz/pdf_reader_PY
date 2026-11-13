import * as React from "react";
import { getJSON, errorText } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { useProfile, type Y4Data } from "./common";
import type { Y4Upload } from "./Y4Upload";
import { MEASURES, finiteNumber, formatValue, rankItems, b3Groups, learningMeasures, readableHasData, type RawItem, type B3Detail } from "./y4ReadableData";
import "./y4Readable.css";

type Raw = { raw: { schema_124?: RawItem[]; b3_detail?: B3Detail } };
type Measure = { code: string; label: string; max?: number; normCode?: string; unit?: string };
const SYSTEMS = ["心力", "精力", "学习力", "生涯力"];
const numberText = (v: unknown) => finiteNumber(v) === null ? "—" : formatValue(v);
const present = (v: unknown) => v !== null && v !== undefined && String(v).trim() !== "" && v !== "—";

function Score({ label, value, max, norm, unit, missing = "未读取" }: { label: string; value: unknown; max?: number; norm?: unknown; unit?: string; missing?: string }) {
  const n = finiteNumber(value), avg = finiteNumber(norm);
  const has = n !== null;
  return <div className="yr-row">
    <span className="yr-label">{label}</span>
    <span className="yr-track" aria-hidden="true">
      {n !== null && max ? <span style={{ width: `${Math.min(100, Math.max(0, n / max * 100))}%` }} /> : null}
      {avg !== null && max ? <i style={{ left: `${Math.min(100, Math.max(0, avg / max * 100))}%` }} /> : null}
    </span>
    <span className="yr-value">{has ? formatValue(value) : <small>{missing}</small>}{has && max ? <small>{unit === "%" ? "%" : `/${max}`}</small> : has && unit ? <small> {unit}</small> : null}</span>
    {avg !== null ? <span className="yr-norm">同龄平均 {formatValue(norm)}</span> : null}
  </div>;
}

function Panel({ title, children, wide = false }: { title: string; children: React.ReactNode; wide?: boolean }) {
  return <section className={`yr-panel${wide ? " yr-wide" : ""}`} aria-label={title}><h3>{title}</h3>{children}</section>;
}

export default function Y4Readable({ data: y4, up, onEdit, version }: { data: Y4Data; up: Y4Upload; onEdit: () => void; version: number }) {
  const { data } = useProfile();
  const [raw, setRaw] = React.useState<Raw["raw"] | null>(null);
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState("");
  const [retry, setRetry] = React.useState(0);
  const rid = y4.report?.id;
  React.useEffect(() => {
    setRaw(null); setError("");
    if (!rid || !data.permissions.full) { setLoading(false); return; }
    let live = true; setLoading(true);
    getJSON<Raw>(`/api/reports/${rid}/raw`).then(d => { if (live) setRaw(d.raw); })
      .catch(e => { if (live) setError(errorText(e, "画像数据加载失败")); })
      .finally(() => { if (live) setLoading(false); });
    return () => { live = false; };
  }, [rid, data.permissions.full, y4, version, retry]);
  const items: RawItem[] = raw?.schema_124 || y4.items;
  const values = new Map(items.map(x => [String(x.code), x.value]));
  const value = (code: string) => values.get(code);
  const groups = b3Groups(raw?.b3_detail || {});
  const learning = learningMeasures(items);
  const abilities = rankItems(items, "abilities"), workValues = rankItems(items, "values");
  const missingSlot = (slot: string, section: Parameters<typeof readableHasData>[1]) => {
    const state = up.status?.slots[slot];
    if (readableHasData(items, section)) return null;
    if (!state) return <p className="yr-empty">暂无数据</p>;
    if (state.state === "queued" || state.state === "reading") return <p className="yr-empty">{slot} {state.state === "queued" ? "排队中" : "读取中"}</p>;
    return <p className="yr-empty">{slot} {state.has_data || state.state === "done" ? "暂无可读取数据" : state.state === "failed" ? "读取失败，请在资料中重试" : "未上传"}</p>;
  };
  const rows = (specs: Measure[]) => specs.map(m => <Score key={m.code} {...m} value={value(m.code)} norm={m.normCode ? value(m.normCode) : undefined} />);
  const summary = [
    ["情绪稳定性", finiteNumber(value("009")) !== null ? `${numberText(value("009"))} /60` : "—"],
    ["自我概念", finiteNumber(value("051")) !== null ? `${numberText(value("051"))} /100` : "—"],
    ["认知百分位", finiteNumber(value("002")) !== null ? `${numberText(value("002"))}%` : "—"],
    ["职业兴趣代码", formatValue(value("072"))],
    ["能力优势前三", abilities.filter(x => x.rank <= 3).map(x => x.label).join(" · ") || "—"],
    ["职业价值观前三", workValues.filter(x => x.rank <= 3).map(x => x.label).join(" · ") || "—"],
  ];
  const unrankedAbilities = MEASURES.abilities.filter(m => !abilities.some(r => r.code === m.code) && present(value(m.code)));
  const a2 = missingSlot("A2", "heartA2");
  const heartB4 = missingSlot("B4", "heartB4");
  const b4 = missingSlot("B4", "cognitive");
  const b3 = groups.length ? null : missingSlot("B3", "b3");
  const b6 = abilities.length || workValues.length ? null : missingSlot("B6", "b6");

  return <div className="yr">
    <div className="yr-toolbar"><span className="yr-meta">{y4.report?.report_date ? `测评记录 · ${y4.report.report_date}` : "暂无测评记录"}</span>
      {data.permissions.can_write && data.permissions.full && rid ? <Button variant="outline" size="sm" onClick={onEdit}>编辑数值</Button> : null}
    </div>
    <nav className="yr-jump" aria-label="画像维度">{SYSTEMS.map((s, i) => <a key={s} href={`#y4-system-${i}`}>{s}</a>)}</nav>
    {loading ? <p role="status" className="yr-meta">加载画像…</p> : null}
    {error ? <div role="alert" className="yr-error">{error}<Button variant="outline" size="sm" onClick={() => setRetry(x => x + 1)}>重试</Button></div> : null}
    <dl className="yr-glance">{summary.map(([label, v]) => <div key={label}><dt>{label}</dt><dd>{v}</dd></div>)}</dl>
    <section className="yr-system" id="y4-system-0"><h2>心力</h2><div className="yr-grid">
      {a2 ? <Panel title="情绪、依恋与人格">{a2}</Panel> : <Panel title="情绪稳定性"><Score label="总分" value={value("009")} max={60} norm={present(value("009")) ? 40 : undefined} />{rows(MEASURES.emotion)}</Panel>}
      {heartB4 ? <Panel title="自我概念与内驱力">{heartB4}</Panel> : <Panel title="自我概念"><Score label="整体" value={value("051")} max={100} />{rows(MEASURES.self)}</Panel>}
      {!a2 ? <Panel title="依恋关系"><table className="yr-attachment"><caption className="sr-only">依恋关系各维度得分</caption><thead><tr><th scope="col">维度</th>{["母亲", "父亲", "同伴"].map(x => <th scope="col" key={x}>{x}</th>)}</tr></thead><tbody>{[["信任", 23, 50], ["沟通", 26, 45], ["亲近", 29, 30]].map(([label, start, max]) => <tr key={label}><th scope="row">{label}</th>{[0,1,2].map(i => <td key={i}>{numberText(value(String(Number(start) + i).padStart(3, "0")))}<small>/{max}</small></td>)}</tr>)}</tbody></table></Panel> : null}
      {!heartB4 ? <Panel title="内驱力">{rows(MEASURES.drive)}<Score label="思维模式" value={value("059")} max={100} /><div className="yr-endpoints"><span>固定型</span><span>成长型</span></div></Panel> : null}
      {!a2 ? <Panel title="人格">{rows(MEASURES.personality)}</Panel> : null}
    </div></section>
    <section className="yr-system" id="y4-system-1"><h2>精力</h2>{missingSlot("A2", "physical") || <div className="yr-grid"><Panel title="体质健康" wide><dl className="yr-facts">{[["身高", "043", "cm"], ["体重", "044", "kg"], ["BMI", "041", "kg/m²"], ["饮食习惯", "045", "分"], ["睡眠", "047", "小时/天"], ["运动", "049", "小时/周"]].map(([l,c,u]) => <div key={c}><dt>{l}</dt><dd>{numberText(value(c))}{finiteNumber(value(c)) !== null ? <small> {u}</small> : null}</dd></div>)}</dl></Panel></div>}</section>
    <section className="yr-system" id="y4-system-2"><h2>学习力</h2><div className="yr-grid">
      <Panel title="认知能力">{b4 || <><div className="yr-cognitive"><span>总得分 <b>{numberText(value("001"))}</b></span><span>百分位 <b>{numberText(value("002"))}{finiteNumber(value("002")) !== null ? "%" : ""}</b></span></div>{rows(MEASURES.cognitive)}</>}</Panel>
      {b3 ? <Panel title="核心学习能力">{b3}</Panel> : <>
        <Panel title="执行功能">{rows(MEASURES.executive)}</Panel>
        <Panel title="学习动机与策略">{rows(learning.motivation)}<h4>学习策略</h4>{rows(learning.strategy)}</Panel>
        {groups.map(g => <Panel title={g.title} key={g.title}>{g.rows.map((r,i) => <Score key={i} label={r.label} value={r.score} max={r.max} />)}</Panel>)}
      </>}
    </div></section>
    <section className="yr-system" id="y4-system-3"><h2>生涯力</h2>{b6 || <div className="yr-grid">
      <Panel title="职业兴趣"><div className="yr-interest-code">{formatValue(value("072"))}</div>{rows(MEASURES.holland)}</Panel>
      <Panel title="能力优势">{abilities.length ? abilities.map(r => <Score key={r.rank} label={`${r.rank}. ${r.label}`} value={r.score} max={10} missing="—" />) : rows(MEASURES.abilities)}{abilities.length && unrankedAbilities.length ? <><h4>其他已读分数</h4>{rows(unrankedAbilities)}</> : null}</Panel>
      <Panel title="职业价值观"><ol className="yr-ranks">{workValues.map(r => <li value={r.rank} key={r.rank}><span>{r.label}</span>{finiteNumber(r.score) !== null ? <b>{formatValue(r.score)}</b> : null}</li>)}</ol>{!workValues.length ? <p className="yr-empty">暂无排序数据</p> : null}</Panel>
    </div>}</section>
  </div>;
}
