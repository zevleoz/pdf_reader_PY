import * as React from "react";

import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

import {
  DIMS,
  Empty,
  fmtDate,
  fmtFTTime,
  ftSortKey,
  Gate,
  Loading,
  LoadError,
  Section,
  sortKey,
  Tag,
  useProfile,
  useResource,
  type Resource,
} from "./common";
import { dimName, reviewText, useSixAm } from "./SixAmTab";
import type { QResp } from "./QuestionnaireTab";

type Booking = { id: number; appointment_time: string | null; status: string; advisor_name: string; notes: string };
type Minute = { id: number; created_at: string | null; report_date: string | null; preview: string; minutes_text: string };
type MinutesResp = { minutes: Minute[]; restricted?: boolean };
type FileRow = { id: number; report_date: string | null; created_at: string | null };

function bookingTone(s: string): "strong" | "plain" | "alert" {
  if (s === "confirmed" || s === "completed") return "strong";
  if (s === "cancelled") return "alert";
  return "plain";
}

function SixAmStatus() {
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
        return (
          <div key={dim} className="flex flex-wrap items-baseline gap-x-4 gap-y-1 border-t border-line py-3 first:border-t-0">
            <div className="flex min-w-[10rem] items-center gap-2">
              <b>{dim + " " + dimName(model, dim)}</b>
              <Tag tone="soft">{dims[dim]?.level || "—"}</Tag>
            </div>
            <div className="min-w-0 text-sm">{t ? t.head : <span className="text-mute">尚无团队结论</span>}</div>
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
                    <Tag tone={bookingTone(b.status)}>{b.status || "—"}</Tag>
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

type Event = { at: number; label: string; text: string };

function Activity({ bookings, minutes }: { bookings: Resource<{ bookings: Booking[] }>; minutes: Resource<MinutesResp> }) {
  const { data, code } = useProfile();
  const base = "/students/" + encodeURIComponent(code) + "/api/";
  const files = useResource<{ reports: FileRow[] }>("files", base + "reports");
  const qs = useResource<QResp>("questionnaires", base + "questionnaires");
  const sa = useSixAm();
  const all: Resource<unknown>[] = [bookings, minutes, files, qs, sa.profiles, sa.reviews];
  const failed = all.find((r) => r.status === "error");
  if (failed) return <LoadError error={failed.error} onRetry={failed.reload} />;
  if (all.some((r) => r.status !== "ready")) return <Loading />;

  const events: Event[] = [];
  (files.data?.reports || []).forEach((r) =>
    events.push({ at: sortKey(r.report_date), label: r.report_date || "—", text: "Y4 报告 " + (r.report_date || "—") }),
  );
  (bookings.data?.bookings || []).forEach((b) =>
    events.push({ at: sortKey(b.appointment_time), label: fmtDate(b.appointment_time), text: "预约 " + (b.status || "—") }),
  );
  (minutes.data?.minutes || []).forEach((m) =>
    events.push({ at: sortKey(m.created_at), label: fmtDate(m.created_at), text: "解读会纪要" }),
  );
  (qs.data?.assignments || [])
    .filter((a) => a.submitted_at)
    .forEach((a) =>
      events.push({ at: sortKey(a.submitted_at), label: fmtDate(a.submitted_at), text: "问卷提交：" + a.questionnaire_title }),
    );
  (data.first_touch.reports || []).forEach((r) =>
    events.push({ at: ftSortKey(r.confirmedAt), label: fmtFTTime(r.confirmedAt), text: "First Touch 报告确认 v" + r.version }),
  );
  (sa.profiles.data?.profiles || []).forEach((p) =>
    events.push({ at: sortKey(p.created_at), label: fmtDate(p.created_at), text: "6AM 档案 v" + p.version }),
  );
  const reviews = sa.six && sa.reviews.data && sa.reviews.data.profile_id === sa.six.profile_id ? sa.reviews.data.reviews || {} : {};
  DIMS.forEach((dim) => {
    const r = reviews[dim];
    if (r && r.verdict) events.push({ at: sortKey(r.created_at), label: fmtDate(r.created_at), text: "6AM 团队结论 " + dim });
  });
  events.sort((a, b) => b.at - a.at);
  if (events.length === 0) return <Empty>—</Empty>;
  return (
    <ul>
      {events.map((e, i) => (
        <li key={i} className="flex gap-4 border-t border-line py-2 text-sm">
          <span className="w-[10.5rem] shrink-0 font-mono text-mute">{e.label}</span>
          <span className="min-w-0 break-words">{e.text}</span>
        </li>
      ))}
    </ul>
  );
}

export default function OverviewTab() {
  const { code, data } = useProfile();
  const base = "/students/" + encodeURIComponent(code) + "/api/";
  const bookings = useResource<{ bookings: Booking[] }>("bookings", base + "bookings");
  const minutes = useResource<MinutesResp>("minutes", base + "minutes");
  return (
    <div>
      <Section title="6AM 状态">
        <SixAmStatus />
      </Section>
      <Section title="预约记录">
        <Bookings res={bookings} />
      </Section>
      <Section title="解读会纪要">
        <Minutes res={minutes} studentId={data.student.id} />
      </Section>
      <Section title="动态">
        <Activity bookings={bookings} minutes={minutes} />
      </Section>
    </div>
  );
}
