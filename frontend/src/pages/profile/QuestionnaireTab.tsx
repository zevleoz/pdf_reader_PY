import * as React from "react";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { errorText, getJSON, postJSON } from "@/lib/api";
import { cn } from "@/lib/utils";

import { Chip, Empty, fieldClass, fmtDate, Gate, Q_LABEL, useProfile, useResource, type ChipTone, type ScoreSet } from "./common";
import ScoreTable from "./ScoreTable";

export type Assignment = {
  id: number;
  questionnaire_title: string;
  questionnaire_code: string;
  status: string;
  source: string;
  reason: string;
  created_at: string | null;
  submitted_at: string | null;
  answers: Record<string, unknown> | null;
  scores: ScoreSet | null;
};
export type QResp = { enabled: boolean; restricted?: boolean; assignments: Assignment[] };
type BankItem = { id: number; title: string; is_active: boolean | number };
type PackageResp = {
  ok: boolean;
  student_name?: string;
  student_code?: string;
  questionnaire_title?: string;
  account?: { username: string } | null;
  login_url?: string;
  note?: string;
};
type ReissueResp = { ok: boolean; text?: string };

function fmtAns(v: unknown): string {
  if (Array.isArray(v)) return v.join("、");
  if (v && typeof v === "object") return JSON.stringify(v);
  return v === null || v === undefined || v === "" ? "（未作答）" : String(v);
}

const Q_TONE: Record<string, ChipTone> = { pending: "s1", sent: "sn", submitted: "s0", expired: "s2", rejected: "sn" };

const DELIVERIES: { key: string; label: string; desc: string }[] = [
  { key: "account", label: "问卷中心账号（推荐）", desc: "学生登录后看到自己所有待完成的问卷" },
  { key: "link", label: "在线链接", desc: "生成一次性作答链接（7 天有效）" },
  { key: "both", label: "两者都发", desc: "链接与账号同时生成" },
];

type Pkg = { title: string; text: string; note: string };

export default function QuestionnaireTab() {
  const { code, data, cache, notify, reviewFlag } = useProfile();
  const { can_write } = data.permissions;
  const res = useResource<QResp>("questionnaires", "/students/" + encodeURIComponent(code) + "/api/questionnaires");
  const [openAns, setOpenAns] = React.useState<Record<number, boolean>>({});
  const [pkg, setPkg] = React.useState<Pkg | null>(null);
  const [createOpen, setCreateOpen] = React.useState(false);
  const [bank, setBank] = React.useState<BankItem[]>([]);
  const [qid, setQid] = React.useState("");
  const [reason, setReason] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [confirmFor, setConfirmFor] = React.useState<Assignment | null>(null);
  const [delivery, setDelivery] = React.useState("account");

  async function showPackage(aid: number) {
    try {
      const d = await getJSON<PackageResp>("/api/questionnaires/assignments/" + aid + "/package");
      if (!d.ok) throw new Error("操作失败");
      setPkg({
        title: "分发信息",
        text:
          "学生：" + (d.student_name || "") + "（" + (d.student_code || "—") + "）\n" +
          "问卷：" + (d.questionnaire_title || "") + "\n" +
          (d.account ? "账号：" + d.account.username + "\n" : "") +
          "登录地址：" + d.login_url,
        note: d.note || "链接仅本次显示，关闭后无法再次查看",
      });
    } catch (e) {
      notify(errorText(e), "error");
    }
  }

  async function reissue(aid: number) {
    try {
      const d = await postJSON<ReissueResp>("/api/questionnaires/assignments/" + aid + "/reissue");
      if (!d.ok) throw new Error("重新生成失败");
      setPkg({ title: "新的作答链接", text: d.text || "", note: "旧链接已作废，仅本次显示新链接" });
      notify("已重新生成链接", "ok");
      cache.invalidate("questionnaires");
    } catch (e) {
      notify(errorText(e), "error");
    }
  }

  async function reject(aid: number) {
    try {
      const d = await postJSON<{ ok: boolean }>("/api/questionnaires/assignments/" + aid + "/reject");
      if (!d.ok) throw new Error("操作失败");
      cache.invalidate("questionnaires");
    } catch (e) {
      notify(errorText(e), "error");
    }
  }

  async function doConfirm() {
    if (!confirmFor) return;
    setBusy(true);
    try {
      const d = await postJSON<{ ok: boolean; text?: string }>("/api/questionnaires/assignments/" + confirmFor.id + "/confirm", {
        delivery,
      });
      if (!d.ok) throw new Error("确认失败");
      setConfirmFor(null);
      setPkg({ title: "分发信息", text: d.text || "", note: "仅本次显示，关闭后无法再次查看" });
      notify("已确认并分发", "ok");
      cache.invalidate("questionnaires");
    } catch (e) {
      notify(errorText(e), "error");
    } finally {
      setBusy(false);
    }
  }

  async function openCreate() {
    setCreateOpen(true);
    setQid("");
    setReason("");
    try {
      const d = await getJSON<{ questionnaires?: BankItem[] }>("/api/questionnaires/bank");
      setBank((d.questionnaires || []).filter((q) => q.is_active));
    } catch {
      setBank([]);
    }
  }

  async function doCreate() {
    if (!qid) return;
    setBusy(true);
    try {
      const d = await postJSON<{ ok: boolean; created?: boolean }>("/api/questionnaires/assignments", {
        student_id: data.student.id,
        questionnaire_id: parseInt(qid, 10),
        reason,
      });
      if (!d.ok) throw new Error("创建失败");
      setCreateOpen(false);
      notify(d.created ? "任务已创建" : "已有同名活动任务，已复用", "ok");
      cache.invalidate("questionnaires");
    } catch (e) {
      notify(errorText(e), "error");
    } finally {
      setBusy(false);
    }
  }

  function copy(text: string) {
    if (!text) return;
    if (navigator.clipboard) {
      navigator.clipboard.writeText(text).then(
        () => notify("已复制", "ok"),
        () => notify("复制失败，请手动选择", "error"),
      );
    } else {
      notify("请手动选择文本复制");
    }
  }

  const full = data.permissions.full;
  const flags = full ? data.questionnaire_flags : [];

  return (
    <div>
      {flags.map((f) => (
        <div key={f.assignment_id} className="mb-3.5 flex flex-wrap items-center gap-2.5 bg-s3-bg px-3.5 py-[11px] text-sm text-s3">
          <div className="min-w-0 flex-1">
            {(f.flags || []).map((x) => (
              <div key={x.id}>
                <b>安全提醒：</b>
                {f.questionnaire_title} {x.label}：选择「{x.answer}」
              </div>
            ))}
          </div>
          {can_write ? (
            <Button variant="outline" size="sm" className="bg-background" onClick={() => void reviewFlag(f)}>
              我已跟进
            </Button>
          ) : null}
        </div>
      ))}
      <div className="mb-3 flex justify-end">
        {can_write && res.data?.enabled ? <Button onClick={openCreate}>发起问卷任务</Button> : null}
      </div>
      <Gate res={res}>
        {(q) => {
          if (!q.enabled) return <Empty>问卷模块未启用</Empty>;
          return (
            <div>
              {q.assignments.length === 0 ? <Empty>暂无问卷任务</Empty> : null}
              {q.restricted ? <p className="mb-3 text-sm text-mute">当前账号只显示完成状态。</p> : null}
              {q.assignments.map((a) => {
                const total = !q.restricted && a.scores ? a.scores.total : null;
                const scoreFlags = !q.restricted && a.scores ? a.scores.flags || [] : [];
                const summary: React.ReactNode[] = [];
                if (a.source === "auto") summary.push(<span key="r">规则：{a.reason || "—"}</span>);
                if (a.scores && !total && !q.restricted) {
                  const parts = (a.scores.dimensions || [])
                    .filter((x) => x.score !== null && x.score !== undefined)
                    .map((x) => (x.name || x.label || "") + " " + x.score + (x.band ? " · " + x.band.label : ""));
                  if (parts.length > 0) summary.push(<span key="d">{parts.join("；")}</span>);
                }
                if (total && total.score !== null && total.score !== undefined) {
                  summary.push(
                    <span key="t">
                      总分 {total.score}
                      {total.band ? " · " + total.band.label : ""}
                    </span>,
                  );
                }
                scoreFlags.forEach((x) =>
                  summary.push(
                    <span key={"f" + x.id} className="font-semibold text-attention">
                      {x.label}
                    </span>,
                  ),
                );
                const canExpand = !q.restricted && (a.scores || a.answers);
                return (
                  <div key={a.id} className="border-b border-line py-3">
                    <div className="flex flex-wrap items-center gap-2">
                      <b className="text-[15px] font-bold">{a.questionnaire_title}</b>
                      <span className="font-mono text-xs text-mute">{a.questionnaire_code}</span>
                      <Chip tone={Q_TONE[a.status] || "sn"}>
                        {(Q_LABEL[a.status] || a.status || "—") + (a.status === "submitted" && a.submitted_at ? " " + fmtDate(a.submitted_at).slice(0, 10) : "")}
                      </Chip>
                      {can_write ? (
                        <span className="ml-auto flex gap-1.5">
                          {a.status === "pending" ? (
                            <>
                              <Button variant="outline" size="sm" onClick={() => void reject(a.id)}>
                                驳回
                              </Button>
                              <Button
                                size="sm"
                                onClick={() => {
                                  setDelivery("account");
                                  setConfirmFor(a);
                                }}
                              >
                                确认分发
                              </Button>
                            </>
                          ) : null}
                          {a.status === "sent" ? (
                            <Button variant="outline" size="sm" onClick={() => showPackage(a.id)}>
                              分发信息
                            </Button>
                          ) : null}
                          {a.status === "expired" ? (
                            <Button variant="outline" size="sm" onClick={() => reissue(a.id)}>
                              重新生成链接
                            </Button>
                          ) : null}
                        </span>
                      ) : null}
                    </div>
                    {summary.length > 0 ? (
                      <p className="mt-1 text-[13.5px] text-ink-2">
                        {summary.map((x, i) => (
                          <React.Fragment key={i}>
                            {i > 0 ? " · " : null}
                            {x}
                          </React.Fragment>
                        ))}
                      </p>
                    ) : null}
                    {canExpand ? (
                      <div className="mt-2">
                        <button
                          type="button"
                          className="text-[12.5px] font-semibold text-hl hover:underline"
                          onClick={() => setOpenAns((m) => ({ ...m, [a.id]: !m[a.id] }))}
                        >
                          {openAns[a.id] ? "收起得分" : "展开得分"}
                        </button>
                        {openAns[a.id] ? (
                          <div className="mt-2">
                            {a.scores ? <ScoreTable s={a.scores} /> : null}
                            {a.answers ? (
                              <div className="mt-3 border border-line p-3">
                                {Object.entries(a.answers).map(([k, v]) => (
                                  <div key={k} className="flex gap-2 border-b border-line py-1.5 text-sm last:border-b-0">
                                    <span className="shrink-0 font-mono text-xs text-mute">{k}</span>
                                    <span className="min-w-0 break-words">{fmtAns(v)}</span>
                                  </div>
                                ))}
                              </div>
                            ) : null}
                          </div>
                        ) : null}
                      </div>
                    ) : null}
                  </div>
                );
              })}
            </div>
          );
        }}
      </Gate>

      <Dialog open={confirmFor !== null} onOpenChange={(open) => (open ? null : setConfirmFor(null))}>
        <DialogContent className="sm:rounded-none shadow-none">
          <DialogHeader>
            <DialogTitle>确认分发</DialogTitle>
          </DialogHeader>
          <div className="text-sm">
            <b>{confirmFor?.questionnaire_title}</b>
          </div>
          <div className="grid gap-2" role="radiogroup" aria-label="分发方式">
            {DELIVERIES.map((d) => (
              <button
                key={d.key}
                type="button"
                role="radio"
                aria-checked={delivery === d.key}
                onClick={() => setDelivery(d.key)}
                className={cn(
                  "border px-3 py-2 text-left text-sm",
                  delivery === d.key ? "border-rule bg-sunk" : "border-line hover:bg-sunk",
                )}
              >
                <b className="block">{d.label}</b>
                <span className="text-xs text-mute">{d.desc}</span>
              </button>
            ))}
          </div>
          <DialogFooter className="gap-2 sm:gap-0">
            <Button variant="outline" onClick={() => setConfirmFor(null)}>
              取消
            </Button>
            <Button disabled={busy} onClick={doConfirm}>
              确认并分发
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

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

      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent className="sm:rounded-none shadow-none">
          <DialogHeader>
            <DialogTitle>发起问卷任务</DialogTitle>
          </DialogHeader>
          <div className="text-sm">
            学生：<b>{data.student.name}</b>
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor="q-bank">问卷</Label>
            <select
              id="q-bank"
              className={cn(fieldClass, "h-9 w-full")}
              value={qid}
              onChange={(e) => setQid(e.target.value)}
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
            <Label htmlFor="q-reason">原因（可选）</Label>
            <textarea
              id="q-reason"
              rows={2}
              className={cn(fieldClass, "w-full py-2")}
              placeholder="例如：顾问建议补充主观反馈问卷"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
            />
          </div>
          {bank.length === 0 ? <p className="text-sm text-mute">无可选问卷（问卷模块未启用或题库为空）。</p> : null}
          <DialogFooter className="gap-2 sm:gap-0">
            <Button variant="outline" onClick={() => setCreateOpen(false)}>
              取消
            </Button>
            <Button disabled={busy || !qid} onClick={doCreate}>
              创建
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
