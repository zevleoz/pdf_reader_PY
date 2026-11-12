export type Loc = { id: number; name: string };
export type SlotBooking = { id: number; student_name: string; student_code: string; status: string };
export type Slot = {
  date: string;
  time: string;
  closed: boolean;
  past: boolean;
  count: number;
  bookings: SlotBooking[];
};
export type Week = {
  ok: boolean;
  start: string;
  capacity: number;
  location: { id: number; name: string; updated_at: string | null };
  slots: Slot[];
};
export type StudentHit = { name: string; student_code: string; school: string; advisor_name: string };
export type Picked = { code: string; name: string } | { code: ""; name: string; isNew: true };

export const TIMES = [
  "09:00", "09:30", "10:00", "10:30", "11:00",
  "13:00", "13:30", "14:00", "14:30", "15:00",
  "15:30", "16:00", "16:30", "17:00",
];
export const WD = ["周日", "周一", "周二", "周三", "周四", "周五", "周六"];

export const slotKey = (date: string, time: string) => date + "|" + time;

export function parseDay(s: string): Date {
  const [y, m, d] = s.split("-").map(Number);
  return new Date(y, m - 1, d);
}
export function dayKey(d: Date): string {
  const p = (n: number) => (n < 10 ? "0" : "") + n;
  return d.getFullYear() + "-" + p(d.getMonth() + 1) + "-" + p(d.getDate());
}
export function addDays(s: string, n: number): string {
  const d = parseDay(s);
  d.setDate(d.getDate() + n);
  return dayKey(d);
}
export function mondayOf(s: string): string {
  const d = parseDay(s);
  return addDays(s, -((d.getDay() + 6) % 7));
}
export const todayKey = () => dayKey(new Date());
export const md = (s: string) => {
  const d = parseDay(s);
  return d.getMonth() + 1 + "/" + d.getDate();
};
export const wdOf = (s: string) => WD[parseDay(s).getDay()];

/** 服务端给的是不带时区的 UTC 时间。 */
export function updatedText(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(iso) ? iso : iso + "Z");
  if (isNaN(d.getTime())) return "";
  const p = (n: number) => (n < 10 ? "0" : "") + n;
  const hm = p(d.getHours()) + ":" + p(d.getMinutes());
  const same = dayKey(d) === todayKey();
  return (same ? "今天 " : d.getMonth() + 1 + " 月 " + d.getDate() + " 日 ") + hm + " 已更新";
}

export function bookable(s: Slot, cap: number): boolean {
  return !s.past && !s.closed && s.count < cap;
}

export function nextOpen(slots: Slot[], cap: number, n: number): Slot[] {
  return slots.filter((s) => bookable(s, cap)).slice(0, n);
}
