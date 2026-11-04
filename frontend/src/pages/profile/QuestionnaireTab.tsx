import * as React from "react";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { errorText, getJSON, postJSON } from "@/lib/api";
import { cn } from "@/lib/utils";

import { Empty, fieldClass, fmtDate, Gate, Q_LABEL, Section, Tag, useProfile, useResource, type ScoreSet } from "./common";
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

function qTone(s: string): "strong" | "alert" | "soft" | "plain" {
  if (s === "submitted") return "strong";
  if (s === "rejected" || s === "expired") return "alert";
  if (s === "sent") return "soft";
  return "plain";
}

type Pkg = { title: string; text: string; note: string };

export default function QuestionnaireTab() {
  const { code, data, cache, notify } = useProfile();
  const { can_write } = data.permissions;
  const res = useResource<QResp>("questionnaires", "/students/" + encodeURIComponent(code) + "/api/questionnaires");
  const [openAns, setOpenAns] = React.useState<Record<number, boolean>>({});
  const [pkg, setPkg] = React.useState<Pkg | null>(null);
  const [createOpen, setCreateOpen] = React.useState(false);
  const [bank, setBank] = React.useState<BankItem[]>([]);
  const [qid, setQid] = React.useState("");
  const [reason, setReason] = React.useState("");
  const [busy, setBusy] = React.useState(false);

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

  return (
    <div>
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
              {q.assignments.map((a) => (
                <Section
                  key={a.id}
                  title={a.questionnaire_title}
                  sub={
                    <>
                      <span className="font-mono">{a.questionnaire_code}</span> · 创建 {fmtDate(a.created_at)}
                    </>
                  }
                  right={
                    <>
                      <Tag tone={qTone(a.status)}>{Q_LABEL[a.status] || a.status || "—"}</Tag>
                      {can_write && a.status === "pending" ? (
                        <Button variant="outline" size="sm" asChild>
                          <a href="/workspace">去确认</a>
                        </Button>
                      ) : null}
                      {can_write && a.status === "sent" ? (
                        <Button variant="outline" size="sm" onClick={() => showPackage(a.id)}>
                          分发信息
                        </Button>
                      ) : null}
                      {can_write && a.status === "expired" ? (
                        <Button variant="outline" size="sm" onClick={() => reissue(a.id)}>
                          重新生成链接
                        </Button>
                      ) : null}
                    </>
                  }
                >
                  <div className="pb-3 text-sm">
                    {a.source === "auto" ? <p className="text-mute">来源：识别规则 · {a.reason || "—"}</p> : null}
                    {a.submitted_at ? (
                      <p className="mt-1 text-mute">
                        提交时间：<span className="font-mono">{fmtDate(a.submitted_at)}</span>
                      </p>
                    ) : null}
                    {!q.restricted && a.scores ? (
                      <div className="mt-3">
                        <ScoreTable s={a.scores} />
                      </div>
                    ) : null}
                    {!q.restricted && a.answers ? (
                      <div className="mt-3">
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => setOpenAns((m) => ({ ...m, [a.id]: !m[a.id] }))}
                        >
                          {openAns[a.id] ? "收起原始答案" : "展开原始答案"}
                        </Button>
                        {openAns[a.id] ? (
                          <div className="mt-2 border border-line p-3">
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
                </Section>
              ))}
            </div>
          );
        }}
      </Gate>

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
