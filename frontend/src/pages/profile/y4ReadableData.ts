export type RawItem = { code: string; label?: string; value?: unknown; source_pdf?: string };
export type B3Entry = { group?: string; stage?: string; dim?: string; name?: string; score?: number | null };
export type B3Detail = {
  motivation_type?: string;
  method_type?: string;
  practice_dims?: B3Entry[];
  practice_items?: B3Entry[];
  exec_dims?: B3Entry[];
  exec_items?: B3Entry[];
  checks?: string[];
};
export type Measure = { code: string; label: string; max?: number; normCode?: string; unit?: string };

function measures(start: number, labels: string[], max?: number): Measure[] {
  return labels.map((label, i) => ({ code: String(start + i).padStart(3, "0"), label, ...(max === undefined ? {} : { max }) }));
}

// Scales: render_v2.py build_context; percentile fields and value names: extract.py schema.
// Work-value scores have no confirmed maximum in those sources: leave max absent.
export const MEASURES: Record<
  "emotion" | "self" | "drive" | "personality" | "cognitive" | "executive" |
  "motivation" | "strategy" | "holland" | "abilities" | "values", Measure[]
> = {
  emotion: measures(11, ["自卑 / 自尊", "抑郁 / 愉快", "焦虑 / 安详", "无力感 / 掌控感"], 15),
  self: measures(53, ["行为表现", "能力与学校表现", "躯体外貌", "情绪状态", "合群", "幸福与满足"], 10),
  drive: measures(60, ["自主性", "胜任感", "归属感"], 10).map((m, i) => ({ ...m, normCode: String(125 + i) })),
  personality: measures(15, ["开放性", "宜人性", "责任心", "外倾性", "神经质"], 5),
  cognitive: measures(3, ["感知觉", "注意力", "记忆力", "推理能力", "空间能力", "加工速度"], 100).map(m => ({ ...m, unit: "%" })),
  executive: measures(63, ["抑制控制", "工作记忆", "认知灵活性"], 100).map(m => ({ ...m, unit: "%" })),
  motivation: measures(66, ["深层动机", "表面动机", "自我效能感"], 10).map((m, i) => ({ ...m, normCode: String(128 + i) })),
  strategy: measures(69, ["学习深层方法与策略", "学习表面方法与策略", "学习自我调节"], 10).map((m, i) => ({ ...m, normCode: String(131 + i) })),
  holland: measures(73, ["现实型", "研究型", "艺术型", "社会型", "事业型", "常规型"], 10),
  abilities: measures(79, ["语言能力", "逻辑数学能力", "音乐能力", "空间能力", "身体运动能力", "人际关系能力", "内省能力", "自然能力"], 10),
  values: measures(95, ["创造发明", "独立自主", "美的追求", "智力激发", "利他助人", "成就感", "管理权力", "工作环境", "同事关系", "上司关系", "多样变化", "经济报酬", "安全稳定", "声望地位", "生活方式"]),
};

export function finiteNumber(value: unknown): number | null {
  if (typeof value !== "number" && typeof value !== "string") return null;
  if (typeof value === "string" && !value.trim()) return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

export function formatValue(value: unknown): string {
  if (typeof value === "number") return Number.isFinite(value) ? String(value) : "—";
  if (typeof value !== "string") return "—";
  return value.trim() || "—";
}

export function rankItems(items: RawItem[], kind: "abilities" | "values"):
  { label: string; rank: number; score: unknown; code: string }[] {
  const values = new Map(items.map(item => [item.code, item.value]));
  const allowed = new Map(MEASURES[kind].map(m => [m.label, m]));
  const seen = new Set<string>();
  const start = kind === "abilities" ? 87 : 110;
  const rows: { label: string; rank: number; score: unknown; code: string }[] = [];
  for (let i = 0; i < MEASURES[kind].length; i++) {
    const name = values.get(String(start + i).padStart(3, "0"));
    if (typeof name !== "string") continue;
    const label = name.trim();
    const measure = allowed.get(label);
    if (!measure || seen.has(label)) continue;
    seen.add(label);
    // Preserve the stored score (including absence), and the original rank gaps.
    rows.push({ label, rank: i + 1, score: values.get(measure.code), code: measure.code });
  }
  return rows;
}

export function b3Groups(b3: B3Detail):
  { title: string; rows: { label: string; score: unknown; max?: number }[] }[] {
  const lists: [keyof Pick<B3Detail, "practice_dims" | "practice_items" | "exec_dims" | "exec_items">, string][] = [
    ["practice_dims", "学习方法实践·维度"],
    ["practice_items", "学习方法实践·条目"],
    ["exec_dims", "学习策略执行·维度"],
    ["exec_items", "学习策略执行·做法"],
  ];
  // b3_detail.build_prompt explicitly specifies 0–10 for every detail score.
  // Keep every row, even with absent scores/names; type and assessment text is excluded.
  return lists.map(([key, title]) => ({
    title,
    rows: (b3[key] || []).map(entry => ({
      label: [entry.group, entry.stage, entry.dim, entry.name]
        .filter((part): part is string => typeof part === "string" && !!part.trim())
        .map(part => part.trim()).join(" / ") || "—",
      score: entry.score,
      max: 10,
    })),
  })).filter(group => group.rows.length > 0);
}

/** New B3 uses its own two measures, never the legacy self-efficacy/self-regulation labels. */
export function learningMeasures(items: RawItem[]): { motivation: Measure[]; strategy: Measure[] } {
  const newB3 = items.some(x => ["134", "135"].includes(x.code) && finiteNumber(x.value) !== null);
  return newB3 ? {
    motivation: MEASURES.motivation.slice(0, 2),
    strategy: [...MEASURES.strategy.slice(0, 2),
      {code:"134",label:"学习方法实践与提升",max:10},
      {code:"135",label:"学习策略执行与优化",max:10}],
  } : { motivation: MEASURES.motivation, strategy: MEASURES.strategy };
}

const codesOf = (rows: Measure[]) => rows.map(x => x.code);
const range = (start: number, count: number) => Array.from({length:count}, (_,i) => String(start+i).padStart(3,"0"));
const READABLE_CODES = {
  heartA2: ["009", ...codesOf(MEASURES.emotion), ...codesOf(MEASURES.personality), ...range(23,9)],
  heartB4: ["051", "059", ...codesOf(MEASURES.self), ...codesOf(MEASURES.drive)],
  physical: ["041", "043", "044", "045", "047", "049"],
  cognitive: ["001", "002", ...codesOf(MEASURES.cognitive)],
  b3: [...codesOf(MEASURES.executive), ...codesOf(MEASURES.motivation), ...codesOf(MEASURES.strategy), "134", "135"],
  b6: ["072", ...codesOf(MEASURES.holland), ...codesOf(MEASURES.abilities), ...codesOf(MEASURES.values), ...range(87,8), ...range(110,15)],
};
/** A missing headline must never hide a saved subscore, including a zero. */
export function readableHasData(items: RawItem[], section: keyof typeof READABLE_CODES): boolean {
  const codes = new Set(READABLE_CODES[section]);
  return items.some(x => codes.has(x.code) && (finiteNumber(x.value) !== null ||
    ((x.code === "072" || (Number(x.code) >= 87 && Number(x.code) <= 94) || (Number(x.code) >= 110 && Number(x.code) <= 124)) && typeof x.value === "string" && !!x.value.trim() && x.value !== "—")));
}
