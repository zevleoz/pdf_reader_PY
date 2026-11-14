import * as React from "react";

import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { cn } from "@/lib/utils";

import {
  Chip,
  DIMS,
  Empty,
  EmptyPanel,
  fmtDate,
  fmtFTTime,
  ftSortKey,
  Gate,
  levelTone,
  Loading,
  LoadError,
  Section,
  sortKey,
  Tag,
  useProfile,
  useResource,
  useY4Data,
  type Resource,
  type Y4Data,
} from "./common";
import { NextAction } from "./NextStep";
import { useY4Upload, Y4_SLOTS } from "./Y4Upload";
import { dimName, reviewText, useSixAm } from "./SixAmTab";
import type { QResp } from "./QuestionnaireTab";

type Booking = { id: number; appointment_time: string | null; status: string; advisor_name: string; notes: string };
type Minute = { id: number; report_id?: number | null; created_at: string | null; report_date: string | null; preview: string; minutes_text: string };
type MinutesResp = { minutes: Minute[]; restricted?: boolean };
type FileRow = { id: number; report_date: string | null; created_at: string | null };

const BOOKING_ZH: Record<string, string> = { pending: "待完成", completed: "已完成", cancelled: "已取消" };
function bookingText(s: string): string {
  return BOOKING_ZH[s] || s || "—";
}

function bookingTone(s: string): "strong" | "plain" | "alert" {
  if (s === "confirmed" || s === "completed") return "strong";
  if (s === "cancelled") return "alert";
  return "plain";
}

const SIGNAL_NAMES = ["强干预", "弱干预", "强潜能", "弱潜能"];

function Y4SourceStatus() {
  const { setTab } = useProfile();
  const up = useY4Upload();
  const labels: Record<string, string> = {
    empty: "未上传", queued: "排队中", reading: "读取中", done: "已读取", failed: "读取失败",
  };
  return <section className="mb-[26px] border-y border-line" aria-label="Y4 测评资料">
    <div className="flex items-center justify-between gap-3 px-3 py-2">
      <h2 className="text-sm font-semibold">Y4 测评资料</h2>
      <button type="button" onClick={() => setTab("y4")} className="text-xs underline underline-offset-4">查看资料</button>
    </div>
    {up.error ? <div className="flex items-center gap-3 px-3 pb-2 text-sm" role="alert">
      <span>资料状态加载失败</span><button type="button" className="underline" onClick={() => void up.load()}>重试</button>
    </div> : null}
    <div className="grid grid-cols-2 border-t border-line md:grid-cols-4">
      {Y4_SLOTS.map(slot => {
        const state = up.status?.slots[slot.key]?.state;
        return <button key={slot.key} type="button" onClick={() => setTab("y4")}
          aria-label={slot.label + " · " + (up.error ? "状态暂不可用" : state ? labels[state] : "加载中")}
          className="flex items-center justify-between gap-3 border-l border-line px-3 py-3 text-left first:border-l-0 hover:bg-sunk focus-visible:outline focus-visible:outline-2 focus-visible:outline-ink max-md:odd:border-l-0">
          <b className="text-sm">{slot.key}</b>
          <span className="text-xs text-mute">{up.error ? "—" : state ? labels[state] : "加载中…"}</span>
        </button>;
      })}
    </div>
  </section>;
}

function Signals({ y4 }: { y4: Y4Data }) {
  if (!y4.signals) return null;
  const sig = y4.signals;
  return (
    <Section
      title="Y4 研判"
      sub="四个名单"
      right={
        <a href="/insights/y4-signals" className="text-[12.5px] font-semibold text-hl hover:underline">
          看全部
        </a>
      }
    >
      <div className="grid grid-cols-4 gap-2.5">
        {SIGNAL_NAMES.map((n) => (
          <div key={n}>
            <b className="block text-[26px] font-bold leading-[1.1]">{sig[n] ?? 0}</b>
            <small className="text-[12.5px] text-mute">{n}</small>
          </div>
        ))}
      </div>
    </Section>
  );
}

function SixAmRows() {
  const sa = useSixAm();
  if (!sa.six) return <Empty>暂无 6AM 档案</Empty>;
  if (sa.failed) return <LoadError error={sa.failed.error} onRetry={sa.failed.reload} />;
  if (sa.pending || !sa.model.data || !sa.profiles.data || !sa.reviews.data) return <Loading />;
  if (sa.legacy) return <Empty>这份档案按旧规则生成</Empty>;
  const model = sa.model.data.model;
  const dims = (sa.profile?.profile.dims || {}) as Record<string, { level?: string }>;
  const reviews = sa.reviews.data.profile_id === sa.six.profile_id ? sa.reviews.data.reviews || {} : {};
  return (
    <div>
      {DIMS.map((dim) => {
        const r = reviews[dim];
        const t = r && r.verdict ? reviewText(r) : null;
        const level = dims[dim]?.level;
        return (
          <div key={dim} className="border-b border-line py-[7px]">
            <div className="flex items-center justify-between gap-2.5">
              <span>{dim + " " + dimName(model, dim)}</span>
              <Chip tone={levelTone(level, model.levels)}>{level || "—"}</Chip>
            </div>
            {t ? <p className="mt-0.5 text-xs text-mute">{t.head}</p> : null}
          </div>
        );
      })}
    </div>
  );
}

function Bookings({ res }: { res: Resource<{ bookings: Booking[] }> }) {
  return (
    <Gate res={res}>
      {(d) =>
        d.bookings.length === 0 ? (
          <Empty>暂无预约记录</Empty>
        ) : (
          <Table className="min-w-[560px]">
            <TableHeader>
              <TableRow>
                <TableHead>预约时间</TableHead>
                <TableHead>状态</TableHead>
                <TableHead>顾问</TableHead>
                <TableHead>备注</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {d.bookings.map((b) => (
                <TableRow key={b.id}>
                  <TableCell className="font-mono">{fmtDate(b.appointment_time)}</TableCell>
                  <TableCell>
                    <Tag tone={bookingTone(b.status)}>{bookingText(b.status)}</Tag>
                  </TableCell>
                  <TableCell>{b.advisor_name || "—"}</TableCell>
                  <TableCell className="max-w-[320px] text-xs text-mute">{b.notes || "—"}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )
      }
    </Gate>
  );
}

function Minutes({ res, studentId }: { res: Resource<MinutesResp>; studentId: number }) {
  const [open, setOpen] = React.useState<Record<number, boolean>>({});
  return (
    <Gate res={res}>
      {(d) => {
        if (d.restricted) return <Empty>当前账号不显示纪要内容。</Empty>;
        if (d.minutes.length === 0) return <Empty>暂无解读会纪要</Empty>;
        return (
          <div>
            {d.minutes.map((m) => (
              <div key={m.id} className="border-t border-line py-3">
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div className="min-w-0">
                    <div className="font-mono font-semibold">{fmtDate(m.created_at)}</div>
                    <div className="text-xs text-mute">{m.report_date ? "关联报告：" + m.report_date : "未绑定报告"}</div>
                  </div>
                  <div className="flex gap-2">
                    <Button variant="outline" size="sm" asChild>
                      <a href={"/tools/transcript?student_id=" + studentId + "#m" + m.id} target="_blank" rel="noreferrer">
                        前往
                      </a>
                    </Button>
                    <Button variant="outline" size="sm" onClick={() => setOpen((o) => ({ ...o, [m.id]: !o[m.id] }))}>
                      {open[m.id] ? "收起" : "查看"}
                    </Button>
                  </div>
                </div>
                <p className="mt-2 whitespace-pre-wrap break-words text-sm text-mute">
                  {open[m.id] ? m.minutes_text || "（无内容）" : m.preview || "（无预览）"}
                </p>
              </div>
            ))}
          </div>
        );
      }}
    </Gate>
  );
}

type Event = { at: number; label: string; text: string; auto: boolean };

const SHOWN = 8;

function Activity({ bookings, minutes }: { bookings: Resource<{ bookings: Booking[] }>; minutes: Resource<MinutesResp> }) {
  const { data, code } = useProfile();
  const base = "/students/" + encodeURIComponent(code) + "/api/";
  const files = useResource<{ reports: FileRow[] }>("files", base + "reports");
  const qs = useResource<QResp>("questionnaires", base + "questionnaires");
  const sa = useSixAm();
  const [all, setAll] = React.useState(false);
  const rs: Resource<unknown>[] = [bookings, minutes, files, qs, sa.profiles, sa.reviews];
  const failed = rs.find((r) => r.status === "error");
  if (failed) return <LoadError error={failed.error} onRetry={failed.reload} />;
  if (rs.some((r) => r.status !== "ready")) return <Loading />;

  const events: Event[] = [];
  (files.data?.reports || []).forEach((r) =>
    events.push({ at: sortKey(r.report_date), label: r.report_date || "—", text: "Y4 报告 " + (r.report_date || "—"), auto: true }),
  );
  (bookings.data?.bookings || []).forEach((b) =>
    events.push({ at: sortKey(b.appointment_time), label: fmtDate(b.appointment_time).slice(0, 10), text: "预约 " + bookingText(b.status), auto: false }),
  );
  (minutes.data?.minutes || []).forEach((m) =>
    events.push({ at: sortKey(m.created_at), label: fmtDate(m.created_at).slice(0, 10), text: "解读会纪要", auto: false }),
  );
  (qs.data?.assignments || [])
    .filter((a) => a.submitted_at)
    .forEach((a) =>
      events.push({ at: sortKey(a.submitted_at), label: fmtDate(a.submitted_at).slice(0, 10), text: "问卷提交：" + a.questionnaire_title, auto: false }),
    );
  (data.first_touch.reports || []).forEach((r) =>
    events.push({ at: ftSortKey(r.confirmedAt), label: fmtFTTime(r.confirmedAt).slice(0, 10), text: "First Touch 报告确认 v" + r.version, auto: false }),
  );
  (sa.profiles.data?.profiles || []).forEach((p) =>
    events.push({ at: sortKey(p.created_at), label: fmtDate(p.created_at).slice(0, 10), text: "6AM 档案 v" + p.version, auto: true }),
  );
  const reviews = sa.six && sa.reviews.data && sa.reviews.data.profile_id === sa.six.profile_id ? sa.reviews.data.reviews || {} : {};
  DIMS.forEach((dim) => {
    const r = reviews[dim];
    if (r && r.verdict) events.push({ at: sortKey(r.created_at), label: fmtDate(r.created_at).slice(0, 10), text: "6AM 团队结论 " + dim, auto: false });
  });
  events.sort((a, b) => b.at - a.at);
  if (events.length === 0) return <Empty>—</Empty>;
  const shown = all ? events : events.slice(0, SHOWN);
  return (
    <div>
      {shown.map((e, i) => (
        <div key={i} className={cn("grid grid-cols-[5.25rem_10px_minmax(0,1fr)] gap-2 py-1.5 text-[13.5px]", e.auto && "text-mute")}>
          <span className="font-mono text-[12.5px] text-mute">{e.label}</span>
          <i className={cn("mt-[7px] block h-[7px] w-[7px]", e.auto ? "bg-line" : "bg-ink")} />
          <span className="min-w-0 break-words">{e.text}</span>
        </div>
      ))}
      {events.length > SHOWN ? (
        <button type="button" className="mt-1 text-[12.5px] font-semibold text-hl hover:underline" onClick={() => setAll((v) => !v)}>
          {all ? "收起" : "展开全部"}
        </button>
      ) : null}
    </div>
  );
}

export default function OverviewTab() {
  const { code, data, setTab } = useProfile();
  const base = "/students/" + encodeURIComponent(code) + "/api/";
  const bookings = useResource<{ bookings: Booking[] }>("bookings", base + "bookings");
  const minutes = useResource<MinutesResp>("minutes", base + "minutes");
  const y4 = useY4Data();
  return (
    <div>
      <Y4SourceStatus />
      <Gate res={y4}>
        {(d) =>
          d.report ? null : (
            <EmptyPanel title="这位学生还没有 Y4 报告">
              <NextAction data={data} onSixAm={() => setTab("six_am")} only={["booking", "y4_report"]} />
            </EmptyPanel>
          )
        }
      </Gate>
      <div className="mb-[22px] grid grid-cols-1 items-start gap-7 lg:grid-cols-2">
        <div className="min-w-0">
          {y4.data ? <Signals y4={y4.data} /> : null}
          <Section title="动态" sub="系统事件已弱化" className="mb-0">
            <Activity bookings={bookings} minutes={minutes} />
          </Section>
        </div>
        <Section
          title="6AM 启动模型"
          className="mb-0"
          right={
            <button type="button" className="text-[12.5px] font-semibold text-hl hover:underline" onClick={() => setTab("six_am")}>
              打开
            </button>
          }
        >
          <SixAmRows />
        </Section>
      </div>
      <Section title="预约记录">
        <Bookings res={bookings} />
      </Section>
      <Section title="解读会纪要">
        <Minutes res={minutes} studentId={data.student.id} />
      </Section>
    </div>
  );
}
