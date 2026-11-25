import * as React from "react";

import { Button } from "@/components/ui/button";
import { errorText, getJSON, postJSON } from "@/lib/api";
import { cn } from "@/lib/utils";

import { addDays, md, todayKey, wdOf } from "./model";

type Availability = Record<string, Record<string, boolean>>;
type Avail = {
  time_slots: string[];
  availability: Availability;
  offices?: { id: number; name: string }[];
  office_id?: number | null;
};
type Cell = { day: number; slot: number };
type Range = { from: Cell; to: Cell; open: boolean };

function readCell(target: EventTarget | null): Cell | null {
  const cell = target instanceof Element ? target.closest<HTMLElement>("[data-availability-day]") : null;
  return cell ? { day: Number(cell.dataset.availabilityDay), slot: Number(cell.dataset.availabilitySlot) } : null;
}

function within(index: number, a: number, b: number) {
  return index >= Math.min(a, b) && index <= Math.max(a, b);
}

export default function AssessorPanel({ onClose }: { onClose: () => void }) {
  const [data, setData] = React.useState<Avail | null>(null);
  const [start, setStart] = React.useState(todayKey());
  const [busy, setBusy] = React.useState(false);
  const [err, setErr] = React.useState("");
  const [reload, setReload] = React.useState(0);
  const [officeId, setOfficeId] = React.useState<number | null>(null);
  const [preview, setPreview] = React.useState<Range | null>(null);
  const gesture = React.useRef<{ pointer: number; range: Range } | null>(null);
  const keyboardAnchor = React.useRef<Cell | null>(null);
  const grid = React.useRef<HTMLDivElement>(null);
  const days = Array.from({ length: 7 }, (_, i) => addDays(start, i));

  React.useEffect(() => {
    let active = true;
    const query = "/api/assessor/availability?start=" + start + "&days=7"
      + (officeId == null ? "" : "&location_id=" + officeId);
    getJSON<Avail>(query)
      .then((result) => {
        if (!active) return;
        setData(result);
        if (officeId == null && result.office_id != null) setOfficeId(result.office_id);
      })
      .catch((e) => { if (active) setErr(errorText(e, "无法载入可约时段")); });
    return () => { active = false; };
  }, [start, reload, officeId]);

  const cancel = React.useCallback(() => {
    const pointer = gesture.current?.pointer;
    gesture.current = null;
    setPreview(null);
    if (pointer !== undefined && grid.current?.hasPointerCapture(pointer)) {
      grid.current.releasePointerCapture(pointer);
    }
  }, []);

  React.useEffect(() => {
    window.addEventListener("blur", cancel);
    return () => window.removeEventListener("blur", cancel);
  }, [cancel]);

  function changeWeek(offset: number) {
    cancel();
    setData(null);
    setErr("");
    keyboardAnchor.current = null;
    if (offset) setStart(addDays(start, offset));
    else setReload((value) => value + 1);
  }

  function opens(cell: Cell) {
    return !!data && data.availability[days[cell.day]]?.[data.time_slots[cell.slot]] === false;
  }

  async function save(range: Range) {
    if (!data || busy) return;
    setBusy(true);
    setErr("");
    const selected = days.flatMap((date, day) => {
      if (!within(day, range.from.day, range.to.day)) return [];
      const slots = data.time_slots.flatMap((time, slot) =>
        within(slot, range.from.slot, range.to.slot)
          ? [{ time_slot: time, is_available: range.open }]
          : [],
      );
      return [{ date, slots }];
    });
    const results = await Promise.allSettled(
      selected.map((payload) =>
        postJSON<{ availability: Availability }>("/api/assessor/availability", { ...payload, location_id: officeId }),
      ),
    );
    const saved: Availability = {};
    const failed: string[] = [];
    results.forEach((result, i) => {
      if (result.status === "fulfilled") Object.assign(saved, result.value.availability);
      else failed.push(md(selected[i].date) + " " + errorText(result.reason, "保存失败，请重试"));
    });
    setData({ ...data, availability: { ...data.availability, ...saved } });
    setErr(failed.join("；"));
    setBusy(false);
  }

  function startRange(event: React.PointerEvent<HTMLDivElement>) {
    if (event.button !== 0 || !event.isPrimary || gesture.current || busy) return;
    const cell = readCell(event.target);
    if (!cell) return;
    const range = { from: cell, to: cell, open: opens(cell) };
    gesture.current = { pointer: event.pointerId, range };
    keyboardAnchor.current = cell;
    setPreview(range);
    event.currentTarget.setPointerCapture(event.pointerId);
  }

  function moveRange(event: React.PointerEvent<HTMLDivElement>) {
    const current = gesture.current;
    if (!current || current.pointer !== event.pointerId) return;
    const cell = readCell(document.elementFromPoint(event.clientX, event.clientY));
    if (!cell || (cell.day === current.range.to.day && cell.slot === current.range.to.slot)) return;
    const range = { ...current.range, to: cell };
    gesture.current = { pointer: current.pointer, range };
    setPreview(range);
  }

  function finishRange(event: React.PointerEvent<HTMLDivElement>) {
    if (gesture.current?.pointer !== event.pointerId) return;
    moveRange(event);
    const range = gesture.current.range;
    cancel();
    void save(range);
  }

  return (
    <div>
      <div className="mb-2 flex items-center gap-2">
        <h3 className="text-[17px] font-bold">我的可约时段</h3>
        <Button variant="ghost" size="sm" className="ml-auto shadow-none" disabled={busy} onClick={onClose}>
          关闭
        </Button>
      </div>
      <p className="mb-3 text-[12.5px] text-mute">点按一个格子，或按住拖选一段时段。松开后按起始格的状态统一开放或关闭。新增授权的办公室需要先在这里开放时段。</p>
      {data?.offices && data.offices.length > 1 ? (
        <div className="mb-2 flex flex-wrap items-center gap-1.5">
          <span className="mr-1 text-[12.5px] text-mute">办公室</span>
          {data.offices.map((office) => (
            <button
              key={office.id}
              type="button"
              disabled={busy}
              onClick={() => {
                if (office.id === officeId) return;
                cancel();
                setData(null);
                setErr("");
                setOfficeId(office.id);
              }}
              className={cn(
                "h-7 border px-2 text-[12.5px]",
                office.id === officeId ? "border-ink bg-ink text-background" : "border-rule bg-background hover:bg-sunk",
              )}
            >
              {office.name}
            </button>
          ))}
        </div>
      ) : null}
      <div className="mb-2 flex items-center gap-2">
        <Button variant="outline" size="sm" className="border-rule px-2 shadow-none" disabled={busy} onClick={() => changeWeek(-7)}>
          上一周
        </Button>
        <b className="text-[13.5px]">{md(days[0])} – {md(days[6])}</b>
        <Button variant="outline" size="sm" className="border-rule px-2 shadow-none" disabled={busy} onClick={() => changeWeek(7)}>
          下一周
        </Button>
        {busy ? <span role="status" className="text-xs text-mute">保存中…</span> : null}
      </div>
      {err ? <p role="alert" className="mb-2 text-[13px] text-attention">{err}</p> : null}
      {!data ? (
        err ? <Button variant="outline" size="sm" onClick={() => changeWeek(0)}>重试</Button>
          : <p className="text-[13px] text-mute">正在载入…</p>
      ) : (
        <div className="overflow-x-auto">
          <div
            ref={grid}
            aria-busy={busy}
            className="grid min-w-[272px] select-none grid-cols-[36px_repeat(7,minmax(0,1fr))] gap-0.5 sm:grid-cols-[46px_repeat(7,minmax(0,1fr))]"
            onPointerDown={startRange}
            onPointerMove={moveRange}
            onPointerUp={finishRange}
            onPointerCancel={(event) => { if (gesture.current?.pointer === event.pointerId) cancel(); }}
            onLostPointerCapture={(event) => { if (gesture.current?.pointer === event.pointerId) cancel(); }}
          >
            <span />
            {days.map((date) => (
              <div key={date} className="border-b border-rule px-0.5 pb-1 text-center text-[12px] text-mute">
                {wdOf(date).slice(1)}
                <b className="block text-[13px] text-ink sm:text-[15px]">{md(date)}</b>
              </div>
            ))}
            {data.time_slots.map((time, slot) => (
              <React.Fragment key={time}>
                <span className="flex items-center text-[11.5px] text-mute">{time}</span>
                {days.map((date, day) => {
                  const selected = preview && within(day, preview.from.day, preview.to.day)
                    && within(slot, preview.from.slot, preview.to.slot);
                  const closed = selected ? !preview?.open : data.availability[date]?.[time] === false;
                  return (
                    <button
                      key={date}
                      type="button"
                      disabled={busy}
                      data-availability-day={day}
                      data-availability-slot={slot}
                      aria-label={date + " " + time + (closed ? " 不可约" : " 可约")}
                      aria-pressed={!closed}
                      className={cn(
                        "h-8 touch-none text-[11px] outline-offset-[-2px] focus-visible:outline focus-visible:outline-2 focus-visible:outline-ink sm:h-7",
                        closed
                          ? "bg-[repeating-linear-gradient(135deg,hsl(var(--line))_0_2px,transparent_2px_6px)] text-mute"
                          : "bg-sunk hover:bg-ink hover:text-background",
                        selected && "ring-2 ring-inset ring-hl",
                      )}
                      onClick={(event) => {
                        if (event.detail !== 0) return;
                        const to = { day, slot };
                        const from = (event.shiftKey && keyboardAnchor.current) || to;
                        keyboardAnchor.current = to;
                        void save({ from, to, open: opens(from) });
                      }}
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
