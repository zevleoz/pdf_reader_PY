import * as React from "react";
import { Link, useParams } from "react-router-dom";
import { Pencil } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ApiError, errorText, getJSON, postJSON, putJSON } from "@/lib/api";
import { trackLine, type Progress } from "@/lib/progress";
import { useTab } from "@/lib/useTab";
import { cn } from "@/lib/utils";
import PageHeader from "@/shell/PageHeader";

import { EmptyPanel, ProfileCtx, ResourceCache, type Notify, type OpenFlag, type PageData } from "./profile/common";
import FilesTab from "./profile/FilesTab";
import FirstTouchTab from "./profile/FirstTouchTab";
import { NextBox } from "./profile/NextStep";
import OverviewTab from "./profile/OverviewTab";
import QuestionnaireTab from "./profile/QuestionnaireTab";
import SixAmTab from "./profile/SixAmTab";
import Y4Tab from "./profile/Y4Tab";

const TABS: { key: string; label: string }[] = [
  { key: "overview", label: "概览" },
  { key: "y4", label: "Y4 画像" },
  { key: "questionnaires", label: "问卷" },
  { key: "six_am", label: "6AM" },
  { key: "first_touch", label: "First Touch" },
  { key: "m1", label: "M1" },
  { key: "files", label: "文件" },
];
const TAB_KEYS = TABS.map((t) => t.key);

type LoadState =
  | { status: "loading" }
  | { status: "ready"; data: PageData }
  | { status: "error"; httpStatus: number | null };

/* ------------------------------------------------------------ 顾问 / 学校 行内编辑 */
function MetaField({
  prefix,
  field,
  value,
  editLabel,
  placeholder,
  studentId,
  canWrite,
  onSaved,
  notify,
}: {
  prefix?: string;
  field: "advisor_name" | "school";
  value: string;
  editLabel: string;
  placeholder: string;
  studentId: number;
  canWrite: boolean;
  onSaved: (value: string) => void;
  notify: Notify;
}) {
  const [editing, setEditing] = React.useState(false);
  const [draft, setDraft] = React.useState("");
  const saving = React.useRef(false);

  async function save() {
    if (!editing || saving.current) return;
    saving.current = true;
    try {
      const res = await putJSON<{ ok: boolean; student: Record<string, string> }>("/api/students/" + studentId, {
        [field]: draft.trim(),
      });
      onSaved(res.student[field] ?? draft.trim());
      notify("已保存", "ok");
    } catch (e) {
      notify(errorText(e, "保存失败"), "error");
    } finally {
      saving.current = false;
      setEditing(false);
    }
  }

  return (
    <span className="inline-flex min-w-0 items-center gap-1">
      {prefix ? <span>{prefix}</span> : null}
      {editing ? (
        <Input
          autoFocus
          className="h-7 w-40 rounded-none text-sm"
          value={draft}
          placeholder={placeholder}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              void save();
            } else if (e.key === "Escape") {
              e.preventDefault();
              setEditing(false);
            }
          }}
          onBlur={() => void save()}
        />
      ) : (
        <>
          <span className="min-w-0 break-words">{value || "未填写"}</span>
          {canWrite ? (
            <button
              type="button"
              title={editLabel}
              aria-label={editLabel}
              className="inline-flex h-5 w-5 shrink-0 items-center justify-center text-mute hover:bg-sunk hover:text-ink"
              onClick={() => {
                setDraft(value || "");
                setEditing(true);
              }}
            >
              <Pencil className="h-3 w-3" />
            </button>
          ) : null}
        </>
      )}
    </span>
  );
}

/* ------------------------------------------------------------ 六步进度 */
function Tracker({ progress }: { progress: Progress }) {
  const currentKey = progress.done || !progress.next ? null : progress.next.key;
  return (
    <ol className="grid auto-cols-[104px] grid-flow-col overflow-x-auto md:grid-flow-row md:auto-cols-auto md:grid-cols-6 md:overflow-visible">
      {progress.stages.map((s) => {
        const current = s.key === currentKey;
        return (
          <li
            key={s.key}
            className={cn(
              "min-w-0 border-t-[5px] px-2.5 pb-2 pt-[9px]",
              s.state === "done" ? "border-ink" : current ? "border-hl" : "border-line",
            )}
          >
            <b className={cn("block text-[13.5px] font-bold leading-tight", current && "text-hl")}>{s.label}</b>
            <small className="block text-[12.5px] leading-snug text-mute">{trackLine(s, current)}</small>
          </li>
        );
      })}
    </ol>
  );
}

/* ------------------------------------------------------------ 页面 */
export default function StudentProfile() {
  const params = useParams();
  const code = params.code || "";
  const [tab, setTab] = useTab(TAB_KEYS, "overview");
  const [state, setState] = React.useState<LoadState>({ status: "loading" });
  const [reload, setReload] = React.useState(0);
  const [visited, setVisited] = React.useState<string[]>([tab]);
  const [notice, setNotice] = React.useState<{ text: string; kind: "ok" | "error" } | null>(null);
  const cache = React.useMemo(() => new ResourceCache(), [code]);
  const [y4Dim, setY4Dim] = React.useState("");
  const listRef = React.useRef<HTMLDivElement | null>(null);
  const [ink, setInk] = React.useState<{ left: number; width: number }>({ left: 0, width: 0 });

  const noticeTimer = React.useRef<number | undefined>(undefined);
  const notify: Notify = React.useCallback((text, kind = "ok") => {
    setNotice({ text, kind });
    window.clearTimeout(noticeTimer.current);
    noticeTimer.current = window.setTimeout(() => setNotice(null), 4000);
  }, []);

  React.useEffect(() => () => window.clearTimeout(noticeTimer.current), []);

  React.useEffect(() => {
    setVisited((v) => (v.includes(tab) ? v : [...v, tab]));
  }, [tab]);

  // 标签下的滑动条：量当前标签的位置（标签文字、窗口宽度变化时重新量）
  const flagCountKey = state.status === "ready" ? state.data.questionnaire_flags.length : -1;
  React.useLayoutEffect(() => {
    const measure = () => {
      const el = listRef.current?.querySelector<HTMLElement>('[data-state="active"]');
      if (el) setInk({ left: el.offsetLeft, width: el.offsetWidth });
    };
    measure();
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, [tab, state.status, flagCountKey]);

  React.useEffect(() => {
    let cancelled = false;
    setState({ status: "loading" });
    getJSON<PageData>("/api/profiling/students/" + encodeURIComponent(code))
      .then((data) => {
        if (!cancelled) setState({ status: "ready", data });
      })
      .catch((e) => {
        if (!cancelled) setState({ status: "error", httpStatus: e instanceof ApiError ? e.status : null });
      });
    return () => {
      cancelled = true;
    };
  }, [code, reload]);

  const refreshProgress = React.useCallback(async () => {
    try {
      const res = await getJSON<{ progress: Progress }>("/api/profiling/students/" + encodeURIComponent(code) + "/progress");
      setState((s) => (s.status === "ready" ? { status: "ready", data: { ...s.data, progress: res.progress } } : s));
    } catch {
      // 保留旧进度
    }
  }, [code]);

  const refreshPage = React.useCallback(async () => {
    try {
      const res = await getJSON<PageData>("/api/profiling/students/" + encodeURIComponent(code));
      setState({ status: "ready", data: res });
    } catch {
      // 保留旧数据
    }
  }, [code]);

  if (state.status === "loading") {
    return (
      <div aria-busy="true">
        <Skeleton className="mb-4 h-4 w-24" />
        <Skeleton className="mb-3 h-10 w-64 max-w-full" />
        <Skeleton className="mb-6 h-4 w-80 max-w-full" />
        <Skeleton className="mb-6 h-16 w-full" />
        <Skeleton className="h-40 w-full" />
      </div>
    );
  }

  if (state.status === "error") {
    return (
      <div className="py-10">
        <p className="mb-3">{state.httpStatus === 404 ? "学生不存在" : "无法载入" + (state.httpStatus ? " HTTP " + state.httpStatus : "")}</p>
        <div className="flex gap-2">
          <Button variant="outline" asChild>
            <Link to="/students">← 学生档案</Link>
          </Button>
          {state.httpStatus !== 404 ? (
            <Button variant="outline" onClick={() => setReload((n) => n + 1)}>
              重试
            </Button>
          ) : null}
        </div>
      </div>
    );
  }

  const data = state.data;
  const { student, permissions } = data;
  const setStudent = (patch: Partial<typeof student>) =>
    setState((s) => (s.status === "ready" ? { status: "ready", data: { ...s.data, student: { ...s.data.student, ...patch } } } : s));

  const openFlags = permissions.full ? data.questionnaire_flags : [];
  const flagCount = openFlags.reduce((n, f) => n + (f.flags || []).length, 0);

  const reviewFlag = async (f: OpenFlag) => {
    try {
      const d = await postJSON<{ ok: boolean }>("/api/questionnaires/assignments/" + f.assignment_id + "/flag-review");
      if (!d.ok) throw new Error("操作失败");
      setState((s) =>
        s.status === "ready"
          ? {
              status: "ready",
              data: { ...s.data, questionnaire_flags: s.data.questionnaire_flags.filter((x) => x.assignment_id !== f.assignment_id) },
            }
          : s,
      );
      notify("已标记跟进", "ok");
      cache.invalidate("questionnaires");
    } catch (e) {
      notify(errorText(e), "error");
    }
  };

  const subParts: React.ReactNode[] = [
    <span key="code" className="font-mono">
      {student.code}
    </span>,
    <span key="grade">{student.grade || "未填年级"}</span>,
    <MetaField
      key="school"
      field="school"
      value={student.school}
      editLabel="编辑学校"
      placeholder="学校"
      studentId={student.id}
      canWrite={permissions.can_write}
      onSaved={(v) => setStudent({ school: v })}
      notify={notify}
    />,
    <MetaField
      key="advisor"
      prefix="顾问 "
      field="advisor_name"
      value={student.advisor_name}
      editLabel="编辑顾问"
      placeholder="顾问姓名"
      studentId={student.id}
      canWrite={permissions.can_write}
      onSaved={(v) => setStudent({ advisor_name: v })}
      notify={notify}
    />,
  ];
  if (permissions.full && flagCount > 0) {
    subParts.push(
      <b key="flag" className="font-bold text-attention">
        安全提醒
      </b>,
    );
  }
  const contact = permissions.full
    ? [
        student.gender || null,
        student.birthday ? "生日 " + student.birthday : null,
        student.email ? "邮箱：" + student.email : null,
        student.phone ? "电话：" + student.phone : null,
      ].filter(Boolean)
    : [];
  const linkClass = "text-mute underline-offset-2 hover:underline";

  return (
    <ProfileCtx.Provider value={{ data, code, cache, notify, setTab, refreshProgress, refreshPage, y4Dim, setY4Dim, reviewFlag }}>
      <div>
        <Link to="/students" className="mb-3 inline-block text-sm text-mute hover:underline md:hidden">
          ← 学生档案
        </Link>

        <PageHeader title={student.name} actions={<div className="hidden md:block"><NextBox data={data} onSixAm={() => setTab("six_am")} /></div>} />

        <div className="-mt-3 mb-4 text-sm">
          <p className="flex flex-wrap items-center gap-x-1.5 gap-y-1 text-mute">
            {subParts.map((part, i) => (
              <React.Fragment key={i}>
                {i > 0 ? <span aria-hidden="true">·</span> : null}
                {part}
              </React.Fragment>
            ))}
          </p>
          {contact.length > 0 ? <p className="mt-1 break-all text-mute">{contact.join(" · ")}</p> : null}
          <p className="mt-1 flex flex-wrap gap-x-4 gap-y-1">
            <a className={linkClass} href={"/students/" + encodeURIComponent(student.code)}>
              旧版档案
            </a>
            {permissions.m1_access ? (
              <a className={linkClass} href={"/m1?student=" + student.id}>
                M1
              </a>
            ) : null}
            {permissions.is_admin ? (
              <a className={linkClass} href={"/first-touch/archive/" + student.id}>
                First Touch 归档
              </a>
            ) : null}
          </p>
        </div>

        <div className="mb-4 md:hidden">
          <NextBox data={data} onSixAm={() => setTab("six_am")} phone />
        </div>

        <Tracker progress={data.progress} />

        <Tabs value={tab} onValueChange={setTab}>
          <TabsList
            ref={listRef}
            className="relative mb-[18px] mt-[18px] flex h-auto w-full gap-5 overflow-x-auto"
          >
            {TABS.map((t) => (
              <TabsTrigger
                key={t.key}
                value={t.key}
                className="h-auto px-px py-[9px] text-sm font-medium data-[state=active]:border-transparent data-[state=active]:font-bold"
              >
                {t.label}
                {t.key === "questionnaires" && flagCount > 0 ? <b className="ml-1 font-bold text-attention">{flagCount}</b> : null}
              </TabsTrigger>
            ))}
            <span
              aria-hidden="true"
              className="pointer-events-none absolute bottom-0 h-[3px] bg-hl transition-[left,width] duration-200 ease-out"
              style={{ left: ink.left, width: ink.width }}
            />
          </TabsList>
          {visited.includes("overview") ? (
            <TabsContent value="overview" forceMount className="mt-0 data-[state=inactive]:hidden">
              <OverviewTab />
            </TabsContent>
          ) : null}
          {visited.includes("y4") ? (
            <TabsContent value="y4" forceMount className="mt-0 data-[state=inactive]:hidden">
              <Y4Tab />
            </TabsContent>
          ) : null}
          {visited.includes("questionnaires") ? (
            <TabsContent value="questionnaires" forceMount className="mt-0 data-[state=inactive]:hidden">
              <QuestionnaireTab />
            </TabsContent>
          ) : null}
          {visited.includes("six_am") ? (
            <TabsContent value="six_am" forceMount className="mt-0 data-[state=inactive]:hidden">
              <SixAmTab />
            </TabsContent>
          ) : null}
          {visited.includes("first_touch") ? (
            <TabsContent value="first_touch" forceMount className="mt-0 data-[state=inactive]:hidden">
              <FirstTouchTab />
            </TabsContent>
          ) : null}
          {visited.includes("m1") ? (
            <TabsContent value="m1" forceMount className="mt-0 data-[state=inactive]:hidden">
              <EmptyPanel title="M1 在单独的平台里">
                {permissions.m1_access ? (
                  <Button asChild>
                    <a href={"/m1?student=" + student.id}>打开 M1</a>
                  </Button>
                ) : (
                  <span>当前账号未开通 M1</span>
                )}
              </EmptyPanel>
            </TabsContent>
          ) : null}
          {visited.includes("files") ? (
            <TabsContent value="files" forceMount className="mt-0 data-[state=inactive]:hidden">
              <FilesTab />
            </TabsContent>
          ) : null}
        </Tabs>
      </div>

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
    </ProfileCtx.Provider>
  );
}
