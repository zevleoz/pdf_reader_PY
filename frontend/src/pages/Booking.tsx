import * as React from "react";
import { useSearchParams } from "react-router-dom";
import { CalendarClock, ChevronLeft, ChevronRight, Pencil, Send } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { errorText, getJSON, postJSON } from "@/lib/api";
import { useBoot } from "@/lib/boot";
import { cn } from "@/lib/utils";
import PageHeader from "@/shell/PageHeader";

import AssessorPanel from "./booking/AssessorPanel";
import HandoffPanel from "./booking/HandoffPanel";
import { SendPanel, SlotPanel, WeekPanel } from "./booking/Panels";
import {
  TIMES,
  addDays,
  bookable,
  dayKey,
  md,
  mondayOf,
  nextOpen,
  parseDay,
  slotKey,
  todayKey,
  updatedText,
  wdOf,
  type Loc,
  type Picked,
  type Slot,
  type StudentHit,
  type Week,
} from "./booking/model";

type Toast = { id: number; text: string; kind: "ok" | "error"; undo?: () => void };
function firstDayIdx(weekStart: string): number {
  const i = Math.round((parseDay(todayKey()).getTime() - parseDay(weekStart).getTime()) / 86400000);
  return i >= 0 && i <= 6 ? i : 0;
}
type Cell = { date: string; time: string };
type Change = Cell & { open: boolean };
type Paint = {
  pointerId: number;
  grid: HTMLDivElement;
  from: Cell;
  to: Cell;
  open: boolean;
  changes: Change[];
};

function readSlot(target: EventTarget | null) {
  const button = target instanceof Element ? target.closest<HTMLButtonElement>("button[data-office-slot]") : null;
  const date = button?.dataset.officeDate;
  const time = button?.dataset.officeSlot;
  return date && time ? { date, time } : null;
}

function between(value: string, a: string, b: string) {
  return a <= b ? value >= a && value <= b : value >= b && value <= a;
}

function Dots({ n, cap }: { n: number; cap: number }) {
  return (
    <>
      {Array.from({ length: cap }, (_, i) => (
        <i
          key={i}
          className={cn("size-1.5 rounded-full border-[1.3px] border-current", i < n && "bg-current")}
        />
      ))}
    </>
  );
}

export default function Booking() {
  const boot = useBoot();
  const isAdmin = boot.user.role === "admin";
  const canBook = boot.user.role === "admin" || boot.user.role === "advisor";
  const [params, setParams] = useSearchParams();
  const presetCode = params.get("student") || "";

  const [locs, setLocs] = React.useState<Loc[] | null>(null);
  const [locId, setLocId] = React.useState<number | null>(null);
  const [weekStart, setWeekStart] = React.useState(() => mondayOf(todayKey()));
  const [week, setWeek] = React.useState<Week | null>(null);
  const [ahead, setAhead] = React.useState<Slot[]>([]);
  const [failed, setFailed] = React.useState(false);
  const [sel, setSel] = React.useState<Cell | null>(null);
  const [picked, setPicked] = React.useState<Picked | null>(null);
  const [presetName, setPresetName] = React.useState("");
  const [send, setSend] = React.useState(false);
  const [edit, setEdit] = React.useState(false);
  const [handoffId, setHandoffId] = React.useState<number | null>(null);
  const [myAvail, setMyAvail] = React.useState(false);
  const [over, setOver] = React.useState<Record<string, boolean>>({});
  const [editNote, setEditNote] = React.useState("");
  const [dayIdx, setDayIdx] = React.useState(() => firstDayIdx(mondayOf(todayKey())));
  const [toasts, setToasts] = React.useState<Toast[]>([]);
  const toastId = React.useRef(0);
  const paint = React.useRef<Paint | null>(null);
  const savingAvailability = React.useRef(false);
  const reqId = React.useRef(0);

  const notify = React.useCallback((text: string, kind: "ok" | "error" = "ok", undo?: () => void) => {
    const id = ++toastId.current;
    setToasts((t) => [...t, { id, text, kind, undo }]);
    window.setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), undo ? 6000 : 3500);
  }, []);

  // 办公室
  React.useEffect(() => {
    getJSON<{ locations: Loc[] }>("/api/locations")
      .then((r) => {
        setLocs(r.locations || []);
        if (r.locations?.length) setLocId((cur) => cur ?? r.locations[0].id);
      })
      .catch(() => setFailed(true));
  }, []);

  const loc = locs?.find((l) => l.id === locId) || null;

  const load = React.useCallback(async () => {
    if (locId == null) return;
    const id = ++reqId.current;
    const thisMon = mondayOf(todayKey());
    try {
      const q = (s: string) => `/api/bookings/week?loc=${locId}&start=${s}`;
      const [w, a, b] = await Promise.all([
        getJSON<Week>(q(weekStart)),
        weekStart === thisMon ? Promise.resolve(null) : getJSON<Week>(q(thisMon)),
        getJSON<Week>(q(addDays(thisMon, 7))),
      ]);
      if (id !== reqId.current) return;
      setWeek(w);
      setAhead([...(a || w).slots, ...(weekStart === addDays(thisMon, 7) ? w : b).slots]);
      setFailed(false);
    } catch {
      if (id === reqId.current) setFailed(true);
    }
  }, [locId, weekStart]);

  React.useEffect(() => {
    setWeek((w) => (w && w.start === weekStart && w.location.id === locId ? w : null));
    void load();
  }, [load, weekStart, locId]);

  // 每 60 秒与窗口回到前台时刷新，让预约页上的新预约不用重载就出现
  React.useEffect(() => {
    const tick = () => {
      if (!paint.current && !savingAvailability.current && !document.hidden) void load();
    };
    const t = window.setInterval(tick, 60000);
    window.addEventListener("focus", tick);
    document.addEventListener("visibilitychange", tick);
    return () => {
      window.clearInterval(t);
      window.removeEventListener("focus", tick);
      document.removeEventListener("visibilitychange", tick);
    };
  }, [load]);

  // ?student=<code>：预选这位学生
  React.useEffect(() => {
    if (!presetCode) {
      setPresetName("");
      return;
    }
    let live = true;
    getJSON<{ students: StudentHit[] }>("/api/students/search?q=" + encodeURIComponent(presetCode))
      .then((r) => {
        const hit = (r.students || []).find((s) => s.student_code === presetCode);
        if (live && hit) {
          setPresetName(hit.name);
          setPicked({ code: hit.student_code, name: hit.name });
        }
      })
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, [presetCode]);

  function clearPreset() {
    setPresetName("");
    setPicked(null);
    const next = new URLSearchParams(params);
    next.delete("student");
    setParams(next, { replace: true });
  }

  const cap = week?.capacity ?? 4;
  const slotMap = React.useMemo(() => {
    const m = new Map<string, Slot>();
    week?.slots.forEach((s) => m.set(slotKey(s.date, s.time), s));
    return m;
  }, [week]);
  const days = Array.from({ length: 7 }, (_, i) => addDays(weekStart, i));
  const isOpen = (s: Slot) => over[slotKey(s.date, s.time)] ?? !s.closed;
  const selSlot = sel ? slotMap.get(slotKey(sel.date, sel.time)) || null : null;
  const chips = nextOpen(ahead.filter((s) => s.date >= todayKey()), cap, 3);

  function pickSlot(s: { date: string; time: string }) {
    setSend(false);
    setHandoffId(null);
    setMyAvail(false);
    setSel({ date: s.date, time: s.time });
    const mon = mondayOf(s.date);
    if (mon !== weekStart) {
      setWeekStart(mon);
      setDayIdx((parseDay(s.date).getDay() + 6) % 7);
    } else setDayIdx((parseDay(s.date).getDay() + 6) % 7);
  }

  function shiftWeek(n: number) {
    const next = addDays(weekStart, n);
    setWeekStart(next);
    setSel(null);
    setDayIdx(firstDayIdx(next));
  }

  async function sendBulk(changes: Change[]) {
    if (!loc || !changes.length || savingAvailability.current) return;
    savingAvailability.current = true;
    try {
      const r = await postJSON<{ refused?: Cell[] }>("/api/availability/bulk", { location_id: loc.id, changes });
      setEditNote(
        r.refused && r.refused.length
          ? "有预约的时段不能关闭：" + r.refused.map((x) => md(x.date) + " " + x.time).join("、")
          : "",
      );
    } catch (e) {
      notify(errorText(e, "保存失败"), "error");
    }
    await load();
    setOver({});
    savingAvailability.current = false;
  }

  function previewPaint(current: Paint, to: Cell) {
    current.to = to;
    const slots = week?.slots.filter((slot) => !slot.past
      && between(slot.date, current.from.date, to.date)
      && between(slot.time, current.from.time, to.time)
      && slot.closed === current.open) || [];
    current.changes = slots
      .filter((slot) => current.open || slot.count === 0)
      .map(({ date, time }) => ({ date, time, open: current.open }));
    setEditNote(!current.open && slots.some((slot) => slot.count > 0) ? "有预约的时段不能关闭" : "");
    setOver(Object.fromEntries(current.changes.map((change) => [slotKey(change.date, change.time), change.open])));
  }

  const stopPaint = React.useCallback(() => {
    const current = paint.current;
    if (!current) return null;
    paint.current = null;
    if (current.grid.hasPointerCapture(current.pointerId)) current.grid.releasePointerCapture(current.pointerId);
    return current;
  }, []);

  const cancelPaint = React.useCallback(() => {
    if (!stopPaint()) return;
    setOver({});
    setEditNote("");
  }, [stopPaint]);

  React.useEffect(() => {
    window.addEventListener("blur", cancelPaint);
    return () => window.removeEventListener("blur", cancelPaint);
  }, [cancelPaint]);
  React.useEffect(() => { if (!edit) cancelPaint(); }, [edit, cancelPaint]);

  function startPaint(event: React.PointerEvent<HTMLDivElement>) {
    if (!edit || event.button !== 0 || !event.isPrimary || savingAvailability.current || paint.current) return;
    const cell = readSlot(event.target);
    if (!cell) return;
    const slot = slotMap.get(slotKey(cell.date, cell.time));
    if (!slot || slot.past) return;
    const current = {
      pointerId: event.pointerId, grid: event.currentTarget,
      from: cell, to: cell, open: slot.closed, changes: [],
    };
    paint.current = current;
    event.currentTarget.setPointerCapture(event.pointerId);
    previewPaint(current, cell);
  }

  function movePaint(event: React.PointerEvent<HTMLDivElement>) {
    const current = paint.current;
    if (!current || current.pointerId !== event.pointerId) return;
    const hit = document.elementFromPoint(event.clientX, event.clientY);
    const cell = current.grid.contains(hit) ? readSlot(hit) : null;
    if (cell && (current.to.date !== cell.date || current.to.time !== cell.time)) previewPaint(current, cell);
  }

  function finishPaint(event: React.PointerEvent<HTMLDivElement>) {
    if (paint.current?.pointerId !== event.pointerId) return;
    movePaint(event);
    const current = stopPaint();
    if (current) void sendBulk(current.changes);
  }

  const paintHandlers = {
    onPointerDown: startPaint, onPointerMove: movePaint, onPointerUp: finishPaint,
    onPointerCancel: (event: React.PointerEvent<HTMLDivElement>) => {
      if (paint.current?.pointerId === event.pointerId) cancelPaint();
    },
    onLostPointerCapture: (event: React.PointerEvent<HTMLDivElement>) => {
      if (paint.current?.pointerId === event.pointerId) cancelPaint();
    },
  };

  function toggleDay(s: Slot) {
    if (!edit || s.past || savingAvailability.current) return;
    if (isOpen(s) && s.count > 0) {
      setEditNote("有预约的时段不能关闭");
      return;
    }
    setEditNote("");
    const open = !isOpen(s);
    setOver((o) => ({ ...o, [slotKey(s.date, s.time)]: open }));
    void sendBulk([{ date: s.date, time: s.time, open }]);
  }

  function onBooked(id: number, label: string) {
    setSel(null);
    setPicked(null);
    setHandoffId(id);
    if (presetCode) clearPreset();
    notify("已预约 " + label, "ok", async () => {
      try {
        await postJSON("/api/booking/" + id + "/cancel");
        setHandoffId(null);
        notify("已撤销");
      } catch (e) {
        notify(errorText(e, "撤销失败"), "error");
      }
      void load();
    });
    void load();
  }

  const multi = (locs?.length || 0) > 1;
  const sub = loc ? [loc.name, updatedText(week?.location.updated_at)].filter(Boolean).join(" · ") : "";
  const range = md(days[0]) + " – " + md(days[6]);

  const actions = (
    <div className="flex flex-wrap gap-2">
      {isAdmin ? (
        <Button
          variant={edit ? "default" : "outline"}
          className={cn("shadow-none", !edit && "border-rule")}
          onClick={() => {
            setEdit(!edit);
            setSel(null);
            setSend(false);
            setHandoffId(null);
            setMyAvail(false);
            setEditNote("");
          }}
        >
          <Pencil />
          {edit ? "完成编辑" : "编辑开放时段"}
        </Button>
      ) : null}
      {boot.user.is_assessor ? (
        <Button
          variant={myAvail ? "default" : "outline"}
          className={cn("shadow-none", !myAvail && "border-rule")}
          onClick={() => {
            setMyAvail(!myAvail);
            setSel(null);
            setSend(false);
            setHandoffId(null);
            setEdit(false);
          }}
        >
          <CalendarClock />
          我的可约时段
        </Button>
      ) : null}
      <Button
        className="shadow-none"
        onClick={() => {
          setSend(true);
          setSel(null);
          setEdit(false);
          setHandoffId(null);
          setMyAvail(false);
        }}
        disabled={!loc}
      >
        <Send />
        发送预约页
      </Button>
    </div>
  );

  const slotBtn = (s: Slot) => {
    const key = slotKey(s.date, s.time);
    const open = isOpen(s);
    const sCap = s.capacity ?? cap;
    const full = open && s.count >= sCap && !edit;
    const on = sel?.date === s.date && sel?.time === s.time;
    const label = `${md(s.date)} ${s.time}`;
    const names = (s.assessors || []).map((a) => a.display_name).join("、");
    if (s.past)
      return (
        <button key={key} disabled aria-label={label + " 不可预约"} className="flex h-7 cursor-not-allowed items-center justify-center gap-[3px] opacity-30">
          <Dots n={s.count} cap={sCap} />
        </button>
      );
    if (!open)
      return (
        <button
          key={key}
          aria-label={label + " 未开放"}
          data-office-date={s.date}
          data-office-slot={s.time}
          className={cn(
            "flex h-7 items-center justify-center",
            edit
              ? "touch-none cursor-cell bg-[repeating-linear-gradient(135deg,hsl(var(--line))_0_2px,transparent_2px_6px)]"
              : "cursor-default after:h-px after:w-3 after:bg-line",
          )}
          onClick={(event) => { if (event.detail === 0) toggleDay(s); }}
        />
      );
    return (
      <button
        key={key}
        aria-label={`${label}，已约 ${s.count} 人，余 ${sCap - s.count}${names ? "，可约老师 " + names : ""}`}
        title={names ? "可约老师：" + names : undefined}
        data-office-date={s.date}
        data-office-slot={s.time}
        className={cn(
          "flex h-7 items-center justify-center gap-[3px] transition-colors",
          on ? "bg-hl text-white" : full ? "cursor-default bg-sunk" : "bg-sunk hover:bg-ink hover:text-background",
          edit && "touch-none cursor-cell shadow-[inset_0_0_0_1.5px_hsl(var(--ink))]",
        )}
        onClick={(event) => {
          if (!edit) pickSlot(s);
          else if (event.detail === 0) toggleDay(s);
        }}
      >
        <Dots n={s.count} cap={sCap} />
      </button>
    );
  };

  const today = todayKey();
  const dayDate = days[dayIdx] || days[0];

  return (
    <div>
      <PageHeader title="预约" sub={sub} actions={actions} />

      {failed && !week ? <p className="mb-3 text-attention">无法载入预约数据，请稍后刷新。</p> : null}

      {multi ? (
        <div className="mb-3.5 flex flex-wrap gap-1 bg-sunk p-1 w-fit" role="tablist">
          {locs!.map((l) => (
            <button
              key={l.id}
              role="tab"
              aria-selected={l.id === locId}
              className={cn("px-3 py-1.5 text-[13.5px] font-semibold", l.id === locId ? "bg-ink text-background" : "hover:bg-line")}
              onClick={() => {
                setLocId(l.id);
                setSel(null);
              }}
            >
              {l.name}
            </button>
          ))}
        </div>
      ) : null}

      {presetName ? (
        <div className="mb-3 flex items-center gap-2.5 bg-tint px-3 py-2 text-[13.5px]">
          <span>
            正在为 <b>{presetName}</b> 找时段
          </span>
          <Button variant="outline" size="sm" className="ml-auto border-rule shadow-none" onClick={clearPreset}>
            取消
          </Button>
        </div>
      ) : null}

      <div className="grid grid-cols-1 gap-6 md:grid-cols-[minmax(0,1fr)_330px] min-[1180px]:grid-cols-[minmax(0,1fr)_372px] md:items-start">
        <div className="min-w-0">
          <div className="mb-3.5 flex flex-wrap items-center gap-2">
            <span className="text-[13px] font-semibold text-ink-2">最近可约</span>
            {chips.length === 0 ? <span className="text-[13px] text-mute">{week ? "近两周没有空位" : ""}</span> : null}
            {chips.map((s) => (
              <button
                key={slotKey(s.date, s.time)}
                type="button"
                className="inline-flex items-baseline gap-1.5 bg-sunk px-[11px] py-1.5 text-[14px] font-bold hover:bg-ink hover:text-background"
                onClick={() => pickSlot(s)}
              >
                {md(s.date)} {wdOf(s.date)} {s.time}
                <small className="text-[12.5px] font-medium opacity-70">余 {cap - s.count}</small>
              </button>
            ))}
          </div>

          {edit ? (
            <div className="mb-2.5 flex flex-wrap items-center gap-2.5 bg-tint px-3 py-2 text-[13.5px]">
              <span>点按一个格子，或按住拖选一段时段。修改立刻出现在发出去的预约页上。</span>
              {editNote ? <b className="text-attention">{editNote}</b> : null}
              <Button size="sm" className="ml-auto shadow-none" onClick={() => setEdit(false)}>
                完成编辑
              </Button>
            </div>
          ) : null}

          <div className="mb-2 flex items-center gap-2">
            <Button variant="outline" size="sm" className="border-rule px-2 shadow-none" aria-label="上一周" onClick={() => shiftWeek(-7)}>
              <ChevronLeft />
            </Button>
            <b className="text-[15px]">{range}</b>
            <Button variant="outline" size="sm" className="border-rule px-2 shadow-none" aria-label="下一周" onClick={() => shiftWeek(7)}>
              <ChevronRight />
            </Button>
            <span className="ml-auto hidden items-center gap-2.5 text-[12.5px] text-mute md:flex">
              <span className="inline-flex items-center gap-1 text-ink">
                <Dots n={0} cap={1} />
                <span className="text-mute">空位</span>
              </span>
              <span className="inline-flex items-center gap-1 text-ink">
                <Dots n={1} cap={1} />
                <span className="text-mute">已约</span>
              </span>
            </span>
          </div>

          {!week ? (
            <Skeleton className="h-[420px] w-full" />
          ) : (
            <>
              <div className="hidden select-none grid-cols-[50px_repeat(7,minmax(0,1fr))] gap-0.5 md:grid" {...paintHandlers}>
                <span />
                {days.map((d) => (
                  <div key={d} className="mb-0.5 border-b border-rule px-0.5 pb-1.5 pt-1 text-[12.5px] leading-tight text-mute">
                    {wdOf(d)}
                    <b className={cn("block text-[19px] font-bold tracking-tight", d === today ? "text-hl" : "text-ink")}>
                      {parseDay(d).getDate()}
                    </b>
                  </div>
                ))}
                {TIMES.map((t) => (
                  <React.Fragment key={t}>
                    <span className="flex items-center text-[12px] font-medium text-mute">{t}</span>
                    {days.map((d) => {
                      const s = slotMap.get(slotKey(d, t));
                      return s ? slotBtn(s) : <span key={d} />;
                    })}
                  </React.Fragment>
                ))}
              </div>

              <div className="md:hidden">
                <div className="mb-2.5 grid grid-cols-7 gap-[3px]">
                  {days.map((d, i) => (
                    <button
                      key={d}
                      type="button"
                      className={cn(
                        "py-[5px] text-center text-[11.5px] leading-tight",
                        i === dayIdx ? "bg-ink text-background" : "text-mute hover:bg-sunk",
                      )}
                      onClick={() => {
                        setDayIdx(i);
                        setSel(null);
                      }}
                    >
                      {wdOf(d).slice(1)}
                      <b className={cn("block text-[15px]", i === dayIdx ? "text-inherit" : "text-ink")}>{parseDay(d).getDate()}</b>
                    </button>
                  ))}
                </div>
                <div className="grid grid-cols-3 gap-1" {...paintHandlers}>
                  {TIMES.map((t) => {
                    const s = slotMap.get(slotKey(dayDate, t));
                    if (!s) return null;
                    const open = isOpen(s);
                    const sCap = s.capacity ?? cap;
                    const left = sCap - s.count;
                    const on = sel?.date === s.date && sel?.time === s.time;
                    const dis = s.past || (!edit && (!open || left <= 0));
                    return (
                      <button
                        key={t}
                        type="button"
                        disabled={dis && !(edit && !s.past)}
                        data-office-date={s.date}
                        data-office-slot={s.time}
                        className={cn(
                          "flex h-[46px] flex-col items-center justify-center text-[13px] font-semibold leading-tight shadow-[inset_0_0_0_1px_hsl(var(--line))] disabled:opacity-30",
                          edit && "touch-none",
                          on && "bg-ink text-background",
                          !open && "bg-[repeating-linear-gradient(135deg,hsl(var(--line))_0_2px,transparent_2px_6px)] shadow-none",
                        )}
                        onClick={(event) => {
                          if (!edit) pickSlot(s);
                          else if (event.detail === 0) toggleDay(s);
                        }}
                      >
                        {t}
                        <small className="text-[11.5px] font-normal opacity-70">{open ? "余 " + Math.max(0, left) : "未开放"}</small>
                      </button>
                    );
                  })}
                </div>
              </div>
            </>
          )}
        </div>

        <aside
          className={cn(
            "md:sticky md:top-4",
            (selSlot || send || handoffId || myAvail) &&
              "max-md:fixed max-md:inset-x-0 max-md:bottom-0 max-md:z-40 max-md:max-h-[72vh] max-md:overflow-auto max-md:bg-background max-md:p-4 max-md:shadow-[0_-14px_34px_-14px_rgba(0,0,0,.4)]",
          )}
        >
          {send && loc && locs ? (
            <SendPanel locs={locs} loc={loc} setLoc={(id) => setLocId(id)} onClose={() => setSend(false)} notify={notify} />
          ) : handoffId ? (
            <HandoffPanel bookingId={handoffId} onClose={() => setHandoffId(null)} />
          ) : myAvail ? (
            <AssessorPanel onClose={() => setMyAvail(false)} />
          ) : selSlot && loc ? (
            <SlotPanel
              slot={selSlot}
              cap={cap}
              loc={loc}
              canBook={canBook}
              picked={picked}
              setPicked={setPicked}
              onBooked={onBooked}
              requesterDefault={boot.user.display_name}
              onClose={() => {
                setSel(null);
                if (!presetCode) setPicked(null);
              }}
            />
          ) : week && loc ? (
            <WeekPanel
              slots={week.slots}
              cap={cap}
              locName={loc.name}
              onJump={(s) => {
                setHandoffId(null);
                setMyAvail(false);
                setSel({ date: s.date, time: s.time });
              }}
              onOpenBooking={(id) => {
                setSel(null);
                setSend(false);
                setMyAvail(false);
                setHandoffId(id);
              }}
            />
          ) : null}
        </aside>
      </div>

      <div className="fixed bottom-4 left-4 right-4 z-[60] flex flex-col gap-2 sm:right-auto sm:max-w-sm" aria-live="polite">
        {toasts.map((t) => (
          <div
            key={t.id}
            role="status"
            className={cn(
              "flex items-center gap-3 border bg-background px-4 py-3 text-sm",
              t.kind === "error" ? "border-attention text-attention" : "border-rule",
            )}
          >
            <span className="flex-1">{t.text}</span>
            {t.undo ? (
              <button
                type="button"
                className="font-semibold text-hl underline-offset-2 hover:underline"
                onClick={() => {
                  t.undo?.();
                  setToasts((x) => x.filter((y) => y.id !== t.id));
                }}
              >
                撤销
              </button>
            ) : null}
          </div>
        ))}
      </div>
    </div>
  );
}
