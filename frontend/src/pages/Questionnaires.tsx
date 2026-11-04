import * as React from "react";
import { Link, useSearchParams } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { deleteJSON, errorText, getJSON, postJSON } from "@/lib/api";
import { useBoot } from "@/lib/boot";
import { cn } from "@/lib/utils";
import { Chip, fieldClass, type ChipTone, type FlagItem } from "@/pages/profile/common";
import PageHeader from "@/shell/PageHeader";

import ResponseDialog, { type ResponseResp, type ResponseView } from "./questionnaires/ResponseDialog";

type Assignment = {
  id: number;
  student_id: number;
  student_code: string;
  student_name: string;
  questionnaire_title: string;
  questionnaire_code: string;
  status: string;
  source: string;
  reason: string;
  delivery: string;
  confirmed_at: string | null;
  expires_at: string;
  flagged: boolean;
};
type OpenFlagRow = { assignment_id: number; student_code: string; student_name: string; questionnaire_title: string; flags: FlagItem[] };
type ListResp = { ok: boolean; assignments: Assignment[]; counts: Record<string, number>; open_flags: OpenFlagRow[] };
type StudentOpt = { id: number; name: string; student_code?: string };
type BankItem = { id: number; title: string; is_active: boolean | number };
type PackageResp = {
  ok: boolean;
  student_name: string;
  student_code?: string;
  questionnaire_title: string;
  delivery: string;
  account?: { username: string } | null;
  login_url: string;
  note?: string;
};
type TextResp = { ok: boolean; text?: string; account?: { created?: boolean } | null };
type Pkg = { title: string; text: string; note: string };
type ConfirmDlg = { title: string; body: string; okText: string; run: () => Promise<void> };

const FILTERS: { key: string; label: string }[] = [
  { key: "pending", label: "待确认" },
  { key: "sent", label: "等待作答" },
  { key: "submitted", label: "已提交" },
  { key: "expired", label: "已过期" },
  { key: "rejected", label: "已驳回" },
  { key: "all", label: "全部" },
];
const DELIVERIES: { key: string; label: string; desc: string }[] = [
  { key: "account", label: "问卷中心账号（推荐）", desc: "学生登录后看到自己所有待完成的问卷" },
  { key: "link", label: "在线链接", desc: "生成一次性作答链接（7 天有效）" },
  { key: "both", label: "两者都发", desc: "链接与账号同时生成" },
];
const STATUS_LABEL: Record<string, string> = {
  pending: "待确认",
  sent: "等待作答",
  submitted: "已提交",
  expired: "已过期",
  rejected: "已驳回",
};
const STATUS_TONE: Record<string, ChipTone> = { pending: "s1", sent: "sn", submitted: "s0", expired: "s2", rejected: "sn" };

function deliveryLabel(d: string | undefined): string {
  return ({ link: "链接", account: "账号", both: "链接 + 账号" } as Record<string, string>)[d || ""] || "—";
}
function sentDays(a: Assignment): number {
  if (!a.confirmed_at) return 0;
  const t = new Date(a.confirmed_at).getTime();
  if (isNaN(t)) return 0;
  return Math.max(0, Math.floor((Date.now() - t) / 86400000));
}
function deliverySub(a: Assignment): string {
  if (a.status !== "sent") return "—";
  let exp = "";
  if (a.expires_at) {
    const dt = new Date(a.expires_at);
    if (!isNaN(dt.getTime())) exp = " · " + (dt.getMonth() + 1) + "月" + dt.getDate() + "日 到期";
  }
  return "已等 " + sentDays(a) + " 天" + exp;
}
function studentLink(code: string): string {
  return "/students/" + encodeURIComponent(code);
}

export default function Questionnaires() {
  const boot = useBoot();
  const canWrite = boot.policy.role !== "viewer";
  const [params, setParams] = useSearchParams();
  const status = FILTERS.some((f) => f.key === params.get("status")) ? (params.get("status") as string) : "pending";

  const [data, setData] = React.useState<ListResp | null>(null);
  const [loadError, setLoadError] = React.useState("");
  const [reload, setReload] = React.useState(0);
  const [busy, setBusy] = React.useState(false);
  const [rowOpen, setRowOpen] = React.useState<number | null>(null);
  const [rowDelivery, setRowDelivery] = React.useState("account");
  const [rowError, setRowError] = React.useState<{ id: number; text: string } | null>(null);
  const [pkg, setPkg] = React.useState<Pkg | null>(null);
  const [resp, setResp] = React.useState<ResponseView | null>(null);
  const [confirmDlg, setConfirmDlg] = React.useState<ConfirmDlg | null>(null);
  const [createOpen, setCreateOpen] = React.useState(false);
  const [students, setStudents] = React.useState<StudentOpt[]>([]);
  const [bank, setBank] = React.useState<BankItem[]>([]);
  const [form, setForm] = React.useState({ student_id: "", questionnaire_id: "", reason: "" });
  const [notice, setNotice] = React.useState<{ text: string; kind: "ok" | "error" } | null>(null);
  const noticeTimer = React.useRef<number | undefined>(undefined);

  const notify = React.useCallback((text: string, kind: "ok" | "error" = "ok") => {
    setNotice({ text, kind });
    window.clearTimeout(noticeTimer.current);
    noticeTimer.current = window.setTimeout(() => setNotice(null), 4000);
  }, []);
  React.useEffect(() => () => window.clearTimeout(noticeTimer.current), []);

  React.useEffect(() => {
    let cancelled = false;
    const url = "/api/questionnaires/assignments" + (status === "all" ? "" : "?status=" + status);
    getJSON<ListResp>(url)
      .then((body) => {
        if (cancelled) return;
        if (!body.ok) throw new Error("加载失败");
        setData(body);
        setLoadError("");
      })
      .catch((e) => {
        if (cancelled) return;
        const text = errorText(e, "加载失败");
        setLoadError(text);
        notify(text, "error");
      });
    return () => {
      cancelled = true;
    };
  }, [status, reload, notify]);

  const refresh = () => setReload((n) => n + 1);
  const rows = data?.assignments || [];
  const counts = data?.counts || {};
  const openFlags = data?.open_flags || [];
  const total = Object.values(counts).reduce((s, n) => s + n, 0);
  const loading = data === null && !loadError;

  function setStatus(key: string) {
    const p = new URLSearchParams(params);
    if (key === "pending") p.delete("status");
    else p.set("status", key);
    setParams(p, { replace: true });
    setRowOpen(null);
    setData(null);
  }
  function countLabel(key: string): string {
    const n = key === "all" ? total : counts[key] || 0;
    return n ? "(" + n + ")" : "";
  }
  const filterLabel = FILTERS.find((f) => f.key === status)?.label || "";
  const emptyTitle =
    status === "pending" ? "没有待确认的任务" : status === "all" ? "暂无任务" : "暂无" + filterLabel + "的任务";

  function toggleRow(id: number) {
    setRowOpen((cur) => (cur === id ? null : id));
    setRowDelivery("account");
    setRowError(null);
  }
  function pendingForStudent(a: Assignment): number {
    return rows.filter((r) => r.student_id === a.student_id && (r.status === "pending" || r.status === "expired")).length;
  }
  function copy(text: string) {
    if (!text) return;
    if (navigator.clipboard) {
      navigator.clipboard.writeText(text).then(
        () => notify("已复制"),
        () => notify("复制失败，请手动选择", "error"),
      );
    } else {
      notify("请手动选择文本复制");
    }
  }

  async function doConfirmInline(a: Assignment) {
    if (busy) return;
    setBusy(true);
    setRowError(null);
    try {
      const d = await postJSON<TextResp>("/api/questionnaires/assignments/" + a.id + "/confirm", { delivery: rowDelivery });
      if (!d.ok) throw new Error("确认失败");
      setRowOpen(null);
      setPkg({ title: "分发信息（请立即复制）", text: d.text || "", note: "仅本次显示，关闭后无法再次查看" });
      notify("已确认并分发");
      refresh();
    } catch (e) {
      const text = errorText(e, "确认失败");
      setRowError({ id: a.id, text });
      notify(text, "error");
    } finally {
      setBusy(false);
    }
  }
  async function sendAll(a: Assignment) {
    if (busy) return;
    setBusy(true);
    setRowError(null);
    try {
      const d = await postJSON<TextResp>("/api/questionnaires/students/" + a.student_id + "/send-all");
      if (!d.ok) throw new Error("发送失败");
      setRowOpen(null);
      setPkg({
        title: "发给学生的登录信息（请立即复制）",
        text: d.text || "",
        note: d.account && d.account.created ? "初始密码仅本次显示，关闭后无法再次查看" : "",
      });
      notify("已发到问卷中心");
      refresh();
    } catch (e) {
      const text = errorText(e, "发送失败");
      setRowError({ id: a.id, text });
      notify(text, "error");
    } finally {
      setBusy(false);
    }
  }
  async function reviewFlag(f: OpenFlagRow) {
    try {
      const d = await postJSON<{ ok: boolean }>("/api/questionnaires/assignments/" + f.assignment_id + "/flag-review");
      if (!d.ok) throw new Error("操作失败");
      notify("已标记跟进");
      refresh();
    } catch (e) {
      notify(errorText(e), "error");
    }
  }
  async function showPackage(a: Assignment) {
    try {
      const d = await getJSON<PackageResp>("/api/questionnaires/assignments/" + a.id + "/package");
      if (!d.ok) throw new Error("操作失败");
      const text =
        "学生：" + d.student_name + "（" + (d.student_code || "—") + "）\n" +
        "问卷：" + d.questionnaire_title + "\n" +
        "分发方式：" + deliveryLabel(d.delivery) + "\n" +
        (d.account ? "账号：" + d.account.username + "\n" : "") +
        "登录地址：" + d.login_url;
      setPkg({ title: "分发信息", text, note: d.note || "" });
    } catch (e) {
      notify(errorText(e), "error");
    }
  }
  async function showResponse(a: Assignment) {
    try {
      const d = await getJSON<ResponseResp>("/api/questionnaires/assignments/" + a.id + "/response");
      if (!d.ok) throw new Error("操作失败");
      setResp({ title: a.student_name + " · " + a.questionnaire_title, data: d });
    } catch (e) {
      notify(errorText(e), "error");
    }
  }
  async function reissue(a: Assignment) {
    try {
      const d = await postJSON<TextResp>("/api/questionnaires/assignments/" + a.id + "/reissue");
      if (!d.ok) throw new Error("操作失败");
      setPkg({ title: "新的作答链接", text: d.text || "", note: "旧链接已作废，仅本次显示新链接" });
      refresh();
    } catch (e) {
      notify(errorText(e), "error");
    }
  }
  function resetPwd(a: Assignment) {
    setConfirmDlg({
      title: "重置密码",
      body: "重置后旧密码立即失效，新密码只显示一次，请复制后再关闭。",
      okText: "重置密码",
      run: async () => {
        try {
          const d = await postJSON<{ ok: boolean; username: string; password: string }>(
            "/api/questionnaires/assignments/" + a.id + "/reset-password",
          );
          if (!d.ok) throw new Error("操作失败");
          setPkg({ title: "新密码", text: "账号：" + d.username + "\n初始密码：" + d.password + "（仅本次显示）", note: "" });
          refresh();
        } catch (e) {
          notify(errorText(e), "error");
        }
      },
    });
  }
  function rejectAsk(a: Assignment) {
    setConfirmDlg({
      title: "驳回任务",
      body: "驳回「" + a.questionnaire_title + " · " + a.student_name + "」？驳回后任务进入已驳回，可重新发起。",
      okText: "确认驳回",
      run: async () => {
        try {
          const d = await postJSON<{ ok: boolean }>("/api/questionnaires/assignments/" + a.id + "/reject");
          if (!d.ok) throw new Error("操作失败");
          if (rowOpen === a.id) setRowOpen(null);
          notify("已驳回");
          refresh();
        } catch (e) {
          notify(errorText(e), "error");
        }
      },
    });
  }
  function deleteAsk(a: Assignment) {
    setConfirmDlg({
      title: "删除问卷任务",
      body:
        "将永久删除「" + a.questionnaire_title + " · " + a.student_name +
        "」的任务、已提交答案或草稿，并使相关作答链接失效。此操作不可撤销。",
      okText: "确认删除",
      run: async () => {
        try {
          const d = await deleteJSON<{ ok: boolean }>("/api/questionnaires/assignments/" + a.id);
          if (!d.ok) throw new Error("删除失败");
          if (rowOpen === a.id) setRowOpen(null);
          setResp(null);
          notify("问卷任务已删除");
          refresh();
        } catch (e) {
          notify(errorText(e, "删除失败"), "error");
        }
      },
    });
  }
  async function runConfirm() {
    const dlg = confirmDlg;
    if (!dlg) return;
    setConfirmDlg(null);
    setBusy(true);
    try {
      await dlg.run();
    } finally {
      setBusy(false);
    }
  }

  async function openCreate() {
    setCreateOpen(true);
    setForm({ student_id: "", questionnaire_id: "", reason: "" });
    try {
      const [s, b] = await Promise.all([
        getJSON<{ students?: StudentOpt[] }>("/api/students"),
        getJSON<{ questionnaires?: BankItem[] }>("/api/questionnaires/bank"),
      ]);
      setStudents(s.students || []);
      setBank((b.questionnaires || []).filter((q) => q.is_active));
    } catch {
      notify("加载选项失败", "error");
    }
  }
  async function doCreate() {
    if (!form.student_id || !form.questionnaire_id) {
      notify("请选择学生与问卷", "error");
      return;
    }
    setBusy(true);
    try {
      const d = await postJSON<{ ok: boolean; created?: boolean }>("/api/questionnaires/assignments", {
        student_id: parseInt(form.student_id, 10),
        questionnaire_id: parseInt(form.questionnaire_id, 10),
        reason: form.reason,
      });
      if (!d.ok) throw new Error("创建失败");
      setCreateOpen(false);
      notify(d.created ? "任务已创建" : "该学生已有此问卷的活动任务，已复用");
      refresh();
    } catch (e) {
      notify(errorText(e, "创建失败"), "error");
    } finally {
      setBusy(false);
    }
  }

  function menuItems(a: Assignment): { label: string; danger?: boolean; run: () => void }[] {
    const out: { label: string; danger?: boolean; run: () => void }[] = [];
    if (a.status === "sent") {
      if (a.delivery !== "account") out.push({ label: "重新生成链接", run: () => void reissue(a) });
      if (a.delivery !== "link") out.push({ label: "重置密码", run: () => resetPwd(a) });
    }
    if (a.status === "pending" || a.status === "sent" || a.status === "expired") {
      out.push({ label: "驳回", danger: true, run: () => rejectAsk(a) });
    }
    out.push({ label: "删除问卷任务", danger: true, run: () => deleteAsk(a) });
    return out;
  }

  return (
    <div>
      <PageHeader
        title="问卷任务"
        sub={data ? (counts.pending || 0) + " 项待确认 · " + (counts.sent || 0) + " 项等待学生" : "加载中…"}
        actions={
          <div className="flex flex-wrap items-center gap-3">
            {canWrite ? <Button onClick={() => void openCreate()}>新建任务</Button> : null}
            <a href="/workspace" className="text-xs text-mute hover:underline">
              旧版工作台
            </a>
          </div>
        }
      />

      {openFlags.length > 0 ? (
        <section className="mb-5 border-t-2 border-rule pt-[9px]" aria-label="需优先关注的作答">
          <div className="mb-2 flex flex-wrap items-baseline gap-x-2">
            <h2 className="text-sm font-bold">需优先关注的作答</h2>
            <small className="text-[12.5px] text-mute">Excel：重视第九题得分情况。跟进后标记</small>
          </div>
          {openFlags.map((f) => (
            <div key={f.assignment_id} className="mb-1 flex flex-wrap items-center gap-2.5 bg-s3-bg px-3.5 py-[11px] text-sm text-s3">
              <div className="min-w-0 flex-1">
                {f.student_code ? (
                  <Link to={studentLink(f.student_code)} className="font-semibold hover:underline">
                    {f.student_name}
                  </Link>
                ) : (
                  <span className="font-semibold">{f.student_name}</span>
                )}{" "}
                <span>{f.questionnaire_title}</span>
                {(f.flags || []).map((x) => (
                  <div key={x.id}>
                    {x.label}：选择「{x.answer}」
                  </div>
                ))}
              </div>
              {canWrite ? (
                <Button variant="outline" size="sm" className="bg-background" onClick={() => void reviewFlag(f)}>
                  标记已跟进
                </Button>
              ) : null}
            </div>
          ))}
        </section>
      ) : null}

      <div className="mb-4 flex flex-wrap items-center gap-2" role="group" aria-label="状态筛选">
        {FILTERS.map((f) => {
          const on = f.key === status;
          return (
            <button
              key={f.key}
              type="button"
              onClick={() => setStatus(f.key)}
              className={cn(
                "h-8 border px-3 text-sm font-semibold transition-colors",
                on ? "border-rule bg-ink text-white" : "border-line bg-background hover:bg-sunk",
              )}
            >
              {f.label} <span className={on ? "text-white" : "text-mute"}>{countLabel(f.key)}</span>
            </button>
          );
        })}
      </div>

      {loadError ? (
        <div className="py-10">
          <p className="mb-3">{loadError}</p>
          <Button
            variant="outline"
            onClick={() => {
              setLoadError("");
              refresh();
            }}
          >
            重试
          </Button>
        </div>
      ) : (
        <div className="overflow-x-auto">
          <Table className="min-w-[860px]">
            <TableHeader>
              <TableRow>
                <TableHead>学生</TableHead>
                <TableHead>问卷</TableHead>
                <TableHead>状态</TableHead>
                <TableHead>分发</TableHead>
                <TableHead className="text-right">操作</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {loading
                ? Array.from({ length: 4 }).map((_, i) => (
                    <TableRow key={i}>
                      <TableCell colSpan={5}>
                        <Skeleton className="h-4 w-64" />
                      </TableCell>
                    </TableRow>
                  ))
                : rows.map((a) => {
                    const expandable = canWrite && (a.status === "pending" || a.status === "expired");
                    const items = canWrite ? menuItems(a) : [];
                    return (
                      <React.Fragment key={a.id}>
                        <TableRow
                          className={cn(expandable && "cursor-pointer", rowOpen === a.id && "bg-sunk")}
                          onClick={() => expandable && toggleRow(a.id)}
                        >
                          <TableCell>
                            {a.student_code ? (
                              <Link
                                to={studentLink(a.student_code)}
                                className="font-semibold hover:underline"
                                onClick={(e) => e.stopPropagation()}
                              >
                                {a.student_name}
                              </Link>
                            ) : (
                              <span className="font-semibold">{a.student_name}</span>
                            )}
                            <div className="font-mono text-xs text-mute">{a.student_code || "—"}</div>
                          </TableCell>
                          <TableCell>
                            <div className="flex items-center gap-2">
                              <span
                                title={a.source === "auto" ? "系统推荐" : "人工创建"}
                                className={cn("inline-block h-2 w-2 shrink-0 border border-rule", a.source === "auto" && "bg-ink")}
                              />
                              <span className="font-semibold">{a.questionnaire_title}</span>
                            </div>
                            <div className="font-mono text-xs text-mute">{a.questionnaire_code}</div>
                            <div className="max-w-[320px] truncate text-xs text-mute" title={a.reason || ""}>
                              {a.reason || ""}
                            </div>
                          </TableCell>
                          <TableCell>
                            <div className="flex flex-col items-start gap-1">
                              <Chip tone={STATUS_TONE[a.status] || "sn"}>{STATUS_LABEL[a.status] || a.status}</Chip>
                              {a.flagged ? <Chip tone="s3">需关注</Chip> : null}
                            </div>
                          </TableCell>
                          <TableCell>
                            <div>{deliveryLabel(a.delivery)}</div>
                            <div className="text-xs text-mute">{deliverySub(a)}</div>
                          </TableCell>
                          <TableCell onClick={(e) => e.stopPropagation()}>
                            <div className="flex items-center justify-end gap-1.5">
                              {expandable ? (
                                <Button size="sm" onClick={() => toggleRow(a.id)}>
                                  {a.status === "expired" ? "重新确认" : "确认分发"}
                                </Button>
                              ) : null}
                              {a.status === "sent" ? (
                                <Button variant="outline" size="sm" onClick={() => void showPackage(a)}>
                                  分发信息
                                </Button>
                              ) : null}
                              {a.status === "submitted" ? (
                                <Button variant="outline" size="sm" onClick={() => void showResponse(a)}>
                                  查看得分
                                </Button>
                              ) : null}
                              {items.length > 0 ? (
                                <DropdownMenu>
                                  <DropdownMenuTrigger asChild>
                                    <Button variant="outline" size="sm" aria-label="更多操作">
                                      ⋯
                                    </Button>
                                  </DropdownMenuTrigger>
                                  <DropdownMenuContent align="end" className="rounded-none shadow-none">
                                    {items.map((it) => (
                                      <DropdownMenuItem
                                        key={it.label}
                                        className={cn("rounded-none", it.danger && "text-attention focus:text-attention")}
                                        onSelect={it.run}
                                      >
                                        {it.label}
                                      </DropdownMenuItem>
                                    ))}
                                  </DropdownMenuContent>
                                </DropdownMenu>
                              ) : null}
                            </div>
                          </TableCell>
                        </TableRow>
                        {rowOpen === a.id ? (
                          <TableRow className="bg-sunk hover:bg-sunk">
                            <TableCell colSpan={5}>
                              <div className="grid gap-5 md:grid-cols-2">
                                <div>
                                  <h5 className="mb-1.5 text-sm font-bold">推荐理由</h5>
                                  <div className="border border-line bg-background p-3 text-sm">
                                    <span>{a.reason || "人工创建，无规则依据。"}</span>
                                    <div className="mt-1.5 text-xs text-mute">
                                      指标实测值见{" "}
                                      {a.student_code ? (
                                        <a
                                          href={"/app" + studentLink(a.student_code)}
                                          target="_blank"
                                          rel="noopener"
                                          className="font-semibold text-hl hover:underline"
                                        >
                                          该生画像页
                                        </a>
                                      ) : (
                                        <span>该生画像页</span>
                                      )}
                                    </div>
                                  </div>
                                </div>
                                <div>
                                  {canWrite ? (
                                    <>
                                      <h5 className="mb-1.5 text-sm font-bold">分发方式</h5>
                                      <div className="grid gap-2" role="radiogroup" aria-label="分发方式">
                                        {DELIVERIES.map((d) => (
                                          <button
                                            key={d.key}
                                            type="button"
                                            role="radio"
                                            aria-checked={rowDelivery === d.key}
                                            onClick={() => setRowDelivery(d.key)}
                                            className={cn(
                                              "border bg-background px-3 py-2 text-left text-sm",
                                              rowDelivery === d.key ? "border-rule" : "border-line hover:bg-sunk",
                                            )}
                                          >
                                            <b className="block">{d.label}</b>
                                            <span className="text-xs text-mute">{d.desc}</span>
                                          </button>
                                        ))}
                                      </div>
                                      <div className="mt-3 flex flex-wrap gap-2">
                                        <Button disabled={busy} onClick={() => void doConfirmInline(a)}>
                                          确认并分发
                                        </Button>
                                        {pendingForStudent(a) > 1 ? (
                                          <Button variant="outline" disabled={busy} onClick={() => void sendAll(a)}>
                                            {"全部发到问卷中心（" + pendingForStudent(a) + " 份）"}
                                          </Button>
                                        ) : null}
                                      </div>
                                      {rowError && rowError.id === a.id ? (
                                        <div className="mt-2 bg-s3-bg px-3 py-2 text-sm text-s3">{rowError.text}</div>
                                      ) : null}
                                    </>
                                  ) : (
                                    <>
                                      <h5 className="mb-1.5 text-sm font-bold">状态</h5>
                                      <div className="border border-line bg-background p-3 text-sm text-mute">
                                        该任务当前状态为「{STATUS_LABEL[a.status] || a.status}」，只读视图无法操作。
                                      </div>
                                    </>
                                  )}
                                </div>
                              </div>
                            </TableCell>
                          </TableRow>
                        ) : null}
                      </React.Fragment>
                    );
                  })}
            </TableBody>
          </Table>
        </div>
      )}

      {data && rows.length === 0 && !loadError ? (
        <div className="py-10 text-center">
          <p className="mb-1 font-semibold">{emptyTitle}</p>
          <p className="text-sm text-mute">报告生成后，命中识别规则的问卷会自动出现在这里。</p>
        </div>
      ) : null}

      <Dialog open={pkg !== null} onOpenChange={(open) => (open ? null : setPkg(null))}>
        <DialogContent className="sm:rounded-none shadow-none">
          <DialogHeader>
            <DialogTitle>{pkg?.title}</DialogTitle>
          </DialogHeader>
          {pkg?.note ? <p className="text-sm text-mute">{pkg.note}</p> : null}
          <pre className="max-h-[50vh] overflow-auto whitespace-pre-wrap break-words border border-line bg-sunk p-3 font-mono text-xs">
            {pkg?.text}
          </pre>
          <DialogFooter className="gap-2 sm:gap-0">
            <Button variant="outline" onClick={() => copy(pkg?.text || "")}>
              复制
            </Button>
            <Button onClick={() => setPkg(null)}>关闭</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <ResponseDialog view={resp} onClose={() => setResp(null)} />

      <Dialog open={confirmDlg !== null} onOpenChange={(open) => (open ? null : setConfirmDlg(null))}>
        <DialogContent className="sm:rounded-none shadow-none">
          <DialogHeader>
            <DialogTitle>{confirmDlg?.title}</DialogTitle>
          </DialogHeader>
          <p className="text-sm">{confirmDlg?.body}</p>
          <DialogFooter className="gap-2 sm:gap-0">
            <Button variant="outline" onClick={() => setConfirmDlg(null)}>
              取消
            </Button>
            <Button onClick={() => void runConfirm()}>{confirmDlg?.okText}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent className="sm:rounded-none shadow-none">
          <DialogHeader>
            <DialogTitle>新建问卷任务</DialogTitle>
          </DialogHeader>
          <div className="grid gap-1.5">
            <Label htmlFor="qt-student">学生</Label>
            <select
              id="qt-student"
              className={cn(fieldClass, "h-9 w-full")}
              value={form.student_id}
              onChange={(e) => setForm((f) => ({ ...f, student_id: e.target.value }))}
            >
              <option value="">请选择学生</option>
              {students.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name + (s.student_code ? " · " + s.student_code : "")}
                </option>
              ))}
            </select>
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor="qt-bank">问卷</Label>
            <select
              id="qt-bank"
              className={cn(fieldClass, "h-9 w-full")}
              value={form.questionnaire_id}
              onChange={(e) => setForm((f) => ({ ...f, questionnaire_id: e.target.value }))}
            >
              <option value="">请选择问卷</option>
              {bank.map((b) => (
                <option key={b.id} value={b.id}>
                  {b.title}
                </option>
              ))}
            </select>
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor="qt-reason">原因（写入档案）</Label>
            <textarea
              id="qt-reason"
              rows={2}
              className={cn(fieldClass, "w-full py-2")}
              placeholder="例如：顾问建议补充主观反馈问卷"
              value={form.reason}
              onChange={(e) => setForm((f) => ({ ...f, reason: e.target.value }))}
            />
          </div>
          <DialogFooter className="gap-2 sm:gap-0">
            <Button variant="outline" onClick={() => setCreateOpen(false)}>
              取消
            </Button>
            <Button disabled={busy} onClick={() => void doCreate()}>
              创建
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

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
