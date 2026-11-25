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

import AssessorPanel from "./booking/AssessorPanel";
import { PackageDialog, type Pkg } from "./workbench/Dialogs";
import { weekday, type Notify, type QueueItem, type WorkbenchData, type WorkbenchMode } from "./workbench/model";
import QueueList, { AssignList, itemKey } from "./workbench/QueueList";
import { SideTitle, UpcomingList } from "./workbench/Side";

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
  const [mode, setMode] = React.useState<WorkbenchMode | null>(null);
  const skipModeFetch = React.useRef(false);
  const [reload, setReload] = React.useState(0);
  const [removed, setRemoved] = React.useState<string[]>([]);
  const [pkg, setPkg] = React.useState<Pkg | null>(null);
  const [showAvailability, setShowAvailability] = React.useState(false);
  const [notice, setNotice] = React.useState<{ text: string; kind: "ok" | "error" } | null>(null);
  const noticeTimer = React.useRef<number | undefined>(undefined);
  const notify: Notify = React.useCallback((text, kind = "ok") => {
    setNotice({ text, kind });
    window.clearTimeout(noticeTimer.current);
    noticeTimer.current = window.setTimeout(() => setNotice(null), 4000);
  }, []);
  React.useEffect(() => () => window.clearTimeout(noticeTimer.current), []);

  React.useEffect(() => {
    if (skipModeFetch.current) {
      skipModeFetch.current = false;
      return;
    }
    let cancelled = false;
    setState({ status: "loading" });
    setRemoved([]);
    getJSON<WorkbenchData>("/api/profiling/workbench" + (mode ? "?mode=" + mode : ""))
      .then((data) => {
        if (cancelled) return;
        setState({ status: "ready", data });
        if (mode === null) {
          skipModeFetch.current = true;
          setMode(data.mode);
        }
      })
      .catch(() => {
        if (!cancelled) setState({ status: "error" });
      });
    return () => {
      cancelled = true;
    };
  }, [reload, mode]);

  const today = new Date();
  const todayText = today.getMonth() + 1 + " 月 " + today.getDate() + " 日 " + weekday(today);
  const data = state.status === "ready" ? state.data : null;
  const queue: QueueItem[] = data ? data.queue.filter((i) => !removed.includes(itemKey(i))) : [];
  const pending = data?.pending_assignments ?? [];
  const total = queue.length + pending.length;
  const canWrite = !!data?.permissions.can_write;

  const modeSwitch = data ? (
    data.can_switch ? (
      <div role="group" aria-label="工作台范围" className="inline-flex border border-rule">
        {([["mine", "我的学生"], ["all", "全部事项"]] as [WorkbenchMode, string][]).map(([key, label]) => (
          <button
            key={key}
            type="button"
            aria-pressed={data.mode === key}
            className={cn(
              "min-h-8 px-3 text-[12.5px] font-semibold first:border-r first:border-rule",
              data.mode === key ? "bg-ink text-white" : "text-mute hover:text-ink",
            )}
            onClick={() => {
              if (data.mode !== key) setMode(key);
            }}
          >
            {label}
          </button>
        ))}
      </div>
    ) : (
      <p className="text-[12.5px] text-mute">
        我的学生 · {data.bound_advisor}
      </p>
    )
  ) : null;

  const actions = (
    <div className="flex flex-wrap gap-2">
      {bookingsLink ? (
        <Button variant="outline" className="rounded-none border-rule shadow-none" onClick={() => go(bookingsLink)}>
          <CalendarDays />
          找预约时段
        </Button>
      ) : null}
      {boot.user.is_assessor ? (
        <Button variant="outline" className="rounded-none border-rule shadow-none"
          aria-expanded={showAvailability} onClick={() => setShowAvailability(!showAvailability)}>
          我的可约时段
        </Button>
      ) : null}
      {canWrite ? (
        <>
          <Button variant="outline" className="rounded-none shadow-none" asChild>
            <Link to="/questionnaires?create=1">新建问卷任务</Link>
          </Button>
          <Button className="rounded-none shadow-none" asChild>
            <Link to="/students?action=upload">
              <Upload />
              上传测评报告
            </Link>
          </Button>
        </>
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
        sub={data ? total + " 件事等你处理 · " + todayText : todayText}
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
          <div className="grid grid-cols-1 items-start gap-7 md:grid-cols-[minmax(0,1fr)_270px] lg:grid-cols-[minmax(0,1fr)_320px]">
            <section aria-label="待处理" className="min-w-0">
              {modeSwitch ? <div className="mb-5">{modeSwitch}</div> : null}
              {total === 0 ? (
                <div className="border-t-2 border-rule px-4 py-11 text-center text-mute">
                  <b className="mb-1 block text-base text-ink">
                    {data.mode === "mine" ? "我的学生暂无待办" : "当前范围没有待办"}
                  </b>
                  新的任务会出现在这里。
                </div>
              ) : (
                <>
                  <AssignList rows={pending} />
                  <SideTitle>待处理</SideTitle>
                  {queue.length === 0 ? (
                    <p className="py-4 text-sm text-mute">当前范围内没有其他待办。</p>
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
                </>
              )}
              <div className="mt-3 text-right">
                <Link to="/questionnaires" className="text-[12.5px] font-semibold text-hl hover:underline">
                  全部问卷任务
                </Link>
              </div>
            </section>

            <div className="flex flex-col gap-[26px]">
              <UpcomingList rows={data.upcoming} bookingsLink={bookingsLink} />
            </div>
          </div>
          {showAvailability && boot.user.is_assessor ? (
            <section className="mt-7 border-t-2 border-rule pt-3">
              <AssessorPanel onClose={() => setShowAvailability(false)} />
            </section>
          ) : null}
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
