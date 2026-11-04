import * as React from "react";
import { Link, useSearchParams } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { getJSON } from "@/lib/api";
import { stageTitle, type Progress } from "@/lib/progress";
import { useTab } from "@/lib/useTab";
import { cn } from "@/lib/utils";
import PageHeader from "@/shell/PageHeader";

type Row = {
  code: string;
  name: string;
  school: string;
  advisor_name: string;
  progress: Progress;
  updated_at: string | null;
};
type ListResponse = {
  ok: boolean;
  total: number;
  page: number;
  per_page: number;
  counts: Record<string, number>;
  rows: Row[];
};

const PER_PAGE = 200;
const COLUMNS: { key: string; label: string }[] = [
  { key: "booking", label: "预约" },
  { key: "y4_report", label: "Y4 报告" },
  { key: "interpretation", label: "解读会" },
  { key: "six_am", label: "6AM" },
  { key: "done", label: "已完成" },
];

function bucketOf(row: Row): string {
  return row.progress.done || !row.progress.next ? "done" : row.progress.next.key;
}

function dayOf(iso: string | null): string {
  return iso ? iso.slice(0, 10) : "—";
}

async function loadAll(): Promise<Row[]> {
  const rows: Row[] = [];
  for (let page = 1; ; page += 1) {
    const body = await getJSON<ListResponse>("/api/profiling/students?per_page=" + PER_PAGE + "&page=" + page);
    rows.push(...body.rows);
    if (body.rows.length === 0 || rows.length >= body.total) break;
  }
  return rows;
}

function StageBar({ progress }: { progress: Progress }) {
  return (
    <div className="flex gap-0.5" aria-label={progress.stages.map(stageTitle).join("；")}>
      {progress.stages.map((stage) => (
        <span
          key={stage.key}
          title={stageTitle(stage)}
          className={cn(
            "h-3 w-3",
            stage.state === "done" && "bg-ink",
            stage.state === "todo" && (stage.required ? "border border-ink" : "border border-line"),
            stage.state === "not_used" && "bg-sunk",
          )}
        />
      ))}
    </div>
  );
}

function Board({ rows }: { rows: Row[] }) {
  return (
    <div className="overflow-x-auto">
      <div className="grid min-w-[1000px] grid-cols-5 gap-4">
        {COLUMNS.map((col) => {
          const items = rows.filter((row) => bucketOf(row) === col.key);
          return (
            <section key={col.key} className="min-w-0 border-t-2 border-rule">
              <h2 className="flex items-baseline gap-2 py-2.5 text-sm font-bold">
                {col.label}
                <span className="font-mono text-xs font-normal text-mute">{items.length}</span>
              </h2>
              {items.length === 0 ? (
                <p className="py-2 text-sm text-mute">—</p>
              ) : (
                <ul>
                  {items.map((row) => (
                    <li key={row.code} className="border-t border-line">
                      <Link
                        to={"/students/" + encodeURIComponent(row.code)}
                        className="block px-1 py-2.5 transition-colors hover:bg-sunk"
                      >
                        <span className="block truncate font-semibold">{row.name || "—"}</span>
                        <span className="block truncate text-xs text-mute">
                          {(row.advisor_name || "未分配顾问") + " · " + dayOf(row.updated_at)}
                        </span>
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          );
        })}
      </div>
    </div>
  );
}

function List({ rows }: { rows: Row[] }) {
  const open = rows.filter((row) => bucketOf(row) !== "done");
  return (
    <div className="overflow-x-auto border-t-2 border-rule">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>学生</TableHead>
            <TableHead>顾问</TableHead>
            <TableHead>流程进度</TableHead>
            <TableHead>下一步</TableHead>
            <TableHead>更新</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {open.length === 0 ? (
            <TableRow>
              <TableCell colSpan={5} className="py-10 text-center text-mute">
                没有进行中的学生
              </TableCell>
            </TableRow>
          ) : (
            open.map((row) => (
              <TableRow key={row.code}>
                <TableCell>
                  <Link to={"/students/" + encodeURIComponent(row.code)} className="font-semibold hover:underline">
                    {row.name || "—"}
                  </Link>
                  <div className="font-mono text-xs text-mute">{row.code}</div>
                </TableCell>
                <TableCell>{row.advisor_name || "—"}</TableCell>
                <TableCell>
                  <StageBar progress={row.progress} />
                </TableCell>
                <TableCell className="font-semibold">{row.progress.label}</TableCell>
                <TableCell className="font-mono text-xs text-mute">{dayOf(row.updated_at)}</TableCell>
              </TableRow>
            ))
          )}
        </TableBody>
      </Table>
    </div>
  );
}

export default function Flow() {
  const [view, setView] = useTab(["board", "list"], "board", "view");
  const [params, setParams] = useSearchParams();
  const advisor = params.get("advisor") || "";
  const setAdvisor = (value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set("advisor", value);
    else next.delete("advisor");
    setParams(next, { replace: true });
  };
  const [rows, setRows] = React.useState<Row[] | null>(null);
  const [error, setError] = React.useState(false);
  const [reload, setReload] = React.useState(0);

  React.useEffect(() => {
    let cancelled = false;
    setError(false);
    setRows(null);
    loadAll()
      .then((all) => {
        if (!cancelled) setRows(all);
      })
      .catch(() => {
        if (!cancelled) setError(true);
      });
    return () => {
      cancelled = true;
    };
  }, [reload]);

  const advisors = React.useMemo(() => {
    const names = new Set<string>();
    (rows || []).forEach((row) => {
      if (row.advisor_name) names.add(row.advisor_name);
    });
    return Array.from(names).sort((a, b) => a.localeCompare(b, "zh-CN"));
  }, [rows]);

  const shown = (rows || []).filter((row) => !advisor || row.advisor_name === advisor);

  return (
    <div>
      <PageHeader title="Profiling 流程" sub="每位学生现在走到哪一步。" />

      <div className="mb-4 flex flex-wrap items-center gap-2">
        <div className="inline-flex border border-rule" role="group" aria-label="显示方式">
          {[
            { key: "board", label: "看板" },
            { key: "list", label: "列表" },
          ].map((opt, i) => (
            <button
              key={opt.key}
              type="button"
              aria-pressed={view === opt.key}
              onClick={() => setView(opt.key)}
              className={cn(
                "h-8 px-3 text-[13px] font-medium transition-colors",
                i > 0 && "border-l border-rule",
                view === opt.key ? "bg-ink font-semibold text-white" : "hover:bg-sunk",
              )}
            >
              {opt.label}
            </button>
          ))}
        </div>
        <select
          aria-label="顾问"
          value={advisor}
          onChange={(e) => setAdvisor(e.target.value)}
          className="h-8 border border-line bg-background px-2 text-[13px]"
        >
          <option value="">全部顾问</option>
          {advisors.map((name) => (
            <option key={name} value={name}>
              {name}
            </option>
          ))}
        </select>
        {rows ? <span className="ml-auto text-[13px] text-mute">{"共 " + shown.length + " 名学生"}</span> : null}
      </div>

      {error ? (
        <div className="py-10">
          <p className="mb-3">无法载入</p>
          <Button variant="outline" onClick={() => setReload((n) => n + 1)}>
            重试
          </Button>
        </div>
      ) : rows === null ? (
        <div aria-busy="true" className="grid gap-3">
          <Skeleton className="h-6 w-64" />
          <Skeleton className="h-40 w-full" />
        </div>
      ) : view === "list" ? (
        <List rows={shown} />
      ) : (
        <Board rows={shown} />
      )}
    </div>
  );
}
