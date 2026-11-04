import {
  CalendarDays,
  ChartColumn,
  FileText,
  House,
  MessagesSquare,
  Settings,
  Users,
  Waypoints,
  Workflow,
  Wrench,
  type LucideIcon,
} from "lucide-react";

import type { Boot, NavLink } from "@/lib/boot";

export type RailItem = { key: string; label: string; icon: LucideIcon; link: NavLink };
export type RailSection = { key: string; label: string; icon: LucideIcon; links: NavLink[] };
export type RailModel = { main: RailItem[]; old: RailSection[]; other: RailItem[] };

const MAIN: { label: string; icon: LucideIcon; key: string }[] = [
  { label: "工作台", icon: House, key: "workspace" },
  { label: "学生档案", icon: Users, key: "students" },
  { label: "Profiling 流程", icon: Workflow, key: "flow" },
  { label: "预约", icon: CalendarDays, key: "tools.bookings" },
];

const OLD: { key: string; label: string; icon: LucideIcon; keys: string[] }[] = [
  { key: "first_touch", label: "First Touch", icon: MessagesSquare, keys: ["first_touch", "first_touch.guide"] },
  { key: "six_am", label: "6AM", icon: Waypoints, keys: ["insights.six-am"] },
  { key: "insights", label: "洞察", icon: ChartColumn, keys: ["insights.dashboard", "insights.y4-signals"] },
  {
    key: "tools",
    label: "工具",
    icon: Wrench,
    keys: ["generate", "tools.bank", "tools.transcript", "tools.internal", "tools.prompt-lab"],
  },
  { key: "system", label: "系统", icon: Settings, keys: ["system.users", "system.settings", "system.docs"] },
];

const OTHER_ICONS: Record<string, LucideIcon> = { m1: MessagesSquare, e4: FileText };

/** 把服务端给的导航整理成设计稿的侧栏结构；没有映射到的链接放进“工具”，不会丢。 */
export function buildRail(boot: Boot): RailModel {
  const byKey = new Map<string, NavLink>();
  for (const group of boot.nav) {
    if (group.key === "other") continue;
    for (const link of group.links) byKey.set(link.key, link);
  }

  const used = new Set<string>();
  const main: RailItem[] = [];
  for (const m of MAIN) {
    used.add(m.key);
    const link = byKey.get(m.key);
    if (link) main.push({ key: m.key, label: m.label, icon: m.icon, link });
  }

  for (const o of OLD) o.keys.forEach((k) => used.add(k));
  const unmapped = Array.from(byKey.keys()).filter((k) => !used.has(k));

  const old: RailSection[] = [];
  for (const o of OLD) {
    const keys = o.key === "tools" ? [...o.keys, ...unmapped] : o.keys;
    const links = keys.map((k) => byKey.get(k)).filter((l): l is NavLink => Boolean(l));
    if (links.length) old.push({ key: o.key, label: o.label, icon: o.icon, links });
  }

  const other: RailItem[] = [];
  const otherGroup = boot.nav.find((g) => g.key === "other");
  if (otherGroup) {
    for (const link of otherGroup.links) {
      if (link.key === "platforms") continue;
      other.push({ key: link.key, label: link.label, icon: OTHER_ICONS[link.key] ?? FileText, link });
    }
  }

  return { main, old, other };
}

export type Jump = { key: string; label: string; link: NavLink; group?: string };

/** 命令面板里的“跳转”项：侧栏上所有能点的链接。 */
export function buildJumps(model: RailModel): Jump[] {
  const out: Jump[] = [];
  const seen = new Set<string>();
  const add = (key: string, label: string, link: NavLink, group?: string) => {
    if (seen.has(link.href)) return;
    seen.add(link.href);
    out.push({ key, label, link, group });
  };
  model.main.forEach((i) => add(i.key, i.label, i.link));
  model.old.forEach((s) => {
    if (s.links.length === 1) add(s.key, s.label, s.links[0]);
    else s.links.forEach((l) => add(l.key, l.label, l, s.label));
  });
  model.other.forEach((i) => add(i.key, i.label, i.link));
  return out;
}
