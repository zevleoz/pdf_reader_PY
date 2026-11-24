import * as React from "react";
import { Link } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { errorText, getJSON, postJSON } from "@/lib/api";
import { cn } from "@/lib/utils";

type Account = { exists: boolean; username: string; is_active?: number; created_at?: string | null };
export type HandoffBooking = {
  id: number;
  student_id: number | null;
  student_name: string;
  student_code: string;
  appointment_date: string;
  appointment_slot: string;
  location_name: string;
  status: string;
  source_label: string;
  requester_name: string;
  assessor_name: string;
  account: Account;
  portal_url: string;
};

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[76px_minmax(0,1fr)] gap-2 border-b border-line py-1.5 text-[13.5px]">
      <span className="text-mute">{label}</span>
      <span className="min-w-0 break-words">{value}</span>
    </div>
  );
}

export default function HandoffPanel({ bookingId, onClose, showScheduleLink = true }: {
  bookingId: number;
  onClose?: () => void;
  showScheduleLink?: boolean;
}) {
  const [booking, setBooking] = React.useState<HandoffBooking | null>(null);
  const [password, setPassword] = React.useState("");
  const [created, setCreated] = React.useState(false);
  const [busy, setBusy] = React.useState(false);
  const [err, setErr] = React.useState("");
  const [notice, setNotice] = React.useState("");

  const load = React.useCallback(async () => {
    try {
      const r = await getJSON<{ booking: HandoffBooking }>("/api/booking/" + bookingId + "/handoff");
      setBooking(r.booking);
      setErr("");
    } catch (e) {
      setErr(errorText(e, "无法载入预约"));
    }
  }, [bookingId]);

  React.useEffect(() => {
    setPassword("");
    setCreated(false);
    setNotice("");
    void load();
  }, [load]);

  async function issue(reset = false) {
    if (busy) return;
    if (reset && !window.confirm("重置后旧密码立即失效，确认继续？")) return;
    setBusy(true);
    setErr("");
    try {
      const r = await postJSON<{ username: string; password: string | null; created: boolean }>(
        "/api/booking/" + bookingId + "/handoff" + (reset ? "/reset" : "/account"),
      );
      setPassword(r.password || "");
      setCreated(r.created);
      setNotice(r.created ? "账号已生成" : reset ? "密码已重置" : "账号已存在，未重置密码");
      await load();
    } catch (e) {
      setErr(errorText(e, "操作失败"));
    } finally {
      setBusy(false);
    }
  }

  async function copyAll() {
    if (!booking) return;
    const lines = [
      "学生：" + booking.student_name + "（" + booking.student_code + "）",
      "预约：" + booking.appointment_date + " " + booking.appointment_slot + " · " + booking.location_name,
      "账号：" + booking.account.username,
      password ? "密码：" + password : "",
      "登录：" + window.location.origin + booking.portal_url,
    ].filter(Boolean);
    try {
      await navigator.clipboard.writeText(lines.join("\n"));
      setNotice("已复制交接信息");
    } catch {
      setErr("浏览器不允许复制，请手动选择");
    }
  }

  if (!booking) {
    return (
      <div>
        <h3 className="text-[17px] font-bold">预约交接</h3>
        {err ? <p className="mt-2 text-[13px] text-attention">{err}</p> : <p className="mt-2 text-[13px] text-mute">正在载入…</p>}
      </div>
    );
  }

  const canReset = booking.account.exists && booking.status !== "cancelled";
  return (
    <div>
      <div className="mb-3 flex items-center gap-2">
        <div>
          <h3 className="text-[17px] font-bold">预约已确认</h3>
          <p className="mt-0.5 text-[12.5px] text-mute">确认预约信息，把 Y4 账号交给家长</p>
        </div>
        {onClose ? (
          <Button variant="ghost" size="sm" className="ml-auto shadow-none" onClick={onClose}>
            关闭
          </Button>
        ) : null}
      </div>

      <div className="mb-3">
        <Row label="学生" value={<b>{booking.student_name}<small className="ml-2 font-normal text-mute">{booking.student_code}</small></b>} />
        <Row label="时间" value={booking.appointment_date + " " + booking.appointment_slot} />
        <Row label="办公室" value={booking.location_name} />
        <Row label="来源" value={booking.source_label + (booking.requester_name ? " · 经办 " + booking.requester_name : "")} />
        <Row label="测评师" value={booking.assessor_name || <span className="text-mute">未分配</span>} />
      </div>

      <div className="border border-line bg-sunk p-3">
        <div className="flex items-center gap-2">
          <b className="text-[13.5px]">Y4 学生账号</b>
          <span className={cn("ml-auto text-[12px]", booking.account.exists ? "text-ink-2" : "text-mute")}>
            {booking.account.exists ? "已生成" : "待生成"}
          </span>
        </div>
        {booking.account.exists ? (
          <p className="mt-1 break-all font-mono text-[14px]">{booking.account.username}</p>
        ) : (
          <p className="mt-1 text-[12.5px] text-mute">生成后用户名会显示在这里；初始密码只显示一次。</p>
        )}
        {password ? (
          <p className="mt-2 break-all bg-background px-2 py-1.5 font-mono text-[14px]">
            {booking.account.username} / {password}
          </p>
        ) : null}
        <div className="mt-2.5 flex flex-wrap gap-2">
          <Button size="sm" className="shadow-none" disabled={busy} onClick={() => void issue(false)}>
            {booking.account.exists ? "查看账号" : "生成 Y4 账号"}
          </Button>
          {canReset ? (
            <Button size="sm" variant="outline" className="border-rule shadow-none" disabled={busy} onClick={() => void issue(true)}>
              重置密码
            </Button>
          ) : null}
          <Button size="sm" variant="outline" className="border-rule shadow-none" onClick={() => void copyAll()}>
            复制交接信息
          </Button>
        </div>
        <p className="mt-2 text-[12px] text-mute">学生入口：{booking.portal_url}</p>
      </div>

      {notice ? <p className="mt-2 text-[13px] text-ink-2">{notice}</p> : null}
      {err ? <p className="mt-2 text-[13px] text-attention">{err}</p> : null}

      {booking.student_code && showScheduleLink ? (
        <Link
          className="mt-3 inline-block text-[13px] font-semibold underline-offset-2 hover:underline"
          to={"/students/" + encodeURIComponent(booking.student_code) + "?tab=schedule"}
        >
          到档案里分配测评师
        </Link>
      ) : null}
    </div>
  );
}
