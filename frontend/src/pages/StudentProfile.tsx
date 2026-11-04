import * as React from "react";
import { Link, useParams } from "react-router-dom";
import { Pencil } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ApiError, errorText, getJSON, postJSON, putJSON } from "@/lib/api";
import { stageState, type Progress } from "@/lib/progress";
import { useTab } from "@/lib/useTab";
import { cn } from "@/lib/utils";
import PageHeader from "@/shell/PageHeader";

import { ProfileCtx, ResourceCache, type Notify, type OpenFlag, type PageData } from "./profile/common";
import FilesTab from "./profile/FilesTab";
import FirstTouchTab from "./profile/FirstTouchTab";
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
  label,
  field,
  value,
  editLabel,
  placeholder,
  studentId,
  canWrite,
  onSaved,
  notify,
}: {
  label: string;
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
    <div className="flex min-w-0 items-center gap-1.5 text-sm">
      <span className="shrink-0 text-mute">{label}</span>
      {editing ? (
        <Input
          autoFocus
          className="h-8 w-40 rounded-none"
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
          <span className={cn("min-w-0 truncate", !value && "text-mute")}>{value || "未填写"}</span>
          {canWrite ? (
            <button
              type="button"
              title={editLabel}
              aria-label={editLabel}
              className="inline-flex h-6 w-6 shrink-0 items-center justify-center border border-line text-mute hover:bg-sunk"
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
    </div>
  );
}

/* ------------------------------------------------------------ 下一步 */
const NEXT_BUTTON: Record<string, { label: string; href: (id: number) => string }> = {
  booking: { label: "去预约", href: () => "/booking" },
  y4_report: { label: "去生成报告", href: () => "/generate" },
  interpretation: { label: "去写会议纪要", href: (id) => "/tools/transcript?student_id=" + id },
};

function NextStep({
  data,
  onSixAm,
}: {
  data: PageData;
  onSixAm: () => void;
}) {
  const { progress, permissions, student, six_am } = data;
  let body: React.ReactNode;
  if (progress.done) {
    const at = (progress.stages.find((s) => s.key === "six_am") || { at: null }).at;
    body = (
      <p className="text-base font-bold">
        Profiling 已完成
        {at ? <span className="ml-2 font-mono text-sm font-normal">{at.slice(0, 10)}</span> : null}
      </p>
    );
  } else {
    const next = progress.next;
    let action: React.ReactNode = null;
    if (next && permissions.can_write) {
      if (next.key === "six_am") {
        action = six_am ? (
          <Button onClick={onSixAm}>记录 6AM 团队结论</Button>
        ) : (
          <>
            <span className="text-sm">6AM 档案尚未生成</span>
            <Button variant="outline" asChild>
              <a href="/insights/six-am">打开 6AM</a>
            </Button>
          </>
        );
      } else if (NEXT_BUTTON[next.key]) {
        const b = NEXT_BUTTON[next.key];
        action = (
          <Button asChild>
            <a href={b.href(student.id)}>{b.label}</a>
          </Button>
        );
      }
    }
    body = (
      <div className="flex flex-wrap items-center gap-3">
        <p className="text-base font-bold">下一步：{next ? next.label : progress.label}</p>
        {action}
      </div>
    );
  }
  return (
    <div className={cn("mb-4 border px-4 py-3", progress.done ? "border-rule" : "border-attention bg-tint")}>{body}</div>
  );
}

/* ------------------------------------------------------------ 六步进度 */
function Tracker({ progress }: { progress: Progress }) {
  return (
    <ol className="mb-6 grid grid-cols-2 border-t-2 border-rule sm:grid-cols-3 lg:grid-cols-6">
      {progress.stages.map((s) => (
        <li key={s.key} className="min-w-0 border-b border-line py-3 pr-3">
          <div className="flex items-center gap-2">
            <span
              aria-hidden="true"
              className={cn(
                "h-3 w-3 shrink-0",
                s.state === "done" && "bg-ink",
                s.state === "todo" && (s.required ? "border border-ink" : "border border-line"),
                s.state === "not_used" && "bg-sunk",
              )}
            />
            <span className={cn("min-w-0 truncate text-sm", s.required ? "font-bold" : "font-medium")}>{s.label}</span>
          </div>
          <div className="mt-1 pl-5 text-xs text-mute">{stageState(s)}</div>
        </li>
      ))}
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

  const sub = [
    student.code,
    student.grade || "未填年级",
    student.gender || null,
    student.birthday ? "生日 " + student.birthday : null,
  ]
    .filter(Boolean)
    .join(" · ");

  async function reviewFlag(f: OpenFlag) {
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
      cache.invalidate("profile", "questionnaires");
    } catch (e) {
      notify(errorText(e), "error");
    }
  }

  return (
    <ProfileCtx.Provider value={{ data, code, cache, notify, setTab, refreshProgress, refreshPage }}>
      <div>
        <Link to="/students" className="mb-3 inline-block text-sm text-mute hover:underline">
          ← 学生档案
        </Link>

        <PageHeader
          title={student.name}
          sub={sub}
          actions={
            <div className="flex flex-wrap gap-2">
              <Button variant="outline" asChild>
                <a href={"/students/" + encodeURIComponent(student.code)}>旧版档案</a>
              </Button>
              {permissions.m1_access ? (
                <Button variant="outline" asChild>
                  <a href={"/m1?student=" + student.id}>M1</a>
                </Button>
              ) : null}
              {permissions.is_admin ? (
                <Button variant="outline" asChild>
                  <a href={"/first-touch/archive/" + student.id}>First Touch 归档</a>
                </Button>
              ) : null}
            </div>
          }
        />

        <div className="mb-4 flex flex-wrap gap-x-6 gap-y-2">
          <MetaField
            label="顾问："
            field="advisor_name"
            value={student.advisor_name}
            editLabel="编辑顾问"
            placeholder="顾问姓名"
            studentId={student.id}
            canWrite={permissions.can_write}
            onSaved={(v) => setStudent({ advisor_name: v })}
            notify={notify}
          />
          <MetaField
            label="学校："
            field="school"
            value={student.school}
            editLabel="编辑学校"
            placeholder="学校"
            studentId={student.id}
            canWrite={permissions.can_write}
            onSaved={(v) => setStudent({ school: v })}
            notify={notify}
          />
          {permissions.full ? (
            <>
              <div className="flex min-w-0 gap-1.5 text-sm">
                <span className="shrink-0 text-mute">邮箱：</span>
                <span className={cn("min-w-0 break-all", !student.email && "text-mute")}>{student.email || "未填写"}</span>
              </div>
              <div className="flex min-w-0 gap-1.5 text-sm">
                <span className="shrink-0 text-mute">电话：</span>
                <span className={cn("min-w-0 font-mono", !student.phone && "text-mute")}>{student.phone || "未填写"}</span>
              </div>
            </>
          ) : null}
        </div>

        {data.questionnaire_flags.map((f) => (
          <div key={f.assignment_id} className="mb-3 flex flex-wrap items-center gap-3 border border-attention bg-tint px-4 py-3">
            <div className="min-w-0 flex-1">
              <div className="font-bold text-attention">需优先关注：{f.questionnaire_title}</div>
              {(f.flags || []).map((x) => (
                <div key={x.id} className="mt-0.5 text-sm">
                  {x.label}：选择「{x.answer}」
                </div>
              ))}
            </div>
            {permissions.can_write ? (
              <Button variant="outline" size="sm" onClick={() => reviewFlag(f)}>
                标记已跟进
              </Button>
            ) : null}
          </div>
        ))}

        <NextStep data={data} onSixAm={() => setTab("six_am")} />
        <Tracker progress={data.progress} />

        <Tabs value={tab} onValueChange={setTab}>
          <div className="overflow-x-auto">
            <TabsList className="w-max min-w-full">
              {TABS.map((t) => (
                <TabsTrigger key={t.key} value={t.key}>
                  {t.label}
                </TabsTrigger>
              ))}
            </TabsList>
          </div>
          {visited.includes("overview") ? (
            <TabsContent value="overview" forceMount className="data-[state=inactive]:hidden">
              <OverviewTab />
            </TabsContent>
          ) : null}
          {visited.includes("y4") ? (
            <TabsContent value="y4" forceMount className="data-[state=inactive]:hidden">
              <Y4Tab />
            </TabsContent>
          ) : null}
          {visited.includes("questionnaires") ? (
            <TabsContent value="questionnaires" forceMount className="data-[state=inactive]:hidden">
              <QuestionnaireTab />
            </TabsContent>
          ) : null}
          {visited.includes("six_am") ? (
            <TabsContent value="six_am" forceMount className="data-[state=inactive]:hidden">
              <SixAmTab />
            </TabsContent>
          ) : null}
          {visited.includes("first_touch") ? (
            <TabsContent value="first_touch" forceMount className="data-[state=inactive]:hidden">
              <FirstTouchTab />
            </TabsContent>
          ) : null}
          {visited.includes("m1") ? (
            <TabsContent value="m1" forceMount className="data-[state=inactive]:hidden">
              {permissions.m1_access ? (
                <Button asChild>
                  <a href={"/m1?student=" + student.id}>打开 M1</a>
                </Button>
              ) : (
                <p className="py-8 text-mute">当前账号未开通 M1</p>
              )}
            </TabsContent>
          ) : null}
          {visited.includes("files") ? (
            <TabsContent value="files" forceMount className="data-[state=inactive]:hidden">
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
