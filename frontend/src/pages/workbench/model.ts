import type { Progress } from "@/lib/progress";

export type Who = { id: number; code: string; name: string };
export type Job = {
  running: boolean;
  status: string;
  percent: number;
  message: string;
  filename: string;
  error?: string;
  ago: string;
};
export type QueueItem =
  | { kind: "flag"; student: Who; assignment_id: number; questionnaire_title: string; flags: { label: string; answer: string }[]; submitted_at: string | null }
  | { kind: "confirm"; student: Who; assignments: { id: number; questionnaire_title: string; source: string }[]; created_at: string | null }
  | { kind: "six_am"; student: Who; report_id: number | null; reviewed: number | null }
  | { kind: "first_touch"; student: Who; updated_at: string | null }
  | { kind: "booking"; student: Who };
export type Upcoming = {
  booking_id: number;
  student_name: string;
  student_code: string | null;
  appointment_time: string;
  advisor_name: string;
};
export type WorkbenchData = {
  ok: boolean;
  permissions: { can_write: boolean; full: boolean };
  counts: Record<"booking" | "y4_report" | "interpretation" | "six_am" | "done", number>;
  queue: QueueItem[];
  upcoming: Upcoming[];
  job: Job | null;
};
export type Notify = (text: string, kind?: "ok" | "error") => void;
export type { Progress };

const WEEK = ["日", "一", "二", "三", "四", "五", "六"];
export function weekday(d: Date): string {
  return "周" + WEEK[d.getDay()];
}
export function pad2(n: number): string {
  return (n < 10 ? "0" : "") + n;
}
