import * as React from "react";

import { Button } from "@/components/ui/button";
import { deleteJSON, errorText } from "@/lib/api";
import { csrfToken } from "@/lib/boot";

import { Empty, fmtDate, Gate, saveResponse, useProfile, useResource } from "./common";

type FileRow = { id: number; report_date: string | null; created_at: string | null };
type Minute = { id: number; report_id?: number | null; created_at: string | null };
type MinutesResp = { minutes: Minute[]; restricted?: boolean };

const ROW =
  "grid grid-cols-[minmax(0,1fr)_60px_auto] items-center gap-2.5 border-b border-line py-[7px] sm:grid-cols-[minmax(0,1fr)_80px_90px_auto]";

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

export default function FilesTab() {
  const { code, data, cache, notify, refreshPage } = useProfile();
  const canWrite = data.permissions.can_write;
  const base = "/students/" + encodeURIComponent(code) + "/api/";
  const res = useResource<{ reports: FileRow[] }>("files", base + "reports");
  const minutes = useResource<MinutesResp>("minutes", base + "minutes");
  const [busy, setBusy] = React.useState(false);
  const [v1, setV1] = React.useState<Record<number, string>>({});
  const [older, setOlder] = React.useState(false);

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
      if (v1name) setV1((m) => ({ ...m, [id]: "/output/" + v1name }));
      notify("PDF 已生成并下载", "ok");
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

  function reportRows(r: FileRow) {
    const date = r.report_date || fmtDate(r.created_at).slice(0, 10);
    // 纪要隐藏给 概要 账号（接口对它们返回空列表）
    const linked = (minutes.data?.minutes || []).filter((m) => m.report_id === r.id);
    return (
      <div>
        <FileLine name="Y4 综合报告" type="PDF" date={date}>
          {v1[r.id] ? (
            <Button variant="outline" size="sm" asChild>
              <a href={v1[r.id]} target="_blank" rel="noreferrer">
                旧版
              </a>
            </Button>
          ) : null}
          {canWrite ? (
            <Button size="sm" disabled={busy} onClick={() => regenerate(r.id)}>
              下载
            </Button>
          ) : null}
        </FileLine>
        <FileLine name="Y4 数据" type="JSON" date={date}>
          <Button variant="outline" size="sm" asChild>
            <a href={"/api/reports/" + r.id + "/raw?download=1"} download>
              下载
            </a>
          </Button>
        </FileLine>
        <FileLine name="有效评价" type="MD" date={date} note="首次下载会生成解读，需要一点时间">
          <Button variant="outline" size="sm" asChild>
            <a href={"/api/reports/" + r.id + "/evaluation"} download>
              下载
            </a>
          </Button>
        </FileLine>
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
    <Gate res={res}>
      {(d) => {
        if (d.reports.length === 0) return <Empty>该学生暂无报告</Empty>;
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
  );
}
