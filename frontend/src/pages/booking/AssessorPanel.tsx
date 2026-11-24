import * as React from "react";

import { Button } from "@/components/ui/button";
import { errorText, getJSON, postJSON } from "@/lib/api";
import { cn } from "@/lib/utils";

import { TIMES, addDays, md, todayKey, wdOf } from "./model";

type Avail = { time_slots: string[]; availability: Record<string, Record<string, boolean>>; office_id: number | null };

/** 测评师维护自己的可约时段：默认沿用办公室开放，可逐格关闭。 */
export default function AssessorPanel({ onClose }: { onClose: () => void }) {
  const [data, setData] = React.useState<Avail | null>(null);
  const [start, setStart] = React.useState(todayKey());
  const [busy, setBusy] = React.useState("");
  const [err, setErr] = React.useState("");
  const days = Array.from({ length: 7 }, (_, i) => addDays(start, i));

  const load = React.useCallback(async (s: string) => {
    try {
      const r = await getJSON<Avail>("/api/assessor/availability?start=" + s + "&days=7");
      setData(r);
      setErr("");
    } catch (e) {
      setErr(errorText(e, "无法载入可约时段"));
    }
  }, []);

  React.useEffect(() => {
    void load(start);
  }, [load, start]);

  async function toggle(date: string, time: string, open: boolean) {
    const key = date + time;
    if (busy) return;
    setBusy(key);
    setErr("");
    try {
      await postJSON("/api/assessor/availability", {
        date,
        slots: [{ time_slot: time, is_available: !open }],
      });
      setData((d) =>
        d
          ? {
              ...d,
              availability: {
                ...d.availability,
                [date]: { ...(d.availability[date] || {}), [time]: !open },
              },
            }
          : d,
      );
    } catch (e) {
      setErr(errorText(e, "保存失败"));
    } finally {
      setBusy("");
    }
  }

  return (
    <div>
      <div className="mb-2 flex items-center gap-2">
        <h3 className="text-[17px] font-bold">我的可约时段</h3>
        <Button variant="ghost" size="sm" className="ml-auto shadow-none" onClick={onClose}>
          关闭
        </Button>
      </div>
      <p className="mb-3 text-[12.5px] text-mute">默认跟随办公室开放；点格子可关闭或恢复。已排预约的时段请先在档案里改派。</p>
      <div className="mb-2 flex items-center gap-2">
        <Button variant="outline" size="sm" className="border-rule px-2 shadow-none" onClick={() => setStart(addDays(start, -7))}>
          上一周
        </Button>
        <b className="text-[13.5px]">{md(days[0])} – {md(days[6])}</b>
        <Button variant="outline" size="sm" className="border-rule px-2 shadow-none" onClick={() => setStart(addDays(start, 7))}>
          下一周
        </Button>
      </div>
      {err ? <p className="mb-2 text-[13px] text-attention">{err}</p> : null}
      {!data ? (
        <p className="text-[13px] text-mute">正在载入…</p>
      ) : (
        <div className="overflow-x-auto">
          <div className="grid min-w-[520px] grid-cols-[46px_repeat(7,minmax(0,1fr))] gap-0.5">
            <span />
            {days.map((d) => (
              <div key={d} className="border-b border-rule px-0.5 pb-1 text-center text-[12px] text-mute">
                {wdOf(d).slice(1)}
                <b className="block text-[15px] text-ink">{md(d)}</b>
              </div>
            ))}
            {TIMES.map((t) => (
              <React.Fragment key={t}>
                <span className="flex items-center text-[11.5px] text-mute">{t}</span>
                {days.map((d) => {
                  const closed = data.availability[d]?.[t] === false;
                  return (
                    <button
                      key={d + t}
                      type="button"
                      aria-label={d + " " + t + (closed ? " 不可约" : " 可约")}
                      className={cn(
                        "h-6 text-[11px]",
                        closed
                          ? "bg-[repeating-linear-gradient(135deg,hsl(var(--line))_0_2px,transparent_2px_6px)] text-mute"
                          : "bg-sunk hover:bg-ink hover:text-background",
                        busy === d + t && "opacity-50",
                      )}
                      onClick={() => void toggle(d, t, !closed)}
                    >
                      {closed ? "关" : ""}
                    </button>
                  );
                })}
              </React.Fragment>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
