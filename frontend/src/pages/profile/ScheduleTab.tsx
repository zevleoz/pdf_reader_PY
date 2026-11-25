import * as React from "react";
import { Link, useSearchParams } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { errorText, getJSON, postJSON } from "@/lib/api";
import { cn } from "@/lib/utils";

import { Empty, useProfile } from "./common";

type Booking = {
  id: number;
  appointment_date: string;
  appointment_slot: string;
  location_name: string;
  status: string;
  source: string;
  requester_name: string;
  created_by_name: string;
  assessor_id: number | null;
  assessor_name: string;
  can_assign: boolean;
};
type ScheduleResp = {
  bookings: Booking[];
  can_assign: boolean;
  account: { exists: boolean; username: string; is_active: number };
};
type Candidate = {
  id: number;
  display_name: string;
  office_name: string;
  assigned: boolean;
  is_default: boolean;
};

const STATUS: Record<string, string> = {
  pending: "待到访",
  confirmed: "已确认",
  completed: "已完成",
  cancelled: "已取消",
};
const SOURCE: Record<string, string> = {
  internal: "内部代约",
  parent: "家长预约",
  partner: "合作平台预约",
  walk_in: "到店",
  referral: "转介绍",
  other: "其他",
};

export default function ScheduleTab() {
  const { code, data, notify } = useProfile();
  const [params] = useSearchParams();
  const focusId = Number(params.get("booking") || 0);
  const focusRef = React.useRef<HTMLDivElement | null>(null);
  const [body, setBody] = React.useState<ScheduleResp | null>(null);
  const [err, setErr] = React.useState("");
  const [picking, setPicking] = React.useState<number | null>(null);
  const [cands, setCands] = React.useState<Candidate[]>([]);
  const [choice, setChoice] = React.useState("");
  const [busy, setBusy] = React.useState(false);

  const load = React.useCallback(async () => {
    try {
      const r = await getJSON<ScheduleResp>(
        "/api/profiling/students/" + encodeURIComponent(code) + "/schedule",
      );
      setBody(r);
      setErr("");
    } catch (e) {
      setErr(errorText(e, "无法载入预约"));
    }
  }, [code]);

  React.useEffect(() => {
    void load();
  }, [load]);

  React.useEffect(() => {
    if (body && focusId) focusRef.current?.scrollIntoView({ block: "center" });
  }, [body, focusId]);

  async function openCandidates(b: Booking) {
    setPicking(b.id);
    setChoice("");
    try {
      const r = await getJSON<{ candidates: Candidate[] }>(
        "/api/booking/" + b.id + "/assessor-candidates",
      );
      setCands(r.candidates);
      const current = r.candidates.find((c) => c.assigned);
      const preferred = current || r.candidates.find((c) => c.is_default);
      setChoice(preferred ? String(preferred.id) : "");
    } catch (e) {
      setCands([]);
      notify(errorText(e, "无法载入测评师"), "error");
    }
  }

  async function assign(bookingId: number) {
    if (!choice || busy) return;
    setBusy(true);
    try {
      await postJSON("/api/booking/" + bookingId + "/assign", { assessor_id: Number(choice) });
      notify("已分配测评师", "ok");
      setPicking(null);
      await load();
    } catch (e) {
      notify(errorText(e, "分配失败"), "error");
    } finally {
      setBusy(false);
    }
  }

  if (err) return <p className="py-4 text-[13px] text-attention">{err}</p>;
  if (!body) return <p className="py-4 text-[13px] text-mute">正在载入…</p>;
  const account = body.account;

  return (
    <div>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-b border-line pb-2 text-[13px]">
        <span>
          <span className="text-mute">学生账号 </span>
          {account.exists ? (
            <b className="font-mono">{account.username}</b>
          ) : (
            <span className="text-mute">未生成</span>
          )}
        </span>
        <Link className="ml-auto font-semibold underline-offset-2 hover:underline" to="/booking">
          去预约页交接账号
        </Link>
      </div>

      {body.bookings.length === 0 ? (
        <Empty>该学生暂无预约</Empty>
      ) : (
        <div className="mt-1">
          {body.bookings.map((b) => (
            <div
              key={b.id}
              ref={b.id === focusId ? focusRef : undefined}
              className={cn(
                "border-b border-line py-3",
                b.id === focusId && "bg-tint shadow-[-12px_0_0_hsl(var(--tint)),12px_0_0_hsl(var(--tint))]",
              )}
            >
              <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                <b className="text-[15px]">
                  {b.appointment_date} {b.appointment_slot}
                </b>
                <span className="text-[13px] text-ink-2">{b.location_name}</span>
                <span
                  className={cn(
                    "border border-line px-1.5 py-0.5 text-[11.5px]",
                    b.status === "cancelled" ? "text-mute" : "text-ink-2",
                  )}
                >
                  {STATUS[b.status] || b.status}
                </span>
                <span className="ml-auto text-[12.5px] text-mute">
                  {SOURCE[b.source] || b.source || "家长预约"}
                  {b.requester_name ? " · 经办 " + b.requester_name : b.created_by_name ? " · 经办 " + b.created_by_name : ""}
                </span>
              </div>
              <div className="mt-1.5 flex flex-wrap items-center gap-2 text-[13px]">
                <span className="text-mute">测评师</span>
                <b className={b.assessor_name ? "" : "text-mute"}>{b.assessor_name || "未分配"}</b>
                {b.can_assign && b.status !== "cancelled" ? (
                  <Button
                    variant="outline"
                    size="sm"
                    className="ml-auto border-rule shadow-none"
                    onClick={() => void openCandidates(b)}
                  >
                    {b.assessor_id ? "改派" : "分配测评师"}
                  </Button>
                ) : null}
              </div>
              {picking === b.id ? (
                <div className="mt-2 flex flex-wrap items-center gap-2 bg-sunk p-2">
                  <select
                    aria-label="选择测评师"
                    className="h-8 min-w-[220px] border border-line bg-background px-2 text-[13px]"
                    value={choice}
                    onChange={(e) => setChoice(e.target.value)}
                  >
                    <option value="">选择同办公室可约测评师</option>
                    {cands.map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.display_name} · {c.office_name}
                        {c.assigned ? "（当前）" : c.is_default ? "（默认）" : ""}
                      </option>
                    ))}
                  </select>
                  <Button
                    size="sm"
                    className="shadow-none"
                    disabled={!choice || busy}
                    onClick={() => void assign(b.id)}
                  >
                    确认分配
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="shadow-none"
                    onClick={() => setPicking(null)}
                  >
                    取消
                  </Button>
                  {cands.length === 0 ? (
                    <span className="text-[12px] text-mute">
                      该时段暂无同办公室可约测评师；请检查当天排班或改约其他时间
                    </span>
                  ) : null}
                </div>
              ) : null}
            </div>
          ))}
        </div>
      )}
      {!data.permissions.is_admin ? (
        <p className="mt-3 text-[12.5px] text-mute">测评师分配由管理员在档案内完成；测评师可在预约页维护自己的可约时段。</p>
      ) : null}
    </div>
  );
}
