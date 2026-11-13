import * as React from "react";

import { Button } from "@/components/ui/button";
import { errorText, getJSON, postJSON } from "@/lib/api";
import { csrfToken } from "@/lib/boot";

import { dtShort, fmtValue, Section, useProfile, type Y4Item } from "./common";

export const Y4_SLOTS: { key: string; label: string }[] = [
  { key: "A2", label: "A2 核心素养" },
  { key: "B3", label: "B3 核心学习能力" },
  { key: "B4", label: "B4 核心认知能力 & 成长型思维" },
  { key: "B6", label: "B6 职业发展" },
];

export type SlotState = "empty" | "queued" | "reading" | "done" | "failed";
export type SlotStatus = {
  state: SlotState;
  file_name: string;
  read_at: string;
  name_in_pdf: string;
  name_mismatch: boolean;
  error: string;
  has_data: boolean;
  has_file: boolean;
  job_id: number | null;
  position: number;
};
export type BuildStatus = {
  state: "none" | "queued" | "running" | "done" | "failed";
  job_id: number | null;
  position: number;
  pdf_ready: boolean;
  built_at: string;
  stale: boolean;
  error: string;
};
export type Y4Status = {
  ok: boolean;
  report_id: number | null;
  round_id?: number | null;
  round_started_at: string;
  slots: Record<string, SlotStatus>;
  build: BuildStatus;
  edited_codes_by_slot: Record<string, string[]>;
};

type RawLite = {
  ok: boolean;
  interpretation?: string;
  raw?: { schema_124?: { code: string | number; source_pdf?: string }[] };
};

const CHUNK_SIZE = 1.5 * 1024 * 1024;
const MAX_ATTEMPTS = 3;
const POLL_MS = 3000;

const isPending = (s: Y4Status | null) =>
  !!s &&
  (Object.values(s.slots).some((x) => x.state === "queued" || x.state === "reading") ||
    s.build.state === "queued" ||
    s.build.state === "running");

const sleep = (ms: number) => new Promise((r) => window.setTimeout(r, ms));

/** 读取状态 + 轮询；有任务时每 3 秒刷新，读完后刷新 Y4 数值。 */
export function useY4Upload() {
  const { code, cache, data } = useProfile();
  const base = "/students/" + encodeURIComponent(code) + "/api/y4";
  const [status, setStatus] = React.useState<Y4Status | null>(null);
  const [error, setError] = React.useState("");
  const [codeSlot, setCodeSlot] = React.useState<Record<string, string>>({});
  const [interpretation, setInterpretation] = React.useState("");
  const [dataVersion, setDataVersion] = React.useState(0);
  const prev = React.useRef<Y4Status | null>(null);
  const reportId = status?.report_id ?? null;

  const load = React.useCallback(async () => {
    try {
      const s = await getJSON<Y4Status>(base + "/status");
      if (!s.ok) throw new Error("读取状态失败");
      const p = prev.current;
      prev.current = s;
      const finished =
        !!p &&
        Object.keys(s.slots).some(
          (k) =>
            (p.slots[k]?.state === "queued" || p.slots[k]?.state === "reading") &&
            (s.slots[k].state === "done" || s.slots[k].state === "failed"),
        );
      const created = !!p && (p.report_id !== s.report_id || p.round_id !== s.round_id);
      setStatus(s);
      setError("");
      if (finished || created) {
        cache.invalidate("y4data");
        setDataVersion((v) => v + 1);
      }
    } catch (e) {
      setError(errorText(e, "读取状态失败"));
    }
  }, [base, cache]);

  React.useEffect(() => {
    void load();
  }, [load]);

  const pending = isPending(status);
  React.useEffect(() => {
    if (!pending) return;
    const t = window.setInterval(() => void load(), POLL_MS);
    return () => window.clearInterval(t);
  }, [pending, load]);

  // 指标 → 所属资料（source_pdf）与已保存的 AI 解读；该接口不可用时只是不显示这两项。
  React.useEffect(() => {
    if (!reportId || !data.permissions.full) {
      setCodeSlot({});
      setInterpretation("");
      return;
    }
    let live = true;
    getJSON<RawLite>("/api/reports/" + reportId + "/raw")
      .then((d) => {
        if (!live || !d.ok) return;
        const m: Record<string, string> = {};
        (d.raw?.schema_124 || []).forEach((it) => {
          if (it.source_pdf) m[String(it.code)] = it.source_pdf;
        });
        setCodeSlot(m);
        setInterpretation(d.interpretation || "");
      })
      .catch(() => {
        // 无权限等：不显示
      });
    return () => {
      live = false;
    };
  }, [reportId, dataVersion, data.permissions.full]);

  return { status, error, load, codeSlot, interpretation, setInterpretation, base, bump: () => setDataVersion((v) => v + 1) };
}

export type Y4Upload = ReturnType<typeof useY4Upload>;

/** 该指标是否属于尚未上传的资料（只用于显示）。 */
export function notUploaded(up: Y4Upload, code: string, value: unknown): boolean {
  if (value !== null && value !== undefined && value !== "") return false;
  const slot = up.codeSlot[code];
  if (!slot) return false;
  const st = up.status?.slots[slot];
  return !!st && st.state !== "done";
}

export function valueText(up: Y4Upload, it: { code: string; value: unknown }): string {
  return notUploaded(up, it.code, it.value) ? "未上传" : fmtValue(it.value);
}

async function uploadChunks(slot: string, file: File, uploadId: string, onProgress: (pct: number) => void) {
  const total = Math.max(1, Math.ceil(file.size / CHUNK_SIZE));
  for (let i = 0; i < total; i++) {
    const blob = file.slice(i * CHUNK_SIZE, Math.min(file.size, (i + 1) * CHUNK_SIZE));
    let lastErr: Error | null = null;
    for (let attempt = 1; attempt <= MAX_ATTEMPTS; attempt++) {
      try {
        const fd = new FormData();
        fd.append("key", slot);
        fd.append("upload_id", uploadId);
        fd.append("chunk_index", String(i));
        fd.append("total_chunks", String(total));
        fd.append("chunk", blob, slot + ".part");
        const resp = await fetch("/api/upload/chunk", {
          method: "POST",
          body: fd,
          credentials: "same-origin",
          headers: { "X-CSRF-Token": csrfToken() },
        });
        if (!resp.ok) {
          let msg = "上传失败 (HTTP " + resp.status + ")";
          try {
            const e = await resp.json();
            if (e && e.error) msg = e.error;
          } catch {
            // 不是 JSON
          }
          const err = new Error(msg) as Error & { status?: number };
          err.status = resp.status;
          throw err;
        }
        lastErr = null;
        break;
      } catch (e) {
        lastErr = e as Error;
        const status = (e as { status?: number }).status;
        if ((status && status < 500) || attempt >= MAX_ATTEMPTS) break;
        await sleep(1000 * attempt);
      }
    }
    if (lastErr) throw lastErr;
    onProgress(Math.round(((i + 1) / total) * 100));
  }
}

function SlotRow({
  slotKey,
  label,
  st,
  base,
  canEdit,
  busy,
  localError,
  onPick,
  onRetry,
}: {
  slotKey: string;
  label: string;
  st: SlotStatus;
  base: string;
  canEdit: boolean;
  busy: string;
  localError: string;
  onPick: (slot: string, file: File) => void;
  onRetry: (jobId: number) => void;
}) {
  const input = React.useRef<HTMLInputElement>(null);
  const uploading = !!busy;
  const state = st.state;
  let body: React.ReactNode;
  if (uploading) body = <span className="text-mute">{busy}</span>;
  else if (state === "queued") body = <span className="text-mute">排队中 · 第 {st.position} 位</span>;
  else if (state === "reading") body = <span className="text-mute">读取中</span>;
  else if (state === "done")
    body = (
      <span className="min-w-0 break-words">
        {st.has_file ? (
          <a
            className="underline underline-offset-2"
            href={base + "/slots/" + slotKey + "/file"}
            target="_blank"
            rel="noreferrer"
          >
            {st.file_name || slotKey + ".pdf"}
          </a>
        ) : (
          st.file_name || "已读取"
        )}
        <span className="ml-2 text-[12.5px] text-mute">{dtShort(st.read_at)}</span>
      </span>
    );
  else if (state === "failed") body = <span className="min-w-0 break-words text-s2">{st.error || "读取失败"}</span>;
  else body = <span className="text-mute">未上传</span>;

  const canPick = canEdit && !uploading && state !== "queued" && state !== "reading";
  return (
    <div className="border-b border-line py-[7px]">
      <div className="grid grid-cols-[minmax(0,1fr)] items-center gap-x-3 gap-y-1 sm:grid-cols-[minmax(0,200px)_minmax(0,1fr)_auto]">
        <span className="font-semibold">{label}</span>
        <div className="min-w-0">{body}</div>
        <div className="flex items-center gap-1.5">
          {canEdit && state === "failed" && st.job_id && !uploading ? (
            <Button variant="outline" size="sm" onClick={() => onRetry(st.job_id as number)}>
              重试
            </Button>
          ) : null}
          {canPick ? (
            <Button variant="outline" size="sm" onClick={() => input.current?.click()}>
              {state === "done" || state === "failed" ? "重新上传" : "上传"}
            </Button>
          ) : null}
          <input
            ref={input}
            type="file"
            accept="application/pdf,.pdf"
            className="hidden"
            aria-label={label + " 上传文件"}
            onChange={(e) => {
              const f = e.target.files?.[0];
              e.target.value = "";
              if (f) onPick(slotKey, f);
            }}
          />
        </div>
      </div>
      {state === "done" && st.name_mismatch ? (
        <p className="mt-1 text-[12.5px] text-s2">资料中的姓名为「{st.name_in_pdf}」，与学生姓名不一致</p>
      ) : null}
      {localError ? <p className="mt-1 text-[12.5px] text-s2">{localError}</p> : null}
    </div>
  );
}

export function Y4UploadSection({ up, items, canEdit }: { up: Y4Upload; items: Y4Item[]; canEdit: boolean }) {
  const { cache, notify } = useProfile();
  const { status, base, load } = up;
  const [busy, setBusy] = React.useState<Record<string, string>>({});
  const [errs, setErrs] = React.useState<Record<string, string>>({});
  const [building, setBuilding] = React.useState(false);
  const [interpreting, setInterpreting] = React.useState(false);

  if (up.error && !status) return <p className="mb-3 text-[13px] text-s2">{up.error}</p>;
  if (!status) return null;

  const setSlotBusy = (slot: string, v: string) => setBusy((m) => ({ ...m, [slot]: v }));
  const setSlotErr = (slot: string, v: string) => setErrs((m) => ({ ...m, [slot]: v }));
  const anyDone = Y4_SLOTS.some((s) => status.slots[s.key]?.state === "done");
  const reportId = status.report_id;

  async function pick(slot: string, file: File) {
    if (!/\.pdf$/i.test(file.name) && file.type !== "application/pdf") {
      setSlotErr(slot, "只能上传 PDF 文件");
      return;
    }
    if (!file.size) {
      setSlotErr(slot, "文件为空");
      return;
    }
    const edited = status?.edited_codes_by_slot?.[slot] || [];
    if (edited.length) {
      const byCode = new Map(items.map((it) => [it.code, it]));
      const lines = edited.map((c) => {
        const it = byCode.get(c);
        return c + " " + (it?.label || "") + "：" + (it ? fmtValue(it.value) : "—");
      });
      if (!window.confirm("重新读取会替换以下手动修改的数值：\n" + lines.join("\n") + "\n\n确定继续？")) return;
    }
    setSlotErr(slot, "");
    const uploadId = "u" + Date.now() + "_" + Math.random().toString(36).slice(2, 10);
    try {
      setSlotBusy(slot, "上传中 0%");
      await uploadChunks(slot, file, uploadId, (p) => setSlotBusy(slot, "上传中 " + p + "%"));
      const r = await postJSON<{ ok: boolean; error?: string }>(base + "/read", {
        slot,
        upload_id: uploadId,
        file_name: file.name,
      });
      if (!r.ok) throw new Error(r.error || "提交失败");
      await load();
    } catch (e) {
      setSlotErr(slot, errorText(e, "上传失败"));
    } finally {
      setSlotBusy(slot, "");
    }
  }

  async function retry(slot: string, jobId: number) {
    setSlotErr(slot, "");
    try {
      const r = await postJSON<{ ok: boolean; error?: string }>(base + "/jobs/" + jobId + "/retry");
      if (!r.ok) throw new Error(r.error || "重试失败");
      await load();
    } catch (e) {
      setSlotErr(slot, errorText(e, "重试失败"));
    }
  }

  async function build() {
    setBuilding(true);
    try {
      const r = await postJSON<{ ok: boolean; error?: string }>(base + "/build");
      if (!r.ok) throw new Error(r.error || "生成失败");
      await load();
    } catch (e) {
      notify(errorText(e, "生成失败"), "error");
    } finally {
      setBuilding(false);
    }
  }

  async function newRound() {
    if (!window.confirm("开始新一轮测评后，新上传的资料会进入新的记录，之前的记录保留在「文件」中。")) return;
    try {
      const r = await postJSON<{ ok: boolean; error?: string }>(base + "/new-round");
      if (!r.ok) throw new Error(r.error || "操作失败");
      cache.invalidate("y4data");
      up.setInterpretation("");
      up.bump();
      await load();
    } catch (e) {
      notify(errorText(e, "操作失败"), "error");
    }
  }

  async function interpret() {
    if (!reportId) return;
    setInterpreting(true);
    try {
      const r = await postJSON<{ ok: boolean; error?: string; reply?: string }>(
        "/api/reports/" + reportId + "/interpret",
        {},
      );
      if (!r.ok) throw new Error(r.error || "生成失败");
      up.setInterpretation(r.reply || "");
    } catch (e) {
      notify(errorText(e, "生成失败"), "error");
    } finally {
      setInterpreting(false);
    }
  }

  const b = status.build;
  const buildBusy = building || b.state === "queued" || b.state === "running";
  let buildLine: React.ReactNode = null;
  if (b.state === "queued") buildLine = <span className="text-mute">排队中 · 第 {b.position} 位</span>;
  else if (b.state === "running") buildLine = <span className="text-mute">生成中</span>;
  else if (b.state === "failed" && b.error) buildLine = <span className="text-s2">{b.error}</span>;

  return (
    <Section
      title="Y4 资料"
      right={
        canEdit && reportId ? (
          <Button variant="outline" size="sm" onClick={() => void newRound()}>
            新一轮测评
          </Button>
        ) : null
      }
    >
      {Y4_SLOTS.map((s) => (
        <SlotRow
          key={s.key}
          slotKey={s.key}
          label={s.label}
          st={status.slots[s.key]}
          base={base}
          canEdit={canEdit}
          busy={busy[s.key] || ""}
          localError={errs[s.key] || ""}
          onPick={(slot, f) => void pick(slot, f)}
          onRetry={(id) => void retry(s.key, id)}
        />
      ))}
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 border-b border-line py-[7px]">
        <span className="font-semibold sm:w-[200px]">报告</span>
        {canEdit ? (
          <Button size="sm" disabled={!anyDone || buildBusy} onClick={() => void build()}>
            生成报告
          </Button>
        ) : null}
        {buildLine}
        {b.pdf_ready ? (
          <>
            <a className="underline underline-offset-2" href={base + "/build/file"}>
              下载报告
            </a>
            {b.built_at ? <span className="text-[12.5px] text-mute">{dtShort(b.built_at)}</span> : null}
          </>
        ) : null}
        {b.stale ? <span className="text-[12.5px] text-s2">数据有更新，报告需要重新生成</span> : null}
      </div>
      <div className="py-[7px]">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
          <span className="font-semibold sm:w-[200px]">AI 解读</span>
          {canEdit ? (
            <Button variant="outline" size="sm" disabled={!anyDone || interpreting} onClick={() => void interpret()}>
              {interpreting ? "生成中…" : "生成解读"}
            </Button>
          ) : null}
        </div>
        {up.interpretation ? (
          <div className="mt-2 max-h-[360px] overflow-y-auto whitespace-pre-wrap border border-line bg-sunk px-3 py-2 text-[13px]">
            {up.interpretation}
          </div>
        ) : null}
      </div>
    </Section>
  );
}
