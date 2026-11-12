import * as React from "react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

import type { PageData } from "./common";

const NEXT_BUTTON: Record<string, { label: string; href: (id: number, code: string) => string }> = {
  booking: { label: "去预约", href: (_id, code) => "/app/booking?student=" + encodeURIComponent(code) },
  y4_report: { label: "去生成报告", href: () => "/generate" },
  interpretation: { label: "去写会议纪要", href: (id) => "/tools/transcript?student_id=" + id },
};

/** 下一步的那一个按钮（页头与概览空态共用）。only 限定哪些步骤显示按钮。 */
export function NextAction({ data, onSixAm, only }: { data: PageData; onSixAm: () => void; only?: string[] }) {
  const { progress, permissions, student, six_am } = data;
  const next = progress.done ? null : progress.next;
  if (!next || !permissions.can_write) return null;
  if (only && !only.includes(next.key)) return null;
  if (next.key === "six_am") {
    return six_am ? (
      <Button onClick={onSixAm}>记录 6AM 团队结论</Button>
    ) : (
      <div className="flex flex-wrap items-center gap-2 md:justify-end">
        <span className="text-sm">6AM 档案尚未生成</span>
        <Button variant="outline" asChild>
          <a href="/insights/six-am">打开 6AM</a>
        </Button>
      </div>
    );
  }
  const b = NEXT_BUTTON[next.key];
  if (!b) return null;
  return (
    <Button asChild>
      <a href={b.href(student.id, student.code)}>{b.label}</a>
    </Button>
  );
}

/** 页头右侧的下一步（原型 .ph .nx）。 */
export function NextBox({ data, onSixAm, phone }: { data: PageData; onSixAm: () => void; phone?: boolean }) {
  const { progress } = data;
  if (progress.done) {
    const at = (progress.stages.find((s) => s.key === "six_am") || { at: null }).at;
    return (
      <div className={phone ? "flex flex-wrap items-center gap-x-2.5" : "md:text-right"}>
        <b className={phone ? "text-[15px] font-bold" : "block text-[17px] font-bold leading-tight"}>已完成全部 profiling</b>
        {at ? <small className={cn("font-mono text-[12.5px] text-mute", !phone && "block")}>{at.slice(0, 10)}</small> : null}
      </div>
    );
  }
  const next = progress.next;
  return (
    <div className={phone ? "flex flex-wrap items-center gap-2.5" : "md:text-right"}>
      <small className={cn("text-[12.5px] text-mute", !phone && "block")}>下一步</small>
      <b className={phone ? "text-[15px] font-bold leading-tight" : "mb-2 block text-[17px] font-bold leading-tight"}>
        {next ? next.label : progress.label}
      </b>
      <div className={phone ? "ml-auto" : undefined}>
        <NextAction data={data} onSixAm={onSixAm} />
      </div>
    </div>
  );
}
