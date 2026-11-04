import * as React from "react";

import { Input } from "@/components/ui/input";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { cn } from "@/lib/utils";

import { Empty, fmtDate, fmtValue, Gate, Section, useProfile, useResource, type ScoreSet } from "./common";
import ScoreTable from "./ScoreTable";

type Item = { code: string; label: string; value: unknown; source_pdf?: string };
type Group = { name: string; items: Item[] };
type ProfileResp = {
  report: { id: number; report_date: string | null } | null;
  groups: Group[];
  total: number;
  questionnaire_scores: ScoreSet[];
};

// 百分位类指标（指标名含「百分位」且数值 0-100）画条；与旧页 isPct 同一规则，不放宽。
function pct(it: Item): number | null {
  if (!it.label || String(it.label).indexOf("百分位") === -1) return null;
  const n = Number(it.value);
  if (!isFinite(n) || n < 0 || n > 100) return null;
  return Math.max(0, Math.min(100, n));
}

export default function Y4Tab() {
  const { code, data } = useProfile();
  const res = useResource<ProfileResp>("profile", "/students/" + encodeURIComponent(code) + "/api/profile");
  const [group, setGroup] = React.useState("");
  const [q, setQ] = React.useState("");

  return (
    <Gate res={res}>
      {(p) => {
        const scores = data.permissions.full ? p.questionnaire_scores || [] : [];
        const needle = q.trim().toLowerCase();
        const groups = (p.groups || [])
          .filter((g) => !group || g.name === group)
          .map((g) => ({
            ...g,
            items: g.items.filter(
              (it) => !needle || String(it.code).toLowerCase().includes(needle) || String(it.label).toLowerCase().includes(needle),
            ),
          }))
          .filter((g) => g.items.length > 0);
        if (!p.report && scores.length === 0) return <Empty>暂无画像数据</Empty>;
        return (
          <div>
            {scores.length > 0 ? (
              <div>
                <p className="mb-3 text-sm text-mute">补充问卷得分 · 每份问卷取最近一次提交；计分口径见 Profiling 问卷 Excel</p>
                {scores.map((s) => (
                  <Section
                    key={s.assignment_id}
                    title={s.questionnaire_title}
                    right={<span className="font-mono text-xs text-mute">{fmtDate(s.submitted_at)}</span>}
                  >
                    <ScoreTable s={s} />
                  </Section>
                ))}
              </div>
            ) : null}
            {p.report ? (
              <div>
                <p className="mb-3 text-sm text-mute">
                  最新报告：<span className="font-mono">{p.report.report_date || "—"}</span> · 共 <b>{p.total}</b> 个数据点，按{" "}
                  <b>{p.groups.length}</b> 组展示
                </p>
                <div className="mb-4 flex flex-wrap items-center gap-2">
                  {[{ name: "" }, ...p.groups].map((g) => {
                    const on = g.name === group;
                    return (
                      <button
                        key={g.name || "all"}
                        type="button"
                        onClick={() => setGroup(g.name)}
                        className={cn(
                          "h-8 border px-3 text-sm font-semibold transition-colors",
                          on ? "border-rule bg-ink text-white" : "border-line bg-background hover:bg-sunk",
                        )}
                      >
                        {g.name || "全部"}
                      </button>
                    );
                  })}
                </div>
                <Input
                  className="mb-4 w-full max-w-sm rounded-none"
                  placeholder="搜索编号或指标"
                  value={q}
                  onChange={(e) => setQ(e.target.value)}
                />
                {groups.map((g) => (
                  <Section key={g.name} title={g.name} right={<span className="text-xs text-mute">{g.items.length + " 项"}</span>}>
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead>编号</TableHead>
                          <TableHead>指标</TableHead>
                          <TableHead className="text-right">数值</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {g.items.map((it) => {
                          const w = pct(it);
                          return (
                            <TableRow key={it.code}>
                              <TableCell className="font-mono">{it.code}</TableCell>
                              <TableCell>{it.label}</TableCell>
                              <TableCell className="text-right">
                                <span className="inline-flex items-center justify-end gap-2">
                                  {w !== null ? (
                                    <span className="inline-block h-1 w-[60px] bg-sunk" aria-hidden="true">
                                      <i className="block h-full bg-ink" style={{ width: w + "%" }} />
                                    </span>
                                  ) : null}
                                  <span className="font-semibold">{fmtValue(it.value)}</span>
                                </span>
                              </TableCell>
                            </TableRow>
                          );
                        })}
                      </TableBody>
                    </Table>
                  </Section>
                ))}
              </div>
            ) : null}
          </div>
        );
      }}
    </Gate>
  );
}
