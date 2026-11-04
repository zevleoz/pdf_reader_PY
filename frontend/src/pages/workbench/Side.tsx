import * as React from "react";
import { Link } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { ApiError, getJSON } from "@/lib/api";
import type { NavLink } from "@/lib/boot";
import type { Progress } from "@/lib/progress";
import { stageTitle } from "@/lib/progress";
import { readRecent, type RecentStudent } from "@/lib/recent";
import { cn } from "@/lib/utils";
import { useGoLink } from "@/shell/useGoLink";

import { pad2, weekday, type Job, type Notify, type Upcoming } from "./model";

export function SideTitle({ children, right }: { children: React.ReactNode; right?: React.ReactNode }) {
  return (
    <h2 className="mb-2.5 flex items-center gap-2 border-t-2 border-rule pt-[9px] text-sm font-bold">
      {children}
      {right ? <span className="ml-auto flex gap-1.5">{right}</span> : null}
    </h2>
  );
}

const miniClass = "flex w-full items-center gap-2.5 border-b border-line py-2 text-left hover:[&_b]:underline";

/* ------------------------------------------------------------ 生成作业 */
export function JobCard({ initial, notify }: { initial: Job; notify: Notify }) {
  const [job, setJob] = React.useState<Job>(initial);
  const running = job.running;

  React.useEffect(() => {
    if (!running) return;
    let timer: number | undefined;
    let stopped = false;

    const tick = () => {
      getJSON<{ percent?: number; message?: string; status?: string; filename?: string; error?: string }>("/api/progress")
        .then((d) => {
          if (stopped) return;
          const next: Partial<Job> = { percent: d.percent || 0, message: d.message || "" };
          if (d.status === "done") {
            stopped = true;
            window.clearInterval(timer);
            setJob((j) => ({ ...j, ...next, running: false, status: "done", filename: d.filename || j.filename, ago: "刚刚" }));
            notify("报告已生成：" + (d.filename || ""), "ok");
          } else if (d.status === "error") {
            stopped = true;
            window.clearInterval(timer);
            setJob((j) => ({ ...j, ...next, running: false, status: "error", error: d.error || "", ago: "刚刚" }));
            notify("生成失败：" + (d.error || ""), "error");
          } else {
            setJob((j) => ({ ...j, ...next }));
          }
        })
        .catch(() => {});
    };
    const start = () => {
      window.clearInterval(timer);
      timer = window.setInterval(tick, 3000);
    };
    const onVisibility = () => {
      if (document.hidden) {
        window.clearInterval(timer);
      } else if (!stopped) {
        start();
        tick();
      }
    };
    if (!document.hidden) start();
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      stopped = true;
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [running, notify]);

  return (
    <section aria-label="生成作业">
      <SideTitle
        right={
          running ? (
            <span className="inline-flex h-[22px] items-center bg-s1-bg px-2 text-[12.5px] font-semibold text-s1">进行中</span>
          ) : null
        }
      >
        生成作业
      </SideTitle>
      {running ? (
        <div className="pb-2">
          <div className="text-[30px] font-bold leading-[1.1] tracking-tight">{job.percent + "%"}</div>
          <div className="mt-1 text-sm">{job.message}</div>
          <div className="mt-2 h-1.5 bg-line">
            <div className="h-full bg-ink" style={{ width: job.percent + "%" }} />
          </div>
          <div className="mt-1.5 text-[12.5px] text-mute">{(job.filename ? job.filename + " · " : "") + "每 3 秒自动刷新"}</div>
        </div>
      ) : (
        <div className="pb-2">
          <div className="text-sm text-ink-2">{job.message}</div>
          <div className="mt-1.5 text-[12.5px] text-mute">{(job.filename ? job.filename + " · " : "") + job.ago}</div>
        </div>
      )}
      <Button variant="outline" size="sm" className="mt-1 h-7 rounded-none px-2.5 text-[12.5px] shadow-none" asChild>
        <a href="/generate">前往报告生成</a>
      </Button>
    </section>
  );
}

/* ------------------------------------------------------------ 接下来的预约 */
export function UpcomingList({ rows, bookingsLink }: { rows: Upcoming[]; bookingsLink: NavLink | null }) {
  const go = useGoLink();
  return (
    <section aria-label="接下来的预约">
      <SideTitle
        right={
          bookingsLink ? (
            <button type="button" className="text-[12.5px] font-semibold text-hl hover:underline" onClick={() => go(bookingsLink)}>
              打开日历
            </button>
          ) : null
        }
      >
        接下来的预约
      </SideTitle>
      {rows.length === 0 ? (
        <p className="py-3 text-sm text-mute">暂无待完成的预约</p>
      ) : (
        rows.map((u) => {
          const when = new Date(u.appointment_time);
          const valid = !isNaN(when.getTime());
          const body = (
            <>
              <span className="min-w-0">
                <b className="font-semibold">{u.student_name}</b>
                <small className="block text-[12.5px] leading-[1.3] text-mute">{"顾问 " + u.advisor_name}</small>
              </span>
              <span className="ml-auto whitespace-nowrap text-right text-[13px] font-semibold">
                {valid ? when.getMonth() + 1 + "/" + when.getDate() + " " + weekday(when) : ""}
                <br />
                {valid ? pad2(when.getHours()) + ":" + pad2(when.getMinutes()) : ""}
              </span>
            </>
          );
          return u.student_code ? (
            <Link key={u.booking_id} to={"/students/" + encodeURIComponent(u.student_code)} className={miniClass}>
              {body}
            </Link>
          ) : bookingsLink ? (
            <button key={u.booking_id} type="button" className={miniClass} onClick={() => go(bookingsLink)}>
              {body}
            </button>
          ) : (
            <div key={u.booking_id} className="flex w-full items-center gap-2.5 border-b border-line py-2 text-left">
              {body}
            </div>
          );
        })
      )}
    </section>
  );
}

/* ------------------------------------------------------------ 最近查看 */
function SixSquares({ progress }: { progress: Progress }) {
  return (
    <div className="flex gap-0.5" aria-label={progress.stages.map(stageTitle).join("；")}>
      {progress.stages.map((stage) => (
        <span
          key={stage.key}
          title={stageTitle(stage)}
          className={cn(
            "h-3 w-3",
            stage.state === "done" && "bg-ink",
            stage.state === "todo" && (stage.required ? "border border-ink" : "border border-line"),
            stage.state === "not_used" && "bg-sunk",
          )}
        />
      ))}
    </div>
  );
}

type RecentRow = RecentStudent & { progress: Progress | null };

export function RecentList() {
  const [rows, setRows] = React.useState<RecentRow[] | null>(null);

  React.useEffect(() => {
    let cancelled = false;
    const list = readRecent();
    Promise.all(
      list.map((s) =>
        getJSON<{ progress: Progress }>("/api/profiling/students/" + encodeURIComponent(s.code) + "/progress")
          .then((d): RecentRow | null => ({ ...s, progress: d.progress }))
          .catch((e): RecentRow | null => (e instanceof ApiError && e.status === 404 ? null : { ...s, progress: null })),
      ),
    ).then((all) => {
      if (!cancelled) setRows(all.filter((x): x is RecentRow => x !== null));
    });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <section aria-label="最近查看">
      <SideTitle>最近查看</SideTitle>
      {rows === null ? null : rows.length === 0 ? (
        <p className="py-3 text-sm text-mute">还没有查看过学生档案</p>
      ) : (
        rows.map((s) => (
          <Link key={s.code} to={"/students/" + encodeURIComponent(s.code)} className={miniClass}>
            <span className="min-w-0">
              <b className="font-semibold">{s.name}</b>
              <small className="block font-mono text-[12.5px] leading-[1.3] text-mute">{s.code}</small>
            </span>
            <span className="ml-auto">{s.progress ? <SixSquares progress={s.progress} /> : null}</span>
          </Link>
        ))
      )}
    </section>
  );
}
