import * as React from "react";
import { Search } from "lucide-react";

import { Button } from "@/components/ui/button";
import { errorText, getJSON, postJSON } from "@/lib/api";
import { cn } from "@/lib/utils";

import { md, wdOf, type Loc, type Picked, type Slot, type StudentHit } from "./model";

const RULE = "需提前一天预约 · 每时段最多 4 人 · 可选未来 30 天";

function Mark({ name }: { name: string }) {
  return (
    <span className="grid size-6 shrink-0 place-items-center bg-ink text-[11px] font-bold text-background" aria-hidden>
      {name.slice(0, 1)}
    </span>
  );
}

/** 右侧：选了时段后的表单（原型 sideHTML 的 S.slot 分支）。 */
export function SlotPanel({
  slot,
  cap,
  loc,
  canBook,
  picked,
  setPicked,
  onBooked,
  onClose,
}: {
  slot: Slot;
  cap: number;
  loc: Loc;
  canBook: boolean;
  picked: Picked | null;
  setPicked: (p: Picked | null) => void;
  onBooked: (id: number, label: string) => void;
  onClose: () => void;
}) {
  const [q, setQ] = React.useState("");
  const [hits, setHits] = React.useState<StudentHit[]>([]);
  const [busy, setBusy] = React.useState(false);
  const [err, setErr] = React.useState("");
  const left = cap - slot.count;
  const hidden = Math.max(0, slot.count - slot.bookings.length);

  React.useEffect(() => {
    setQ("");
    setErr("");
  }, [slot.date, slot.time]);

  React.useEffect(() => {
    const kw = q.trim();
    if (!kw || picked) {
      setHits([]);
      return;
    }
    let live = true;
    const t = window.setTimeout(() => {
      getJSON<{ students: StudentHit[] }>("/api/students/search?q=" + encodeURIComponent(kw))
        .then((r) => live && setHits(r.students || []))
        .catch(() => live && setHits([]));
    }, 180);
    return () => {
      live = false;
      window.clearTimeout(t);
    };
  }, [q, picked]);

  async function confirm() {
    if (!picked || busy) return;
    setBusy(true);
    setErr("");
    try {
      const body: Record<string, unknown> = {
        location_id: loc.id,
        appointment_time: slot.date + "T" + slot.time + ":00",
      };
      if ("isNew" in picked) body.new_name = picked.name;
      else body.student_code = picked.code;
      const r = await postJSON<{ ok: boolean; booking_id: number }>("/api/bookings/staff", body);
      onBooked(r.booking_id, picked.name + " · " + md(slot.date) + " " + slot.time);
    } catch (e) {
      setErr(errorText(e, "预约失败"));
    } finally {
      setBusy(false);
    }
  }

  const seats: React.ReactNode[] = slot.bookings.map((b) => (
    <span key={b.id} className="flex items-center gap-2 bg-sunk px-2.5 py-1.5 text-[13.5px] font-semibold">
      <Mark name={b.student_name} />
      {b.student_name}
      <small className="font-normal text-mute">{b.student_code}</small>
    </span>
  ));
  for (let i = 0; i < hidden; i++)
    seats.push(
      <span key={"h" + i} className="bg-sunk px-2.5 py-1.5 text-[13.5px] text-mute">
        已约
      </span>,
    );
  for (let i = 0; i < Math.max(0, left); i++)
    seats.push(
      <span key={"f" + i} className="border border-dashed border-line px-2.5 py-1.5 text-[13.5px] text-mute">
        空位
      </span>,
    );

  return (
    <div>
      <h3 className="text-[17px] font-bold">
        {md(slot.date)} {wdOf(slot.date)} {slot.time}
      </h3>
      <p className="mb-3 mt-1 text-[13px] text-mute">
        {loc.name} · 已约 {slot.count} / {cap}
      </p>
      <div className="mb-3 flex flex-col gap-1.5">{seats}</div>
      {left <= 0 ? (
        <div className="bg-tint px-3 py-2 text-[13.5px]">这个时段已满。试试其他时段。</div>
      ) : !canBook ? null : (
        <>
          <label className="flex items-center gap-2 border border-line px-2.5 focus-within:border-rule">
            <Search className="size-4 text-mute" />
            <input
              className="h-10 min-w-0 flex-1 bg-transparent text-[14px] outline-none"
              placeholder="找学生：姓名、编号、学校"
              autoComplete="off"
              value={picked ? picked.name : q}
              onChange={(e) => {
                if (picked) setPicked(null);
                setQ(e.target.value);
              }}
            />
          </label>
          {!picked && q.trim() ? (
            <div className="mt-1 flex flex-col border border-line">
              {hits.slice(0, 6).map((s) => (
                <button
                  key={s.student_code + s.name}
                  type="button"
                  className="flex items-center gap-2 px-2.5 py-2 text-left hover:bg-sunk"
                  onClick={() => setPicked({ code: s.student_code, name: s.name })}
                >
                  <Mark name={s.name} />
                  <b className="text-[14px]">{s.name}</b>
                  <small className="text-mute">
                    {s.student_code}
                    {s.advisor_name ? " · " + s.advisor_name : ""}
                  </small>
                </button>
              ))}
              {hits.length === 0 ? (
                <button
                  type="button"
                  className="flex flex-col px-2.5 py-2 text-left hover:bg-sunk"
                  onClick={() => setPicked({ code: "", name: q.trim(), isNew: true })}
                >
                  <b className="text-[14px]">“{q.trim()}”</b>
                  <small className="text-mute">按这个名字预约</small>
                </button>
              ) : null}
            </div>
          ) : null}
          {err ? <p className="mt-2 text-[13px] text-attention">{err}</p> : null}
          <div className="mt-3 flex gap-2">
            <Button className="flex-1 shadow-none" disabled={!picked || busy} onClick={confirm}>
              预约这个时段
            </Button>
            <Button variant="outline" className="border-rule shadow-none" onClick={onClose}>
              取消
            </Button>
          </div>
        </>
      )}
      {left <= 0 || !canBook ? (
        <Button variant="outline" className="mt-3 border-rule shadow-none" onClick={onClose}>
          关闭
        </Button>
      ) : null}
    </div>
  );
}

/** 右侧默认：本周预约 + 规则行。 */
export function WeekPanel({
  slots,
  cap,
  locName,
  onJump,
}: {
  slots: Slot[];
  cap: number;
  locName: string;
  onJump: (s: Slot) => void;
}) {
  void cap;
  const rows: { key: string; slot: Slot; name: string | null; code?: string }[] = [];
  for (const s of slots) {
    s.bookings.forEach((b) => rows.push({ key: "b" + b.id, slot: s, name: b.student_name, code: b.student_code }));
    const hidden = s.count - s.bookings.length;
    if (hidden > 0) rows.push({ key: "h" + s.date + s.time, slot: s, name: null });
  }
  return (
    <div>
      <h2 className="mb-2 text-[17px] font-bold">
        本周预约<small className="ml-2 text-[13px] font-normal text-mute">{locName}</small>
      </h2>
      <div className="max-h-[380px] overflow-auto">
        {rows.length === 0 ? (
          <p className="text-mute">这一周还没有预约。</p>
        ) : (
          rows.map((r) => (
            <button
              key={r.key}
              type="button"
              className="flex w-full items-center gap-2.5 border-b border-line py-2 text-left hover:bg-sunk"
              onClick={() => onJump(r.slot)}
            >
              <Mark name={r.name || "·"} />
              <span className="min-w-0 flex-1">
                <b className="block truncate text-[14px]">{r.name || "已约 " + (r.slot.count - r.slot.bookings.length) + " 人"}</b>
                {r.code ? <small className="text-mute">{r.code}</small> : null}
              </span>
              <span className="text-right font-mono text-[12.5px] text-mute">
                {md(r.slot.date)} {wdOf(r.slot.date)}
                <br />
                {r.slot.time}
              </span>
            </button>
          ))
        )}
      </div>
      <p className="mt-3 text-[12.5px] text-mute">{RULE}</p>
    </div>
  );
}

/** 右侧：发送预约页（iframe 预览 + 话术）。 */
export function SendPanel({
  locs,
  loc,
  setLoc,
  onClose,
  notify,
}: {
  locs: Loc[];
  loc: Loc;
  setLoc: (id: number) => void;
  onClose: () => void;
  notify: (t: string, kind?: "ok" | "error") => void;
}) {
  const url = window.location.origin + "/booking?loc=" + loc.id;
  const msg = `您好，这是 Y4 测评的预约页（${loc.name}）。请选择日期和时间，填写学生姓名后提交，需提前一天预约。\n${url}`;
  async function copy() {
    try {
      await navigator.clipboard.writeText(msg);
      notify("已复制");
    } catch {
      notify("浏览器不允许复制，请手动选择文字", "error");
    }
  }
  return (
    <div>
      <div className="mb-3 flex items-center gap-2">
        <h3 className="text-[17px] font-bold">发送预约页</h3>
        <Button variant="ghost" size="sm" className="ml-auto shadow-none" onClick={onClose}>
          关闭
        </Button>
      </div>
      {locs.length > 1 ? (
        <select
          aria-label="办公室"
          className="mb-3 h-9 w-full border border-line bg-background px-2 text-[14px]"
          value={loc.id}
          onChange={(e) => setLoc(Number(e.target.value))}
        >
          {locs.map((l) => (
            <option key={l.id} value={l.id}>
              {l.name}
            </option>
          ))}
        </select>
      ) : null}
      <iframe
        key={loc.id}
        title="预约页预览"
        src={"/booking?loc=" + loc.id}
        className="mx-auto mb-3 block h-[520px] w-[360px] max-w-full border border-line bg-background"
      />
      <p className="mb-2 text-[12.5px] text-mute">这是发出去的页面，可以直接试。提交后左边日历会更新。公司老师和家长用同一个链接。</p>
      <div className={cn("mb-3 whitespace-pre-wrap break-all bg-sunk p-3 text-[13.5px] leading-relaxed")}>{msg}</div>
      <Button className="w-full shadow-none" onClick={copy}>
        复制链接和话术
      </Button>
    </div>
  );
}
