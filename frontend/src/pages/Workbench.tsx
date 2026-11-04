import * as React from "react";
import { Link } from "react-router-dom";
import { CalendarDays, Upload } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { getJSON } from "@/lib/api";
import { useBoot, type NavLink } from "@/lib/boot";
import { cn } from "@/lib/utils";
import PageHeader from "@/shell/PageHeader";
import { useGoLink } from "@/shell/useGoLink";

import { PackageDialog, type Pkg } from "./workbench/Dialogs";
import { weekday, type Notify, type QueueItem, type WorkbenchData } from "./workbench/model";
import QueueList, { itemKey } from "./workbench/QueueList";
import { JobCard, RecentList, SideTitle, UpcomingList } from "./workbench/Side";

const STRIP: { key: keyof WorkbenchData["counts"]; label: string }[] = [
  { key: "booking", label: "预约" },
  { key: "y4_report", label: "Y4 报告" },
  { key: "interpretation", label: "解读会" },
  { key: "six_am", label: "6AM" },
  { key: "done", label: "已完成" },
];

function findLink(groups: { links: NavLink[] }[], key: string): NavLink | null {
  for (const g of groups) {
    const hit = g.links.find((l) => l.key === key);
    if (hit) return hit;
  }
  return null;
}

type LoadState = { status: "loading" } | { status: "error" } | { status: "ready"; data: WorkbenchData };

export default function Workbench() {
  const boot = useBoot();
  const go = useGoLink();
  const bookingsLink = React.useMemo(() => findLink(boot.nav, "tools.bookings"), [boot.nav]);
  const [state, setState] = React.useState<LoadState>({ status: "loading" });
  const [reload, setReload] = React.useState(0);
  const [removed, setRemoved] = React.useState<string[]>([]);
  const [pkg, setPkg] = React.useState<Pkg | null>(null);
  const [notice, setNotice] = React.useState<{ text: string; kind: "ok" | "error" } | null>(null);
  const noticeTimer = React.useRef<number | undefined>(undefined);
  const notify: Notify = React.useCallback((text, kind = "ok") => {
    setNotice({ text, kind });
    window.clearTimeout(noticeTimer.current);
    noticeTimer.current = window.setTimeout(() => setNotice(null), 4000);
  }, []);
  React.useEffect(() => () => window.clearTimeout(noticeTimer.current), []);

  React.useEffect(() => {
    let cancelled = false;
    setState({ status: "loading" });
    setRemoved([]);
    getJSON<WorkbenchData>("/api/profiling/workbench")
      .then((data) => {
        if (!cancelled) setState({ status: "ready", data });
      })
      .catch(() => {
        if (!cancelled) setState({ status: "error" });
      });
    return () => {
      cancelled = true;
    };
  }, [reload]);

  const today = new Date();
  const todayText = today.getMonth() + 1 + " 月 " + today.getDate() + " 日 " + weekday(today);
  const data = state.status === "ready" ? state.data : null;
  const queue: QueueItem[] = data ? data.queue.filter((i) => !removed.includes(itemKey(i))) : [];
  const canWrite = !!data?.permissions.can_write;

  const actions = (
    <div className="flex flex-wrap gap-2">
      {bookingsLink ? (
        <Button variant="outline" className="rounded-none border-rule shadow-none" onClick={() => go(bookingsLink)}>
          <CalendarDays />
          找预约时段
        </Button>
      ) : null}
      {canWrite ? (
        <Button className="rounded-none shadow-none" asChild>
          <a href="/generate">
            <Upload />
            上传测评报告
          </a>
        </Button>
      ) : null}
      <a href="/workspace" className="self-center text-[13px] text-mute underline-offset-2 hover:underline">
        旧版工作台
      </a>
    </div>
  );

  return (
    <div>
      <PageHeader
        title="工作台"
        sub={data ? queue.length + " 件事等你处理 · " + todayText : todayText}
        actions={data ? actions : undefined}
      />

      {state.status === "error" ? (
        <div className="py-10">
          <p className="mb-3">无法载入</p>
          <Button variant="outline" onClick={() => setReload((n) => n + 1)}>
            重试
          </Button>
        </div>
      ) : !data ? (
        <div aria-busy="true" className="grid gap-3">
          <Skeleton className="h-16 w-full" />
          <Skeleton className="h-40 w-full" />
        </div>
      ) : (
        <>
          <div className="mb-[26px] grid auto-cols-[92px] grid-flow-col overflow-x-auto border-t-2 border-rule md:auto-cols-auto md:grid-flow-row md:grid-cols-5 md:overflow-visible">
            {STRIP.map((cell, i) => (
              <Link
                key={cell.key}
                to={"/students?stage=" + cell.key}
                className={cn("px-3 pb-3 pt-2.5 text-left transition-colors hover:bg-sunk", i > 0 && "border-l border-line")}
              >
                <b className="block text-[30px] font-bold leading-[1.1] tracking-tight">{data.counts[cell.key]}</b>
                <small className="text-[12.5px] text-ink-2">{cell.label}</small>
              </Link>
            ))}
          </div>

          <div className="grid grid-cols-1 items-start gap-7 md:grid-cols-[minmax(0,1fr)_270px] lg:grid-cols-[minmax(0,1fr)_320px]">
            <section aria-label="待处理" className="min-w-0">
              <SideTitle>
                待处理<small className="text-[12.5px] font-normal text-mute">最紧急的在最上面</small>
              </SideTitle>
              {queue.length === 0 ? (
                <div className="px-4 py-11 text-center text-mute">
                  <b className="mb-1 block text-base text-ink">今天的事都处理完了</b>
                  新的任务会出现在这里。
                </div>
              ) : (
                <QueueList
                  items={queue}
                  canWrite={canWrite}
                  full={data.permissions.full}
                  bookingsLink={bookingsLink}
                  onRemove={(item) => setRemoved((r) => [...r, itemKey(item)])}
                  onPackage={setPkg}
                  notify={notify}
                />
              )}
              <div className="mt-3 text-right">
                <Link to="/questionnaires" className="text-[12.5px] font-semibold text-hl hover:underline">
                  全部问卷任务
                </Link>
              </div>
            </section>

            <div className="flex flex-col gap-[26px]">
              {data.job ? <JobCard initial={data.job} notify={notify} /> : null}
              <UpcomingList rows={data.upcoming} bookingsLink={bookingsLink} />
              <RecentList />
            </div>
          </div>
        </>
      )}

      {pkg ? <PackageDialog pkg={pkg} onClose={() => setPkg(null)} notify={notify} /> : null}
      {notice ? (
        <div
          role="status"
          className={cn(
            "fixed bottom-4 left-4 right-4 z-[60] border bg-background px-4 py-3 text-sm sm:left-auto sm:max-w-sm",
            notice.kind === "error" ? "border-attention text-attention" : "border-rule",
          )}
        >
          {notice.text}
        </div>
      ) : null}
    </div>
  );
}
