import * as React from "react";

import { Button } from "@/components/ui/button";
import { deleteJSON, errorText, getJSON, postJSON } from "@/lib/api";
import { csrfToken } from "@/lib/boot";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

import { Empty, fmtDate, Gate, saveResponse, Section, useProfile, useResource } from "./common";

type Y4Status = {
  round_id: number | null;
  report_id: number | null;
  build: { state: string; pdf_ready: boolean; name_stale: boolean };
};

type SixPdfState = "missing" | "running" | "ready" | "stale" | "failed";
type SixPdfItem = {
  profile_id: number;
  version: number | null;
  report_id: number | null;
  report_date?: string | null;
  created_at: string | null;
  state: SixPdfState;
  size: number;
  generated_at: string | null;
  error: string;
};

type FileRow = { id: number; report_date: string | null; created_at: string | null; has_b3?: boolean };
type Minute = { id: number; report_id?: number | null; created_at: string | null };
type MinutesResp = { minutes: Minute[]; restricted?: boolean };

const ROW =
  "grid grid-cols-[minmax(0,1fr)_60px_auto] items-center gap-2.5 border-b border-line py-[7px] sm:grid-cols-[minmax(0,1fr)_80px_90px_auto]";

function y4State(status: Y4Status | null | undefined): string {
  if (status === undefined) return "读取中…";
  if (status === null) return "无法读取报告状态";
  const { build } = status;
  if (build.name_stale) return "学生姓名已更新，现有成品已过期";
  if (build.pdf_ready) return "可下载";
  if (build.state === "queued" || build.state === "running") return "生成中";
  return "尚未生成";
}

function sixPdfState(item: SixPdfItem): string {
  if (item.state === "ready") return "PDF 可下载";
  if (item.state === "running") return "生成中";
  if (item.state === "stale") return "档案已更新，PDF 待重新生成";
  if (item.state === "failed") return "生成失败";
  return "模型已生成，PDF 待生成";
}

async function failMessage(resp: Response, fallback: string): Promise<string> {
  let msg = fallback + " (HTTP " + resp.status + ")";
  try {
    const e = await resp.json();
    if (e && e.error) msg = e.error;
  } catch {
    // 不是 JSON：保留状态码
  }
  return msg;
}

function FileLine({ name, type, date, note, children }: { name: string; type: string; date: string; note?: string; children: React.ReactNode }) {
  return (
    <div className={ROW}>
      <span className="min-w-0">
        <b className="font-semibold">{name}</b>
        {note ? <small className="block text-xs text-mute">{note}</small> : null}
      </span>
      <span className="text-mute">{type}</span>
      <span className="font-mono text-mute max-sm:hidden">{date}</span>
      <span className="flex flex-wrap justify-end gap-2">{children}</span>
    </div>
  );
}

/** 任务 N：学生 360 统一「报告与文件」标签。展示既有成品与入口，不改造 Y4 取件。 */
export default function ReportFilesTab() {
  const { code, data, cache, notify, refreshPage, setTab } = useProfile();
  const { student, latest_report, six_am, first_touch } = data;
  const canWrite = data.permissions.can_write;
  const base = "/students/" + encodeURIComponent(code) + "/api/";
  const y4Base = base + "y4";

  const [y4, setY4] = React.useState<Y4Status | null>();
  React.useEffect(() => {
    let active = true;
    getJSON<Y4Status>(y4Base + "/status")
      .then((result) => { if (active) setY4(result); })
      .catch(() => { if (active) setY4(null); });
    return () => { active = false; };
  }, [y4Base, student.name]);

  const files = useResource<{ reports: FileRow[] }>("files", base + "reports");
  const minutes = useResource<MinutesResp>("minutes", base + "minutes");
  const pdfs = useResource<{ items: SixPdfItem[] }>("sixpdf", base + "six-am/pdf-status");

  const [busyId, setBusyId] = React.useState<number | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [v1, setV1] = React.useState<Record<number, { href: string; studentName: string }>>({});
  const [older, setOlder] = React.useState(false);

  const y4Ready = !!y4?.build.pdf_ready;
  const roundLabel = y4?.round_id ? "轮次 #" + y4.round_id : y4?.report_id ? "报告 #" + y4.report_id : "—";
  const ftReports = first_touch.restricted ? [] : first_touch.reports || [];
  const pdfItems = React.useMemo(
    () => [...(pdfs.data?.items || [])].sort(
      (a, b) =>
        String(b.report_date || "").localeCompare(String(a.report_date || "")) ||
        (b.version || 0) - (a.version || 0),
    ),
    [pdfs.data],
  );

  async function generatePdf(item: SixPdfItem) {
    setBusyId(item.profile_id);
    try {
      const res = await postJSON<{ ok: boolean; item: SixPdfItem }>(base + "six-am/" + item.profile_id + "/pdf");
      cache.invalidate("sixpdf");
      if (res.item.state === "failed") notify(res.item.error || "PDF 生成失败，可重试", "error");
      else if (res.item.state === "running") notify("PDF 生成中，请稍后刷新", "ok");
      else notify("PDF 已生成", "ok");
    } catch (e) {
      notify(errorText(e, "PDF 生成失败"), "error");
    } finally {
      setBusyId(null);
    }
  }

  async function regenerate(id: number) {
    setBusy(true);
    try {
      const resp = await fetch("/api/reports/" + id + "/regenerate", {
        method: "POST",
        credentials: "same-origin",
        headers: { "X-CSRF-Token": csrfToken() },
      });
      if (!resp.ok) throw new Error(await failMessage(resp, "生成失败"));
      await saveResponse(resp, "凭远Y4评测报告.pdf");
      const v1name = resp.headers.get("X-V1-Filename");
      if (v1name) setV1((m) => ({ ...m, [id]: { href: "/output/" + v1name, studentName: student.name } }));
      notify("PDF 已生成并下载", "ok");
    } catch (err) {
      notify(err instanceof Error && err.message ? err.message : "生成失败", "error");
    } finally {
      setBusy(false);
    }
  }

  async function generateY42(id: number) {
    setBusy(true);
    try {
      const resp = await fetch("/api/reports/" + id + "/y4-2", {
        method: "POST",
        credentials: "same-origin",
        headers: { "X-CSRF-Token": csrfToken() },
      });
      if (!resp.ok) throw new Error(await failMessage(resp, "生成失败"));
      await saveResponse(resp, "凭远Y4-2学习力报告.pdf");
      notify("Y4-2 已生成并下载", "ok");
    } catch (err) {
      notify(err instanceof Error && err.message ? err.message : "生成失败", "error");
    } finally {
      setBusy(false);
    }
  }

  async function downloadMinutes(minutesId: number) {
    try {
      const resp = await fetch("/api/transcript/docx", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", "X-CSRF-Token": csrfToken() },
        body: JSON.stringify({ minutes_id: minutesId }),
      });
      if (!resp.ok) throw new Error(await failMessage(resp, "生成失败"));
      await saveResponse(resp, "凭远Y4解读会纪要.docx");
    } catch (err) {
      notify(err instanceof Error && err.message ? err.message : "下载失败", "error");
    }
  }

  async function remove(id: number) {
    if (!window.confirm("确认删除此报告？此操作不可撤销。")) return;
    try {
      const d = await deleteJSON<{ ok: boolean; error?: string }>("/api/reports/" + id);
      if (!d.ok) throw new Error(d.error || "删除失败");
      notify("已删除", "ok");
      cache.invalidate("files", "y4data");
      await refreshPage();
    } catch (e) {
      notify(errorText(e, "删除失败"), "error");
    }
  }

  function sixPdfActions(item: SixPdfItem) {
    const href = base + "six-am/" + item.profile_id + "/pdf/file";
    const generating = item.state === "running" || busyId === item.profile_id;
    return (
      <span className="inline-flex flex-wrap justify-end gap-2">
        <Button variant="outline" size="sm" onClick={() => setTab("six_am")}>
          查看 6AM
        </Button>
        {item.state === "ready" ? (
          <>
            <Button variant="outline" size="sm" asChild>
              <a href={href} target="_blank" rel="noreferrer">预览 PDF</a>
            </Button>
            <Button variant="outline" size="sm" asChild>
              <a href={href + "?download=1"} download>下载 PDF</a>
            </Button>
          </>
        ) : generating ? (
          <Button variant="outline" size="sm" disabled>生成中…</Button>
        ) : canWrite ? (
          <Button variant="outline" size="sm" disabled={busyId === item.profile_id} onClick={() => void generatePdf(item)}>
            {item.state === "failed" || item.state === "stale" ? "重新生成 PDF" : "生成 PDF"}
          </Button>
        ) : null}
      </span>
    );
  }

  function reportRows(r: FileRow) {
    const date = r.report_date || fmtDate(r.created_at).slice(0, 10);
    const linked = (minutes.data?.minutes || []).filter((m) => m.report_id === r.id);
    const isCurrentRound = y4?.report_id === r.id;
    return (
      <div>
        <FileLine name="Y4 综合报告快照" type="数据" date={date} note={isCurrentRound ? "当前轮次成品见上方「可交付报告」" : undefined}>
          <Button variant="outline" size="sm" asChild>
            <a href={"/api/reports/" + r.id + "/raw?download=1"} download>数据 JSON</a>
          </Button>
          <Button variant="outline" size="sm" asChild>
            <a href={"/api/reports/" + r.id + "/evaluation"} download>有效评价</a>
          </Button>
          {v1[r.id]?.studentName === student.name ? (
            <Button variant="outline" size="sm" asChild>
              <a href={v1[r.id].href} target="_blank" rel="noreferrer">旧版 PDF</a>
            </Button>
          ) : null}
          {canWrite && !isCurrentRound ? (
            <Button variant="outline" size="sm" disabled={busy} onClick={() => regenerate(r.id)}>
              重新生成 PDF（维护）
            </Button>
          ) : null}
        </FileLine>
        {r.has_b3 ? (
          <FileLine name="Y4-2 学习力报告" type="维护" date={date}>
            {canWrite ? (
              <Button size="sm" disabled={busy} onClick={() => generateY42(r.id)}>
                重新生成并下载
              </Button>
            ) : null}
          </FileLine>
        ) : null}
        {linked.map((m) => (
          <FileLine key={m.id} name="解读会纪要" type="DOCX" date={fmtDate(m.created_at).slice(0, 10)}>
            <Button variant="outline" size="sm" onClick={() => downloadMinutes(m.id)}>
              下载
            </Button>
          </FileLine>
        ))}
        {canWrite ? (
          <div className="py-2">
            <button
              type="button"
              className="text-xs text-mute underline-offset-2 hover:text-attention hover:underline"
              onClick={() => remove(r.id)}
            >
              删除此报告
            </button>
          </div>
        ) : null}
      </div>
    );
  }

  return (
    <div>
      <Section title="可交付报告" sub="对外电子交付仍按既有流程与账号权限执行">
        <div className="overflow-x-auto">
          <Table className="min-w-[680px]">
            <TableHeader>
              <TableRow>
                <TableHead>报告</TableHead>
                <TableHead>版本 / 轮次</TableHead>
                <TableHead>状态</TableHead>
                <TableHead className="text-right">操作</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              <TableRow>
                <TableCell className="font-semibold">Y4 综合测评报告</TableCell>
                <TableCell className="font-mono">{y4Ready ? "v2 · " + roundLabel : roundLabel}</TableCell>
                <TableCell>{y4State(y4)}</TableCell>
                <TableCell className="whitespace-nowrap text-right">
                  <span className="inline-flex gap-2">
                    <Button variant="outline" size="sm" onClick={() => setTab("y4")}>查看</Button>
                    {y4Ready ? (
                      <Button variant="outline" size="sm" asChild>
                        <a href={y4Base + "/build/file"}>下载 PDF</a>
                      </Button>
                    ) : (
                      <Button variant="outline" size="sm" disabled>下载 PDF</Button>
                    )}
                  </span>
                </TableCell>
              </TableRow>

              {pdfs.status === "error" ? (
                <TableRow>
                  <TableCell className="font-semibold">6AM 初步诊断与支持建议</TableCell>
                  <TableCell colSpan={3} className="text-attention">6AM PDF 状态读取失败</TableCell>
                </TableRow>
              ) : pdfItems.length === 0 ? (
                <TableRow>
                  <TableCell className="font-semibold">6AM 初步诊断与支持建议</TableCell>
                  <TableCell className="font-mono">—</TableCell>
                  <TableCell>{pdfs.status === "ready" ? "尚无 6AM 档案" : "读取中…"}</TableCell>
                  <TableCell className="text-right">
                    <Button variant="outline" size="sm" onClick={() => setTab("six_am")}>查看 6AM</Button>
                  </TableCell>
                </TableRow>
              ) : (
                pdfItems.map((item) => (
                  <TableRow key={"six-" + item.profile_id}>
                    <TableCell className="font-semibold">
                      6AM 初步诊断与支持建议
                      {six_am?.profile_id === item.profile_id ? <span className="ml-2 text-xs font-normal text-mute">当前版本</span> : null}
                      {item.state === "failed" && item.error ? (
                        <small className="mt-1 block text-xs font-normal text-attention">{item.error}</small>
                      ) : null}
                    </TableCell>
                    <TableCell className="font-mono">
                      {(item.version ? "v" + item.version : "—") +
                        (item.report_date ? " · " + fmtDate(item.report_date).slice(0, 10) : "")}
                    </TableCell>
                    <TableCell>{sixPdfState(item)}</TableCell>
                    <TableCell className="whitespace-nowrap text-right">{sixPdfActions(item)}</TableCell>
                  </TableRow>
                ))
              )}

              {ftReports.length === 0 ? (
                <TableRow>
                  <TableCell className="font-semibold">First Touch 会谈报告</TableCell>
                  <TableCell className="font-mono">—</TableCell>
                  <TableCell>{first_touch.restricted ? "无权查看" : "尚无已确认版本"}</TableCell>
                  <TableCell className="text-right">
                    <Button variant="outline" size="sm" onClick={() => setTab("first_touch")}>查看</Button>
                  </TableCell>
                </TableRow>
              ) : (
                ftReports.map((r) => (
                  <TableRow key={"ft-" + r.id}>
                    <TableCell className="font-semibold">First Touch 会谈报告</TableCell>
                    <TableCell className="font-mono">{"v" + r.version}</TableCell>
                    <TableCell>已确认</TableCell>
                    <TableCell className="whitespace-nowrap text-right">
                      <span className="inline-flex gap-2">
                        <Button variant="outline" size="sm" asChild>
                          <a href={"/api/growth-talk/reports/" + r.id + "/download.pdf"} target="_blank" rel="noreferrer">PDF</a>
                        </Button>
                        <Button variant="outline" size="sm" asChild>
                          <a href={"/api/growth-talk/reports/" + r.id + "/download.json"} download>JSON</a>
                        </Button>
                      </span>
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </div>
      </Section>

      <Section title="其他文件与纪要" sub="研究员内部材料，不随对外交付开放">
        <Gate res={files}>
          {(d) => {
            if (d.reports.length === 0) return <Empty>该学生暂无历史报告文件</Empty>;
            const sorted = [...d.reports].sort(
              (a, b) => String(b.report_date || "").localeCompare(String(a.report_date || "")) || b.id - a.id,
            );
            const [latest, ...rest] = sorted;
            return (
              <div>
                <div className="border-t-2 border-rule">{reportRows(latest)}</div>
                {rest.length > 0 ? (
                  <div className="mt-4">
                    <button
                      type="button"
                      aria-expanded={older}
                      className="text-[13px] font-semibold text-hl hover:underline"
                      onClick={() => setOlder((v) => !v)}
                    >
                      更早的报告
                    </button>
                    {older
                      ? rest.map((r) => (
                          <div key={r.id} className="mt-3 border-t border-rule">
                            {reportRows(r)}
                          </div>
                        ))
                      : null}
                  </div>
                ) : null}
              </div>
            );
          }}
        </Gate>
        {minutes.status === "ready" && (minutes.data?.minutes || []).length === 0 ? (
          <p className="mt-3 text-xs text-mute">暂无解读会纪要{latest_report ? "" : "；该学生也还没有报告记录"}。</p>
        ) : null}
      </Section>

      <Section title="交付与权限">
        <div className="grid gap-1.5 text-sm">
          <p>本页只汇集档案内已有的报告与文件入口；成品、版本、权限与取件沿用原有接口与账号归属。</p>
          <p>Y4 正式成品的下载仍走原有取件路由；「重新生成」是明确的维护操作，普通下载不会触发重生成。</p>
          <p className="text-mute">促签个案的签约状态尚未在系统中记录，对外交付前请人工核对。</p>
        </div>
      </Section>
    </div>
  );
}

