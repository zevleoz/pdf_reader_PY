import * as React from "react";
import { RefreshCw } from "lucide-react";
import { Link } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { errorText, getJSON, postJSON } from "@/lib/api";
import { useBoot } from "@/lib/boot";
import { cn } from "@/lib/utils";
import { Chip } from "@/pages/profile/common";
import PageHeader from "@/shell/PageHeader";

type Question = {
  id?: string | number;
  title?: string;
  section?: string;
  dimension?: string;
};

type Section = { id?: string; title?: string };

type Schema = {
  questions?: Question[];
  sections?: Section[];
};

type BankItem = {
  id: number;
  title: string;
  description?: string;
  code: string;
  is_active: number | boolean;
  schema?: Schema;
};

type BankResp = { ok: boolean; error?: string; questionnaires?: BankItem[] };
type ToggleResp = { ok: boolean; error?: string; is_active: number | boolean };
type QuestionGroup = { title: string; items: Question[] };

const SEED_NOTE = "题库内容固定，此页仅支持启用或停用；停用后不再创建新的问卷任务";

function isActive(value: number | boolean): boolean {
  return value === true || value === 1;
}

function questionsOf(schema: Schema | undefined): Question[] {
  return schema && Array.isArray(schema.questions) ? schema.questions : [];
}

/** 题目按 sections 顺序分组；对不上分段的题目统一收进「其他题目」。 */
function groupQuestions(schema: Schema | undefined): QuestionGroup[] {
  const questions = questionsOf(schema);
  const sections = schema && Array.isArray(schema.sections) ? schema.sections : [];
  if (!sections.length) return [{ title: "题目", items: questions }];

  const groups: QuestionGroup[] = sections.map((section) => ({
    title: section.title || section.id || "题目",
    items: questions.filter((question) => question.section === section.id),
  }));
  const orphans = questions.filter(
    (question) => !question.section || !sections.some((section) => section.id === question.section),
  );
  if (orphans.length) groups.push({ title: "其他题目", items: orphans });
  return groups;
}

export default function QuestionnaireBank() {
  const boot = useBoot();
  const role = boot.policy.role;
  const allowed = role === "admin" || role === "advisor";
  const isAdmin = role === "admin";

  const [rows, setRows] = React.useState<BankItem[] | null>(null);
  const [loading, setLoading] = React.useState(allowed);
  const [loadError, setLoadError] = React.useState("");
  const [actionError, setActionError] = React.useState("");
  const [expandedId, setExpandedId] = React.useState<number | null>(null);
  const [busyId, setBusyId] = React.useState<number | null>(null);
  const [reload, setReload] = React.useState(0);
  const [notice, setNotice] = React.useState<{ text: string; kind: "ok" | "error" } | null>(null);
  const noticeTimer = React.useRef<number | undefined>(undefined);
  const toggleRefs = React.useRef(new Map<number, HTMLButtonElement | null>());

  const notify = React.useCallback((text: string, kind: "ok" | "error" = "ok") => {
    setNotice({ text, kind });
    window.clearTimeout(noticeTimer.current);
    noticeTimer.current = window.setTimeout(() => setNotice(null), 4000);
  }, []);
  React.useEffect(() => () => window.clearTimeout(noticeTimer.current), []);

  React.useEffect(() => {
    if (!allowed) return;
    let cancelled = false;
    setLoading(true);
    setLoadError("");
    setExpandedId(null);
    getJSON<BankResp>("/api/questionnaires/bank?with_schema=1")
      .then((body) => {
        if (cancelled) return;
        if (!body.ok) throw new Error(body.error || "加载失败");
        setRows(body.questionnaires || []);
      })
      .catch((error) => {
        if (cancelled) return;
        setLoadError(errorText(error, "加载失败"));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [allowed, reload]);

  function refresh() {
    setActionError("");
    setExpandedId(null);
    setReload((n) => n + 1);
  }

  function closePreview(id: number) {
    setExpandedId(null);
    window.requestAnimationFrame(() => toggleRefs.current.get(id)?.focus());
  }

  async function toggleActive(item: BankItem) {
    if (busyId !== null) return;
    setBusyId(item.id);
    setActionError("");
    try {
      const body = await postJSON<ToggleResp>("/api/questionnaires/bank/" + item.id + "/toggle", {
        active: !isActive(item.is_active),
      });
      if (!body.ok) throw new Error(body.error || "操作失败");
      const next = isActive(body.is_active);
      setRows((current) =>
        (current || []).map((row) => (row.id === item.id ? { ...row, is_active: next ? 1 : 0 } : row)),
      );
      notify(next ? "已启用" : "已停用");
    } catch (error) {
      const text = errorText(error, "操作失败");
      setActionError(text);
      notify(text, "error");
    } finally {
      setBusyId(null);
    }
  }

  if (!allowed) {
    return (
      <div>
        <PageHeader title="问卷题库" sub={SEED_NOTE} />
        <div className="border-t-2 border-rule pt-7">
          <h2 className="text-lg font-bold">无权访问</h2>
          <p className="mt-2 max-w-[52ch] text-sm text-mute">
            问卷题库仅对管理员与顾问开放。当前账号无法查看题库内容。
          </p>
          <Link to="/workbench" className="mt-4 inline-block text-sm font-semibold underline underline-offset-4">
            返回工作台
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div>
      <PageHeader
        title="问卷题库"
        sub={SEED_NOTE}
        actions={
          <div className="flex flex-wrap items-center gap-3">
            <Button
              variant="outline"
              size="sm"
              onClick={refresh}
              disabled={loading || busyId !== null}
            >
              <RefreshCw aria-hidden />
              刷新
            </Button>
            <a href="/questionnaires/bank" className="text-xs text-mute hover:underline">
              旧版题库
            </a>
          </div>
        }
      />

      {loadError ? (
        <div className="border-t-2 border-rule pt-6">
          <p role="alert" className="text-sm">
            {loadError}
          </p>
          <Button variant="outline" className="mt-3" onClick={refresh} disabled={loading}>
            重试
          </Button>
        </div>
      ) : loading && rows === null ? (
        <div className="border-t-2 border-rule pt-3" aria-busy="true" aria-label="正在加载题库">
          {Array.from({ length: 3 }).map((_, index) => (
            <Skeleton key={index} className="mb-2 h-12 w-full" />
          ))}
        </div>
      ) : rows && rows.length === 0 ? (
        <div className="border-t-2 border-rule px-4 py-11 text-center text-mute">
          <b className="mb-1 block text-base text-ink">暂无问卷</b>
          <p>题库为空。请联系管理员导入问卷后刷新。</p>
        </div>
      ) : rows ? (
        <div>
          {loading ? (
            <p role="status" className="mb-2 text-xs text-mute">
              正在刷新题库…
            </p>
          ) : null}
          {actionError ? (
            <div role="alert" className="mb-3 border border-attention px-3 py-2 text-sm text-attention">
              {actionError}
            </div>
          ) : null}
          <ul className="border-t-2 border-rule">
            {rows.map((item) => {
              const count = questionsOf(item.schema).length;
              const open = expandedId === item.id;
              const active = isActive(item.is_active);
              const groups = open ? groupQuestions(item.schema) : [];
              const previewId = "qb-preview-" + item.id;
              return (
                <li key={item.id} className={cn("border-b border-line", open && "bg-sunk")}>
                  <div className="grid gap-3 px-1 py-3 md:grid-cols-[minmax(0,1fr)_auto] md:items-start md:gap-6">
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-baseline gap-x-2.5 gap-y-1">
                        <h2 className="break-words text-sm font-semibold">{item.title}</h2>
                        <span className="font-mono text-xs text-mute">{item.code}</span>
                        <span className="text-xs text-mute">{count} 题</span>
                        <Chip tone={active ? "s0" : "sn"}>{active ? "启用" : "停用"}</Chip>
                      </div>
                      <p className="mt-1 max-w-[72ch] break-words text-[12.5px] text-mute">
                        {item.description || "—"}
                      </p>
                    </div>
                    <div className="flex flex-wrap items-center gap-2 md:justify-end">
                      <Button
                        ref={(node) => {
                          toggleRefs.current.set(item.id, node);
                        }}
                        variant="outline"
                        size="sm"
                        aria-expanded={open}
                        aria-controls={previewId}
                        onClick={() => setExpandedId((current) => (current === item.id ? null : item.id))}
                      >
                        {open ? "收起题目" : "查看题目"}
                      </Button>
                      {isAdmin ? (
                        <Button
                          variant="outline"
                          size="sm"
                          className={cn(active && "text-attention hover:text-attention")}
                          disabled={busyId !== null || loading}
                          onClick={() => void toggleActive(item)}
                        >
                          {busyId === item.id ? "处理中…" : active ? "停用" : "启用"}
                        </Button>
                      ) : null}
                    </div>
                  </div>

                  {open ? (
                    <div
                      id={previewId}
                      role="region"
                      aria-label={"问卷题目 · " + item.title}
                      className="px-1 pb-4"
                      onKeyDown={(event) => {
                        if (event.key === "Escape") closePreview(item.id);
                      }}
                    >
                      <div className="border border-line bg-background px-3 py-3 md:px-4">
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <p className="break-words text-[12.5px] font-semibold">
                            {"问卷题目 · " + item.title + "（" + count + " 题）"}
                          </p>
                          <Button variant="outline" size="sm" onClick={() => closePreview(item.id)}>
                            收起
                          </Button>
                        </div>

                        {count === 0 ? (
                          <p className="mt-2 text-sm text-mute">该问卷没有题目数据。</p>
                        ) : (
                          <div className="mt-2 max-h-[420px] overflow-y-auto pr-1">
                            {groups.map((group, groupIndex) => (
                              <div key={groupIndex} className={cn(groupIndex > 0 && "mt-3")}>
                                <h3 className="text-[11px] font-semibold tracking-wide text-mute">
                                  {group.title}
                                </h3>
                                {group.items.length ? (
                                  <ul className="mt-1">
                                    {group.items.map((question, questionIndex) => (
                                      <li
                                        key={String(question.id ?? questionIndex) + "-" + questionIndex}
                                        className="flex gap-2.5 border-b border-line py-1.5 text-[13px] last:border-0"
                                      >
                                        <span className="min-w-[2.5rem] shrink-0 text-right font-mono text-[11.5px] text-mute">
                                          {question.id ?? "—"}
                                        </span>
                                        <span className="min-w-0 break-words text-ink-2">
                                          {question.title || "—"}
                                          {question.dimension ? (
                                            <span className="ml-1.5 text-[12px] text-mute">
                                              [{question.dimension}]
                                            </span>
                                          ) : null}
                                        </span>
                                      </li>
                                    ))}
                                  </ul>
                                ) : (
                                  <p className="py-1 text-xs text-mute">本段暂无题目</p>
                                )}
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    </div>
                  ) : null}
                </li>
              );
            })}
          </ul>
        </div>
      ) : null}

      {notice ? (
        <div
          role={notice.kind === "error" ? "alert" : "status"}
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
