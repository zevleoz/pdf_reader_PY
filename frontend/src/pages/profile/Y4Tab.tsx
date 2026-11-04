import * as React from "react";
import { Search } from "lucide-react";

import { cn } from "@/lib/utils";

import { Chip, evalTone, fmtValue, Gate, useProfile, useY4Data, WEAK_EVALS } from "./common";

const FALLBACK_DIMS = ["心力", "精力", "学习力", "生涯力"];

export default function Y4Tab() {
  const { y4Dim, setY4Dim } = useProfile();
  const res = useY4Data();
  const [low, setLow] = React.useState(false);
  const [q, setQ] = React.useState("");

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
              <label className="flex h-8 w-full items-center gap-2 border border-line px-2.5 text-mute focus-within:border-ink sm:w-[220px]">
                <Search className="h-4 w-4 shrink-0" />
                <input
                  className="min-w-0 flex-1 bg-transparent text-sm text-ink outline-none"
                  placeholder="搜索指标"
                  value={q}
                  onChange={(e) => setQ(e.target.value)}
                />
              </label>
              <span className="ml-auto text-[13px] text-mute">{rows.length} 项</span>
            </div>
            {rows.length === 0 ? (
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
