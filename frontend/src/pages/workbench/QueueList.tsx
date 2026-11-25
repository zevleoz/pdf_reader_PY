import * as React from "react";
import { Link } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { errorText, postJSON } from "@/lib/api";
import type { NavLink } from "@/lib/boot";
import { cn } from "@/lib/utils";

import { fmtDate } from "../profile/common";
import { ConfirmDialog, type Pkg } from "./Dialogs";
import type { Notify, PendingAssignment, QueueItem } from "./model";
import { pad2, weekday } from "./model";
import { SideTitle } from "./Side";

const KIND_LABEL: Record<QueueItem["kind"], string> = {
  flag: "安全提醒",
  confirm: "问卷待确认",
  six_am: "6AM",
  first_touch: "First Touch",
  booking: "待预约",
  m1: "心有灵析",
};

/** 左栏按步骤分段；空组隐藏。问卷反馈（flag）排在同组 confirm 之前。 */
const GROUPS: { key: string; label: string; kinds: QueueItem["kind"][] }[] = [
  { key: "questionnaires", label: "补充问卷", kinds: ["flag", "confirm"] },
  { key: "six_am", label: "6AM", kinds: ["six_am"] },
  { key: "first_touch", label: "First Touch", kinds: ["first_touch"] },
  { key: "m1", label: "心有灵析", kinds: ["m1"] },
  { key: "booking", label: "待预约", kinds: ["booking"] },
];

function GroupTitle({ label, count }: { label: string; count: number }) {
  return (
    <h3 className="mt-5 flex items-baseline gap-1.5 border-t-2 border-rule pt-[9px] text-sm font-bold first:mt-0">
      {label}
      <span className="text-[12.5px] font-medium text-mute">· {count}</span>
    </h3>
  );
}

/* ---------------------------------------------------------- 待分配测评师 */
export function AssignList({ rows }: { rows: PendingAssignment[] }) {
  if (rows.length === 0) return null;
  return (
    <section aria-label="待分配测评师" className="mb-6">
      <SideTitle right={<span className="text-[12.5px] font-medium text-mute">· {rows.length}</span>}>
        待分配测评师
      </SideTitle>
      {rows.map((r) => {
        const profile = r.student_code
          ? "/students/" + encodeURIComponent(r.student_code) + "?tab=schedule&booking=" + r.booking_id
          : null;
        const when = new Date(r.appointment_time);
        const valid = !isNaN(when.getTime());
        return (
          <div
            key={r.booking_id}
            className="grid items-center gap-x-3 gap-y-1 border-b border-line py-[11px] md:grid-cols-[minmax(0,1fr)_auto_auto]"
          >
            <div className="min-w-0">
              {profile ? (
                <Link to={profile} className="font-bold hover:underline">
                  {r.student_name || "—"}
                </Link>
              ) : (
                <b>{r.student_name || "—"}</b>
              )}
              <small className="block text-[12.5px] leading-[1.3] text-mute">{r.office_name || "未填办公室"}</small>
            </div>
            <span className="whitespace-nowrap text-[12.5px] text-mute">
              {valid
                ? when.getMonth() + 1 + "/" + when.getDate() + " " + weekday(when) + " " +
                  pad2(when.getHours()) + ":" + pad2(when.getMinutes())
                : ""}
            </span>
            {profile ? (
              <Link to={profile} className="text-[12.5px] font-semibold text-hl hover:underline">
                分配
              </Link>
            ) : null}
          </div>
        );
      })}
    </section>
  );
}

export function itemKey(item: QueueItem): string {
  switch (item.kind) {
    case "flag":
      return "flag-" + item.assignment_id;
    default:
      return item.kind + "-" + item.student.id;
  }
}

function detailOf(item: QueueItem): string {
  switch (item.kind) {
    case "flag": {
      const flagText = item.flags.map((x) => x.label + "：选择「" + x.answer + "」").join("；");
      return item.questionnaire_title + (flagText ? " · " + flagText : "") + " · 提交 " + fmtDate(item.submitted_at);
    }
    case "confirm": {
      const list = item.assignments;
      const head =
        list.length === 1
          ? list[0].questionnaire_title
          : list.length + " 份：" + list.map((a) => a.questionnaire_title).join("、");
      return head + " · 创建 " + fmtDate(item.created_at) + (list.every((a) => a.source === "auto") ? " · 规则推荐" : "");
    }
    case "six_am":
      return item.reviewed === null ? "6AM 档案尚未生成" : item.reviewed + "/5 维已有团队结论";
    case "first_touch":
      return "进行中" + (item.updated_at ? " · 更新 " + fmtDate(item.updated_at) : "");
    case "m1":
      return item.task.owner;
    case "booking":
      return "还没有测评预约";
  }
}

const btnClass = "min-h-10 whitespace-normal rounded-none md:min-h-7 border-line px-2.5 text-[12.5px] font-semibold shadow-none";

export default function QueueList({
  items,
  canWrite,
  full,
  bookingsLink,
  onRemove,
  onPackage,
  notify,
}: {
  items: QueueItem[];
  canWrite: boolean;
  full: boolean;
  bookingsLink: NavLink | null;
  onRemove: (item: QueueItem) => void;
  onPackage: (pkg: Pkg) => void;
  notify: Notify;
}) {
  const [busy, setBusy] = React.useState(false);
  const [confirming, setConfirming] = React.useState<Extract<QueueItem, { kind: "confirm" }> | null>(null);

  async function reviewFlag(item: Extract<QueueItem, { kind: "flag" }>) {
    setBusy(true);
    try {
      const d = await postJSON<{ ok: boolean }>("/api/questionnaires/assignments/" + item.assignment_id + "/flag-review");
      if (!d.ok) throw new Error("操作失败");
      onRemove(item);
      notify("已标记跟进", "ok");
    } catch (e) {
      notify(errorText(e), "error");
    } finally {
      setBusy(false);
    }
  }

  async function confirmOne(item: Extract<QueueItem, { kind: "confirm" }>, delivery: string) {
    setBusy(true);
    try {
      const d = await postJSON<{ ok: boolean; text?: string }>(
        "/api/questionnaires/assignments/" + item.assignments[0].id + "/confirm",
        { delivery },
      );
      if (!d.ok) throw new Error("确认失败");
      setConfirming(null);
      onRemove(item);
      onPackage({ title: "分发信息（请立即复制）", text: d.text || "", note: "仅本次显示，关闭后无法再次查看" });
    } catch (e) {
      notify(errorText(e), "error");
    } finally {
      setBusy(false);
    }
  }

  async function sendAll(item: Extract<QueueItem, { kind: "confirm" }>) {
    setBusy(true);
    try {
      const d = await postJSON<{ ok: boolean; text?: string; account?: { created?: boolean } | null }>(
        "/api/questionnaires/students/" + item.student.id + "/send-all",
      );
      if (!d.ok) throw new Error("发送失败");
      onRemove(item);
      onPackage({
        title: "发给学生的登录信息（请立即复制）",
        text: d.text || "",
        note: d.account?.created ? "初始密码仅本次显示，关闭后无法再次查看" : "",
      });
    } catch (e) {
      notify(errorText(e), "error");
    } finally {
      setBusy(false);
    }
  }

  function actionOf(item: QueueItem): React.ReactNode {
    const profile = "/students/" + encodeURIComponent(item.student.code);
    switch (item.kind) {
      case "flag":
        return canWrite ? (
          <Button size="sm" disabled={busy} className={cn(btnClass, "border-ink bg-ink text-white hover:bg-ink/90")} onClick={() => void reviewFlag(item)}>
            我已跟进
          </Button>
        ) : null;
      case "confirm":
        if (!canWrite) return null;
        return item.assignments.length === 1 ? (
          <Button variant="outline" size="sm" disabled={busy} className={btnClass} onClick={() => setConfirming(item)}>
            确认分发
          </Button>
        ) : (
          <>
            <Link to={profile + "?tab=questionnaires"} className="self-center text-[12.5px] text-mute underline-offset-2 hover:underline">
              逐份确认
            </Link>
            <Button variant="outline" size="sm" disabled={busy} className={btnClass} onClick={() => void sendAll(item)}>
              {"全部发到问卷中心（" + item.assignments.length + " 份）"}
            </Button>
          </>
        );
      case "six_am":
        return canWrite ? (
          <Button variant="outline" size="sm" className={btnClass} asChild>
            <Link to={profile + "?tab=six_am"}>查看 6AM</Link>
          </Button>
        ) : null;
      case "first_touch":
        if (!canWrite) return null;
        return full ? (
          <Button variant="outline" size="sm" className={btnClass} asChild>
            <Link to={"/first-touch/students/" + item.student.id}>继续会谈</Link>
          </Button>
        ) : (
          <Button variant="outline" size="sm" className={btnClass} asChild>
            <Link to={profile + "?tab=first_touch"}>查看会谈进度</Link>
          </Button>
        );
      case "m1":
        return <Button variant="outline" size="sm" className={btnClass} asChild>
          <a href={item.task.href}>{item.task.label}</a>
        </Button>;
      case "booking":
        return canWrite && bookingsLink ? (
          <Button variant="outline" size="sm" className={btnClass} asChild>
            <Link to={"/booking?student=" + encodeURIComponent(item.student.code)}>为该学生找时段</Link>
          </Button>
        ) : null;
    }
  }

  function renderRow(item: QueueItem) {
    const alert = item.kind === "flag";
    return (
      <div
        key={itemKey(item)}
        className={cn(
          "grid items-center gap-x-3 gap-y-1 border-b border-line py-[11px] md:grid-cols-[92px_minmax(0,1fr)_auto]",
          alert && "bg-tint shadow-[-12px_0_0_hsl(var(--tint)),12px_0_0_hsl(var(--tint))]",
        )}
      >
        <span className={cn("text-[12.5px] font-medium text-mute", alert && "font-bold text-hl")}>
          {KIND_LABEL[item.kind]}
        </span>
        <div className="min-w-0">
          <Link to={"/students/" + encodeURIComponent(item.student.code)} className="font-bold hover:underline">
            {item.student.name || "—"}
          </Link>
          <small className="block text-[12.5px] leading-[1.3] text-mute">{detailOf(item)}</small>
        </div>
        <div className="flex flex-wrap gap-1.5 md:justify-end">{actionOf(item)}</div>
      </div>
    );
  }

  return (
    <div>
      {GROUPS.map((g) => {
        const rows = items.filter((i) => g.kinds.includes(i.kind));
        if (rows.length === 0) return null;
        return (
          <section key={g.key} aria-label={g.label}>
            <GroupTitle label={g.label} count={rows.length} />
            {rows.map(renderRow)}
          </section>
        );
      })}
      {confirming ? (
        <ConfirmDialog
          title={confirming.assignments[0].questionnaire_title}
          busy={busy}
          onCancel={() => setConfirming(null)}
          onConfirm={(delivery) => void confirmOne(confirming, delivery)}
        />
      ) : null}
    </div>
  );
}
