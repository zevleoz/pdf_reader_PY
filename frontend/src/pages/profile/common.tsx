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
    <section className={cn("mb-6 border-t-2 border-rule", className)}>
      {title || right ? (
        <div className="flex flex-wrap items-start justify-between gap-3 py-3">
          <div className="min-w-0">
            {title ? <h2 className="text-base font-bold">{title}</h2> : null}
            {sub ? <div className="mt-0.5 text-xs text-mute">{sub}</div> : null}
          </div>
          {right ? <div className="flex flex-wrap items-center gap-2">{right}</div> : null}
        </div>
      ) : null}
      {children}
    </section>
  );
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
