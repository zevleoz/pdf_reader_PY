import * as React from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError, getJSON } from "@/lib/api";
import type { Progress } from "@/lib/progress";
import { cn } from "@/lib/utils";

/* ------------------------------------------------------------------ 类型 */
export type StudentInfo = {
  id: number;
  code: string;
  name: string;
  grade: string;
  gender: string;
  birthday: string;
  school: string;
  advisor_name: string;
  email: string;
  phone: string;
};

export type Permissions = {
  can_write: boolean;
  is_admin: boolean;
  full: boolean;
  can_review: boolean;
  m1_access: boolean;
};

export type FlagItem = { id: string | number; label: string; answer: string };
export type OpenFlag = {
  assignment_id: number;
  questionnaire_title: string;
  flags: FlagItem[];
};

export type FirstTouchInterest = {
  label: string;
  preferenceScore: number;
  competenceScore: number;
  specialFocus: boolean;
};
export type FirstTouchReport = { id: number; version: number; confirmedAt: string; confirmedBy: string };
export type FirstTouch = {
  status: "needs_y4" | "not_started" | "completed" | "in_progress";
  step: number | null;
  canStart: boolean;
  sessionId: number | null;
  interests: FirstTouchInterest[];
  scoredCount: number;
  pendingCount: number;
  reports: FirstTouchReport[];
  restricted?: boolean;
  updatedAt?: string;
  confirmedAt?: string;
};

export type PageData = {
  ok: boolean;
  student: StudentInfo;
  permissions: Permissions;
  progress: Progress;
  latest_report: { id: number; report_date: string | null } | null;
  six_am: { report_id: number; profile_id: number; version: number } | null;
  first_touch: FirstTouch;
  questionnaire_flags: OpenFlag[];
};

export type ScoreBand = { label: string; tone?: string; advice?: string } | null;
export type ScoreLine = {
  group?: string;
  name?: string;
  label?: string;
  score: number | null;
  min: number;
  max: number;
  answered: number;
  item_count: number;
  band: ScoreBand;
};
export type ScoreSet = {
  assignment_id?: number;
  questionnaire_title?: string;
  submitted_at?: string | null;
  total?: ScoreLine | null;
  dimensions?: ScoreLine[];
  flags?: FlagItem[];
  reviewed_at?: string | null;
  reviewed_by?: string;
};

export type SixAmModel = { dims: { id: string; name: string }[]; levels: string[] };
export type SixAmReview = {
  verdict: string;
  adjusted_state?: string | null;
  note?: string;
  author?: string;
  created_at?: string | null;
};
export type SixAmProfileRow = {
  id: number;
  report_id: number;
  version: number;
  created_at: string | null;
  profile: { schema?: string; dims?: Record<string, { level?: string }> };
};

export type Y4Dim = { name: string; healthy: number; weak_count: number; total: number };
export type Y4Item = { code: string; label: string; value: unknown; dimension: string; eval: string };
export type Y4Data = {
  ok: boolean;
  report: { id: number; report_date: string | null } | null;
  dims: Y4Dim[];
  signals: Record<string, number> | null;
  items: Y4Item[];
};

export const DIMS = ["A1", "A2", "A3", "A4", "A5"];
export const VERDICT_ZH: Record<string, string> = {
  agree: "同意",
  adjust: "调整状态",
  evidence: "证据不足，需追问",
};

/* ------------------------------------------------------------------ 格式 */
function pad(n: number): string {
  return (n < 10 ? "0" : "") + n;
}

/** 与旧页 y4FmtDT 同契约：YYYY-MM-DD HH:MM。 */
export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return String(iso).slice(0, 16).replace("T", " ");
  return (
    d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate()) + " " + pad(d.getHours()) + ":" + pad(d.getMinutes())
  );
}

/** 与旧页 dt_short 同契约：压到分钟，不转换时区。 */
export function dtShort(value: string | null | undefined): string {
  if (!value) return "";
  return String(value).slice(0, 16).replace("T", " ");
}

function ftDate(iso: string | null | undefined): Date | null {
  if (!iso) return null;
  let text = String(iso).trim();
  if (/\d{2}:\d{2}/.test(text) && !/(?:[zZ]|[+-]\d{2}:?\d{2})$/.test(text)) text += "Z";
  const d = new Date(text);
  return isNaN(d.getTime()) ? null : d;
}

/** First Touch 的 confirmedAt 是 naive UTC；按上海时间显示（与旧页 fmtFTTime 同）。 */
export function fmtFTTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = ftDate(iso);
  if (!d) return String(iso).slice(0, 16).replace("T", " ");
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).formatToParts(d);
  const map: Record<string, string> = {};
  parts.forEach((part) => {
    map[part.type] = part.value;
  });
  if (!map.year) return String(iso).slice(0, 16).replace("T", " ");
  return map.year + "-" + map.month + "-" + map.day + " " + (map.hour === "24" ? "00" : map.hour) + ":" + map.minute;
}

export function ftSortKey(iso: string | null | undefined): number {
  const d = ftDate(iso);
  return d ? d.getTime() : 0;
}

export function sortKey(iso: string | null | undefined): number {
  if (!iso) return 0;
  const t = new Date(iso).getTime();
  return isNaN(t) ? 0 : t;
}

export function fmtValue(v: unknown): string {
  if (v === null || v === undefined || v === "") return "—";
  return String(v);
}

export const Q_LABEL: Record<string, string> = {
  pending: "待确认",
  sent: "已发送",
  submitted: "已提交",
  expired: "已过期",
  rejected: "已驳回",
};

/* ------------------------------------------------------------------ 取数缓存 */
type Slot = { status: "idle" | "loading" | "ready" | "error"; data?: unknown; error?: unknown };
const IDLE: Slot = { status: "idle" };

/** 每个 tab 第一次打开时取数，之后保留；多个 tab 共用同一份。 */
export class ResourceCache {
  private slots = new Map<string, Slot>();
  private subs = new Set<() => void>();

  get = (key: string): Slot => this.slots.get(key) || IDLE;

  subscribe = (fn: () => void) => {
    this.subs.add(fn);
    return () => {
      this.subs.delete(fn);
    };
  };

  private put(key: string, slot: Slot) {
    this.slots.set(key, slot);
    this.subs.forEach((fn) => fn());
  }

  load(key: string, url: string) {
    if (this.get(key).status !== "idle") return;
    this.put(key, { status: "loading" });
    getJSON<unknown>(url)
      .then((data) => this.put(key, { status: "ready", data }))
      .catch((error) => this.put(key, { status: "error", error }));
  }

  set(key: string, data: unknown) {
    this.put(key, { status: "ready", data });
  }

  /** 不带参数：全部作废；带参数：只作废这些。已挂载的 tab 会自动重新取数。 */
  invalidate(...keys: string[]) {
    if (keys.length === 0) this.slots.clear();
    else keys.forEach((key) => this.slots.delete(key));
    this.subs.forEach((fn) => fn());
  }
}

export type Notify = (text: string, kind?: "ok" | "error") => void;

export type ProfileCtxValue = {
  data: PageData;
  code: string;
  cache: ResourceCache;
  notify: Notify;
  setTab: (tab: string) => void;
  refreshProgress: () => Promise<void>;
  refreshPage: () => Promise<void>;
  /** Y4 画像 tab 当前筛选的维度（空 = 全部）；概览的维度卡点击后设置并切到 y4。 */
  y4Dim: string;
  setY4Dim: (dim: string) => void;
  /** 标记问卷安全提醒已跟进（页头标记、问卷 tab 横幅共用）。 */
  reviewFlag: (f: OpenFlag) => Promise<void>;
};

export const ProfileCtx = React.createContext<ProfileCtxValue | null>(null);

export function useProfile(): ProfileCtxValue {
  const ctx = React.useContext(ProfileCtx);
  if (!ctx) throw new Error("useProfile 必须在学生档案页内使用");
  return ctx;
}

export type Resource<T> = {
  status: Slot["status"];
  data: T | undefined;
  error: unknown;
  reload: () => void;
};

/** url 为 null 时不取数（例如没有 6AM 档案时不取评议）。 */
export function useResource<T>(key: string, url: string | null): Resource<T> {
  const { cache } = useProfile();
  const slot = React.useSyncExternalStore(cache.subscribe, () => cache.get(key));
  React.useEffect(() => {
    if (url && slot.status === "idle") cache.load(key, url);
  }, [cache, key, url, slot.status]);
  return {
    status: url ? slot.status : "ready",
    data: slot.data as T | undefined,
    error: slot.error,
    reload: () => cache.invalidate(key),
  };
}

/* ------------------------------------------------------------------ 小部件 */
export const fieldClass =
  "border border-input bg-background px-3 text-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:opacity-50";

export function Tag({ children, tone = "plain" }: { children: React.ReactNode; tone?: "strong" | "plain" | "soft" | "alert" }) {
  return (
    <Badge
      variant="outline"
      className={cn(
        "rounded-none whitespace-nowrap",
        tone === "strong" && "border-rule bg-ink text-white",
        tone === "soft" && "border-line bg-sunk text-ink",
        tone === "alert" && "border-attention text-attention",
        tone === "plain" && "border-rule",
      )}
    >
      {children}
    </Badge>
  );
}

export function Section({
  title,
  sub,
  right,
  children,
  className,
}: {
  title?: React.ReactNode;
  sub?: React.ReactNode;
  right?: React.ReactNode;
  children?: React.ReactNode;
  className?: string;
}) {
  return (
    <section className={cn("mb-[22px] border-t-2 border-rule pt-[9px]", className)}>
      {title || right ? (
        <div className="mb-2.5 flex flex-wrap items-center gap-x-2 gap-y-1">
          {title ? <h2 className="text-sm font-bold">{title}</h2> : null}
          {sub ? <small className="text-[12.5px] font-normal text-mute">{sub}</small> : null}
          {right ? <div className="ml-auto flex flex-wrap items-center gap-1.5">{right}</div> : null}
        </div>
      ) : null}
      {children}
    </section>
  );
}

/* ---- 状态小块（原型 .st / s0–s3 / sn） ---- */
export type ChipTone = "s0" | "s1" | "s2" | "s3" | "sn";
const CHIP_CLASS: Record<ChipTone, string> = {
  s0: "bg-s0-bg text-s0",
  s1: "bg-s1-bg text-s1",
  s2: "bg-s2-bg text-s2",
  s3: "bg-s3-bg text-s3",
  sn: "bg-sunk text-ink-2",
};

export function Chip({ tone = "sn", children, className }: { tone?: ChipTone; children: React.ReactNode; className?: string }) {
  return (
    <span className={cn("inline-flex h-[22px] items-center whitespace-nowrap px-2 text-[12.5px] font-semibold", CHIP_CLASS[tone], className)}>
      {children}
    </span>
  );
}

/** Y4 有效评价用语 -> 色调。「高」「不低」不上色（不一定是好事）。 */
export function evalTone(word: string): ChipTone {
  if (word === "严重偏低" || word === "需特殊关注") return "s3";
  if (word === "明显偏低" || word === "需关注") return "s2";
  if (word === "偏低") return "s1";
  if (word === "较好" || word === "相对健康") return "s0";
  return "sn";
}

export const WEAK_EVALS = ["偏低", "明显偏低", "严重偏低", "需关注", "需特殊关注"];

const SIX_AM_LEVELS = ["稳固", "关注", "风险", "阻塞"];
const SIX_AM_TONES: ChipTone[] = ["s0", "s1", "s2", "s3"];

/** 6AM 档位 -> 色调：模型的 levels 恰好是这四个时按位置对应，否则一律 sn。 */
export function levelTone(level: string | undefined, levels: string[] | undefined): ChipTone {
  if (!level || !levels || levels.length !== 4 || levels.some((l, i) => l !== SIX_AM_LEVELS[i])) return "sn";
  const i = levels.indexOf(level);
  return i < 0 ? "sn" : SIX_AM_TONES[i];
}

/** 居中的空态面板（原型 .panel > .empty）：粗标题、一行说明、按钮。 */
export function EmptyPanel({ title, line, children }: { title: React.ReactNode; line?: React.ReactNode; children?: React.ReactNode }) {
  return (
    <div className="px-4 py-11 text-center text-mute">
      <b className="mb-1 block text-base text-ink">{title}</b>
      {line}
      {children ? <div className="mt-3">{children}</div> : null}
    </div>
  );
}

/** 把一个 fetch 响应保存为文件（文件名取 Content-Disposition 的 filename*）。 */
export async function saveResponse(resp: Response, fallbackName: string): Promise<void> {
  const blob = await resp.blob();
  let filename = fallbackName;
  const disp = resp.headers.get("Content-Disposition") || "";
  const star = disp.match(/filename\*=UTF-8''([^;\n]+)/i);
  if (star) {
    try {
      filename = decodeURIComponent(star[1]);
    } catch {
      // 保留默认文件名
    }
  }
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 5000);
}

export function useY4Data(): Resource<Y4Data> {
  const { code } = useProfile();
  return useResource<Y4Data>("y4data", "/api/profiling/students/" + encodeURIComponent(code) + "/y4");
}

export function Empty({ children }: { children: React.ReactNode }) {
  return <p className="border-t border-line py-8 text-center text-mute">{children}</p>;
}

export function Loading() {
  return (
    <div className="space-y-3 py-4" aria-busy="true">
      <Skeleton className="h-4 w-64 max-w-full" />
      <Skeleton className="h-4 w-48 max-w-full" />
      <Skeleton className="h-4 w-56 max-w-full" />
    </div>
  );
}

export function LoadError({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  return (
    <div className="py-8">
      <p className="mb-3">
        无法载入
        {error instanceof ApiError ? " " + error.message : ""}
      </p>
      {onRetry ? (
        <Button variant="outline" onClick={onRetry}>
          重试
        </Button>
      ) : null}
    </div>
  );
}

/** 一个 tab 的取数状态：加载中 / 失败 / 就绪时才渲染 children。 */
export function Gate<T>({
  res,
  children,
}: {
  res: Resource<T>;
  children: (data: T) => React.ReactNode;
}) {
  if (res.status === "error") return <LoadError error={res.error} onRetry={res.reload} />;
  if (res.status !== "ready" || res.data === undefined) return <Loading />;
  return <>{children(res.data)}</>;
}
