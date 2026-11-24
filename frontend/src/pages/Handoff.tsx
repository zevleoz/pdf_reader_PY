import * as React from "react";

import { Button } from "@/components/ui/button";
import { errorText, getJSON } from "@/lib/api";
import { useBoot } from "@/lib/boot";
import PageHeader from "@/shell/PageHeader";

import HandoffPanel, { type HandoffBooking } from "./booking/HandoffPanel";

type Row = Pick<HandoffBooking, "id" | "student_name" | "student_code" | "appointment_slot" |
  "status" | "source_label" | "assessor_name" | "account">;

const STATUS: Record<string, string> = {
  pending: "待到访",
  confirmed: "已确认",
  completed: "已完成",
  cancelled: "已取消",
};

export default function Handoff() {
  const boot = useBoot();
  const [rows, setRows] = React.useState<Row[]>([]);
  const [err, setErr] = React.useState("");
  const [active, setActive] = React.useState<number | null>(null);
  const isFront = boot.user.role === "front";

  React.useEffect(() => {
    let live = true;
    getJSON<{ bookings: Row[] }>("/api/handoff/bookings")
      .then((r) => {
        if (!live) return;
        setRows(r.bookings);
        setActive((cur) => cur ?? (r.bookings[0]?.id || null));
      })
      .catch((e) => live && setErr(errorText(e, "无法载入今日预约")));
    return () => {
      live = false;
    };
  }, []);

  return (
    <div>
      <PageHeader
        title="今日预约"
        sub={isFront ? "只处理本次预约与 Y4 账号交接" : "确认预约信息，把账号交给家长"}
      />
      {err ? <p className="py-4 text-[13px] text-attention">{err}</p> : null}
      <div className="grid gap-6 md:grid-cols-[minmax(0,1fr)_340px]">
        <div>
          {rows.length === 0 && !err ? (
            <p className="border-t-2 border-rule py-6 text-[13.5px] text-mute">今天暂无预约</p>
          ) : null}
          {rows.map((r) => (
            <button
              key={r.id}
              type="button"
              onClick={() => setActive(r.id)}
              className={
                "grid w-full grid-cols-[52px_minmax(0,1fr)_auto] items-center gap-3 border-b border-line py-3 text-left hover:bg-sunk " +
                (active === r.id ? "bg-sunk" : "")
              }
            >
              <b className="font-mono text-[14px]">{r.appointment_slot}</b>
              <span className="min-w-0">
                <b className="block truncate text-[14.5px]">{r.student_name}</b>
                <small className="block truncate text-[12px] text-mute">
                  {r.student_code} · {r.source_label}
                  {r.assessor_name ? " · " + r.assessor_name : " · 未分配测评师"}
                </small>
              </span>
              <span className="flex flex-col items-end gap-1 text-[11.5px] text-mute">
                <span>{STATUS[r.status] || r.status}</span>
                <span>{r.account?.exists ? "已开户" : "待开户"}</span>
              </span>
            </button>
          ))}
        </div>
        <div className="border-t-2 border-rule pt-3 md:sticky md:top-4 md:self-start">
          {active ? (
            <HandoffPanel bookingId={active} showScheduleLink={!isFront} />
          ) : (
            <p className="text-[13px] text-mute">选择一条预约查看交接信息</p>
          )}
          <Button
            variant="ghost"
            size="sm"
            className="mt-3 shadow-none"
            onClick={() => window.location.reload()}
          >
            刷新列表
          </Button>
        </div>
      </div>
    </div>
  );
}
