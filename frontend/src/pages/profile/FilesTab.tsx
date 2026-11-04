import * as React from "react";

import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { deleteJSON, errorText } from "@/lib/api";
import { csrfToken } from "@/lib/boot";

import { Empty, fmtDate, Gate, useProfile, useResource } from "./common";

type FileRow = { id: number; report_date: string | null; created_at: string | null };

export default function FilesTab() {
  const { code, data, cache, notify, refreshPage } = useProfile();
  const canWrite = data.permissions.can_write;
  const res = useResource<{ reports: FileRow[] }>("files", "/students/" + encodeURIComponent(code) + "/api/reports");
  const [busy, setBusy] = React.useState(false);
  const [v1, setV1] = React.useState<Record<number, string>>({});

  async function regenerate(id: number) {
    setBusy(true);
    try {
      const resp = await fetch("/api/reports/" + id + "/regenerate", {
        method: "POST",
        credentials: "same-origin",
        headers: { "X-CSRF-Token": csrfToken() },
      });
      if (!resp.ok) {
        let msg = "生成失败 (HTTP " + resp.status + ")";
        try {
          const e = await resp.json();
          if (e && e.error) msg = e.error;
        } catch {
          // 不是 JSON：保留状态码
        }
        throw new Error(msg);
      }
      const blob = await resp.blob();
      let filename = "凭远Y4评测报告.pdf";
      const disp = resp.headers.get("Content-Disposition") || "";
      const star = disp.match(/filename\*=UTF-8''([^;\n]+)/i);
      if (star) filename = decodeURIComponent(star[1]);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 5000);
      const v1name = resp.headers.get("X-V1-Filename");
      if (v1name) setV1((m) => ({ ...m, [id]: "/output/" + v1name }));
      notify("PDF 已生成并下载", "ok");
    } catch (err) {
      notify(err instanceof Error && err.message ? err.message : "生成失败", "error");
    } finally {
      setBusy(false);
    }
  }

  async function remove(id: number) {
    if (!window.confirm("确认删除此报告？此操作不可撤销。")) return;
    try {
      const d = await deleteJSON<{ ok: boolean; error?: string }>("/api/reports/" + id);
      if (!d.ok) throw new Error(d.error || "删除失败");
      notify("已删除", "ok");
      cache.invalidate("files");
      await refreshPage();
    } catch (e) {
      notify(errorText(e, "删除失败"), "error");
    }
  }

  return (
    <Gate res={res}>
      {(d) =>
        d.reports.length === 0 ? (
          <Empty>该学生暂无报告</Empty>
        ) : (
          <Table className="min-w-[560px]">
            <TableHeader>
              <TableRow>
                <TableHead>报告日期</TableHead>
                <TableHead>创建时间</TableHead>
                <TableHead className="text-right">操作</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {d.reports.map((r) => (
                <TableRow key={r.id}>
                  <TableCell className="font-mono">{r.report_date || "—"}</TableCell>
                  <TableCell className="font-mono">{fmtDate(r.created_at)}</TableCell>
                  <TableCell className="text-right">
                    <span className="inline-flex flex-wrap justify-end gap-2">
                      {canWrite ? (
                        <Button size="sm" disabled={busy} onClick={() => regenerate(r.id)}>
                          生成 PDF
                        </Button>
                      ) : null}
                      {v1[r.id] ? (
                        <Button variant="outline" size="sm" asChild>
                          <a href={v1[r.id]} target="_blank" rel="noreferrer">
                            旧版
                          </a>
                        </Button>
                      ) : null}
                      <Button variant="outline" size="sm" asChild>
                        <a href={"/api/reports/" + r.id + "/raw?download=1"} download>
                          JSON
                        </a>
                      </Button>
                      <Button variant="outline" size="sm" asChild>
                        <a href={"/api/reports/" + r.id + "/evaluation"} download>
                          有效评价
                        </a>
                      </Button>
                      {canWrite ? (
                        <Button variant="outline" size="sm" className="text-attention" onClick={() => remove(r.id)}>
                          删除
                        </Button>
                      ) : null}
                    </span>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )
      }
    </Gate>
  );
}
