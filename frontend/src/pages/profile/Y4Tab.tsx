import * as React from "react";
import { Search } from "lucide-react";

import { Button } from "@/components/ui/button";
import { errorText, getJSON, postJSON } from "@/lib/api";
import { csrfToken } from "@/lib/boot";
import { cn } from "@/lib/utils";

import { Chip, evalTone, fmtDate, fmtValue, Gate, saveResponse, useProfile, useY4Data, WEAK_EVALS } from "./common";

const FALLBACK_DIMS = ["心力", "精力", "学习力", "生涯力"];

type RawItem = { code: string; label?: string; value?: unknown; source_pdf?: string };
type EditEntry = { code: string; old?: string; new?: string; by?: string; at?: string };
type RawResp = { ok: boolean; error?: string; raw: { schema_124?: RawItem[]; edits?: EditEntry[] } };

const asText = (v: unknown) => (v === null || v === undefined ? "" : String(v));

/** 编辑态：报告快照里的全部数值（含同龄均值、新版 B3 的 134/135），改动保存到快照，
 *  生成 PDF 即用新值（/api/reports/<id>/values + /regenerate）。 */
function Y4Editor({ reportId, query, onClose }: { reportId: number; query: string; onClose: () => void }) {
  const { cache, notify } = useProfile();
  const [items, setItems] = React.useState<RawItem[] | null>(null);
  const [log, setLog] = React.useState<EditEntry[]>([]);
  const [orig, setOrig] = React.useState<Record<string, string>>({});
  const [draft, setDraft] = React.useState<Record<string, string>>({});
  const [busy, setBusy] = React.useState<"" | "save" | "pdf">("");
  const [loadError, setLoadError] = React.useState("");

  const load = React.useCallback(async () => {
    try {
      const d = await getJSON<RawResp>("/api/reports/" + reportId + "/raw");
      if (!d.ok) throw new Error(d.error || "加载失败");
      const list = (d.raw.schema_124 || []).map((it) => ({ ...it, code: String(it.code) }));
      const o: Record<string, string> = {};
      list.forEach((it) => (o[it.code] = asText(it.value)));
      setItems(list);
      setOrig(o);
      setDraft(o);
      setLog([...(d.raw.edits || [])].sort((a, b) => String(b.at || "").localeCompare(String(a.at || ""))));
      setLoadError("");
    } catch (e) {
      setLoadError(errorText(e, "加载失败"));
    }
  }, [reportId]);

  React.useEffect(() => {
    void load();
  }, [load]);

  const changed = Object.keys(draft).filter((c) => draft[c] !== orig[c]);
  const labels: Record<string, string> = {};
  (items || []).forEach((it) => (labels[it.code] = it.label || ""));

  function close() {
    if (changed.length && !window.confirm("有未保存的修改，确定离开？")) return;
    onClose();
  }

  async function downloadPdf() {
    const resp = await fetch("/api/reports/" + reportId + "/regenerate", {
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
    await saveResponse(resp, "凭远Y4评测报告.pdf");
  }

  async function save(alsoPdf: boolean) {
    if (!changed.length) return;
    setBusy(alsoPdf ? "pdf" : "save");
    try {
      const edits: Record<string, string> = {};
      changed.forEach((c) => (edits[c] = draft[c]));
      const r = await postJSON<{ ok: boolean; error?: string; changed: string[] }>(
        "/api/reports/" + reportId + "/values",
        { edits },
      );
      if (!r.ok) throw new Error(r.error || "保存失败");
      cache.invalidate("y4data");
      await load();
      if (alsoPdf) {
        await downloadPdf();
        notify("已保存，PDF 已按新数值生成并下载", "ok");
      } else {
        notify("已保存 " + r.changed.length + " 项", "ok");
      }
    } catch (e) {
      notify(errorText(e, "保存失败"), "error");
    } finally {
      setBusy("");
    }
  }

  if (loadError) return <p className="py-8 text-center text-s1">{loadError}</p>;
  if (!items) return <p className="py-8 text-center text-mute">加载中…</p>;

  const needle = query.trim().toLowerCase();
  const rows = items.filter(
    (it) => !needle || String(it.label || "").toLowerCase().includes(needle) || it.code.toLowerCase().includes(needle),
  );

  return (
    <div>
      <div className="sticky top-0 z-10 mb-2 flex flex-wrap items-center gap-2 border-b border-rule bg-background py-2">
        <span className="text-[13px] text-mute">
          编辑本报告全部数值（含同龄均值）。保存后，生成 PDF 会使用新数值。
        </span>
        <span className="ml-auto flex flex-wrap items-center gap-2">
          {changed.length ? <span className="text-[13px] font-semibold">已修改 {changed.length} 项</span> : null}
          <Button variant="outline" size="sm" disabled={!!busy} onClick={close}>
            完成
          </Button>
          <Button variant="outline" size="sm" disabled={!changed.length || !!busy} onClick={() => void save(false)}>
            {busy === "save" ? "保存中…" : "保存修改"}
          </Button>
          <Button size="sm" disabled={!changed.length || !!busy} onClick={() => void save(true)}>
            {busy === "pdf" ? "生成中…" : "保存并生成 PDF"}
          </Button>
        </span>
      </div>
      {rows.length === 0 ? (
        <p className="px-4 py-11 text-center">
          <b className="block text-base text-ink">没有匹配的指标</b>
        </p>
      ) : (
        rows.map((it) => {
          const isChanged = draft[it.code] !== orig[it.code];
          return (
            <div
              key={it.code}
              className="grid grid-cols-[minmax(0,1fr)_110px_44px] items-center gap-2.5 border-b border-line py-[5px]"
            >
              <span className="min-w-0 break-words">
                {it.label || "—"} <span className="ml-1 font-mono text-[11px] text-mute">{it.code}</span>
              </span>
              <input
                aria-label={(it.label || it.code) + " 数值"}
                className={cn(
                  "h-7 w-full border border-line bg-transparent px-2 text-right font-semibold outline-none focus:border-ink",
                  isChanged && "border-[#EAD48A] bg-[#FFF7D6]",
                )}
                value={draft[it.code] ?? ""}
                onChange={(e) => setDraft((m) => ({ ...m, [it.code]: e.target.value }))}
              />
              <span className="font-mono text-[11px] text-mute">{it.source_pdf || ""}</span>
            </div>
          );
        })
      )}
      {log.length ? (
        <div className="mt-5 text-[12.5px] text-mute">
          <b className="mb-1 block text-ink">修改记录</b>
          <ul className="list-disc space-y-0.5 pl-5">
            {log.slice(0, 20).map((e, i) => (
              <li key={i}>
                {e.code} {labels[e.code] || ""}：{e.old || "（空）"} → {e.new || "（空）"}（{e.by || "-"}，
                {e.at ? fmtDate(e.at) : "-"}）
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

export default function Y4Tab() {
  const { y4Dim, setY4Dim, data } = useProfile();
  const res = useY4Data();
  const [low, setLow] = React.useState(false);
  const [q, setQ] = React.useState("");
  const [editing, setEditing] = React.useState(false);
  const canEdit = data.permissions.can_write;

  return (
    <Gate res={res}>
      {(d) => {
        const dimNames = d.dims.length > 0 ? d.dims.map((x) => x.name) : FALLBACK_DIMS;
        const needle = q.trim().toLowerCase();
        const rows = d.items.filter(
          (it) =>
            (!y4Dim || it.dimension === y4Dim) &&
            (!low || WEAK_EVALS.includes(it.eval)) &&
            (!needle || String(it.label).toLowerCase().includes(needle) || String(it.code).toLowerCase().includes(needle)),
        );
        return (
          <div>
            <div className="mb-3 flex flex-wrap items-center gap-2">
              {!editing ? (
                <>
                  <div className="inline-flex max-w-full overflow-x-auto border border-rule">
                    {["", ...dimNames].map((name, i) => (
                      <button
                        key={name || "all"}
                        type="button"
                        onClick={() => setY4Dim(name)}
                        className={cn(
                          "h-8 whitespace-nowrap px-3 text-[13px] font-medium transition-colors hover:bg-sunk",
                          i > 0 && "border-l border-rule",
                          y4Dim === name && "bg-ink font-semibold text-white hover:bg-ink",
                        )}
                      >
                        {name || "全部"}
                      </button>
                    ))}
                  </div>
                  <button
                    type="button"
                    aria-pressed={low}
                    onClick={() => setLow((v) => !v)}
                    className={cn(
                      "h-7 whitespace-nowrap border border-rule px-2.5 text-[12.5px] font-semibold transition-colors hover:bg-sunk",
                      low && "bg-ink text-white hover:bg-ink",
                    )}
                  >
                    只看偏低和需关注
                  </button>
                </>
              ) : null}
              <label className="flex h-8 w-full items-center gap-2 border border-line px-2.5 text-mute focus-within:border-ink sm:w-[220px]">
                <Search className="h-4 w-4 shrink-0" />
                <input
                  className="min-w-0 flex-1 bg-transparent text-sm text-ink outline-none"
                  placeholder="搜索指标"
                  value={q}
                  onChange={(e) => setQ(e.target.value)}
                />
              </label>
              {!editing ? (
                <span className="ml-auto flex items-center gap-3">
                  <span className="text-[13px] text-mute">{rows.length} 项</span>
                  {canEdit && d.report ? (
                    <Button variant="outline" size="sm" onClick={() => setEditing(true)}>
                      编辑数值
                    </Button>
                  ) : null}
                </span>
              ) : null}
            </div>
            {editing && d.report ? (
              <Y4Editor reportId={d.report.id} query={q} onClose={() => setEditing(false)} />
            ) : rows.length === 0 ? (
              <p className="px-4 py-11 text-center">
                <b className="block text-base text-ink">{d.items.length === 0 ? "暂无画像数据" : "没有匹配的指标"}</b>
              </p>
            ) : (
              <div>
                {rows.map((it) => (
                  <div
                    key={it.code}
                    className="grid grid-cols-[minmax(0,1fr)_70px_90px] items-center gap-2.5 border-b border-line py-[7px]"
                  >
                    <span className="min-w-0 break-words">
                      {it.label} <span className="ml-1 font-mono text-[11px] text-mute">{it.code}</span>
                    </span>
                    <span className="text-right font-semibold">{fmtValue(it.value)}</span>
                    <span>{it.eval ? <Chip tone={evalTone(it.eval)}>{it.eval}</Chip> : null}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        );
      }}
    </Gate>
  );
}
