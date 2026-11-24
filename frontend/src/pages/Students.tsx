import * as React from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { errorText, getJSON, postJSON } from "@/lib/api";
import { useBoot } from "@/lib/boot";
import { stageTitle, type Progress } from "@/lib/progress";
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

const PER_PAGE = 50;
const CHIPS: { key: string; label: string }[] = [
  { key: "", label: "全部" },
  { key: "booking", label: "预约" },
  { key: "y4_report", label: "Y4 报告" },
  { key: "interpretation", label: "解读会" },
  { key: "six_am", label: "6AM" },
  { key: "done", label: "已完成" },
];

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

const EMPTY_FORM = { name: "", grade: "", school: "", advisor_name: "", phone: "" };

/** B：未经预约直接建档。顾问账号的归属由服务端固定为本人。 */
function AddStudentDialog({
  open,
  onOpenChange,
  onCreated,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreated: (code: string) => void;
}) {
  const [form, setForm] = React.useState(EMPTY_FORM);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");

  React.useEffect(() => {
    if (open) {
      setForm(EMPTY_FORM);
      setError("");
      setBusy(false);
    }
  }, [open]);

  const set = (key: keyof typeof EMPTY_FORM) => (event: React.ChangeEvent<HTMLInputElement>) =>
    setForm((f) => ({ ...f, [key]: event.target.value }));

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    if (!form.name.trim()) {
      setError("姓名不能为空");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const res = await postJSON<{ ok: boolean; student: { code: string } }>("/api/profiling/students", {
        name: form.name.trim(),
        grade: form.grade.trim(),
        school: form.school.trim(),
        advisor_name: form.advisor_name.trim(),
        phone: form.phone.trim(),
      });
      onCreated(res.student.code);
    } catch (e) {
      setError(errorText(e, "建档失败"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[85vh] overflow-y-auto shadow-none sm:rounded-none">
        <DialogHeader>
          <DialogTitle>添加学生</DialogTitle>
        </DialogHeader>
        <form className="grid gap-3" onSubmit={submit}>
          <div className="grid gap-1.5">
            <Label htmlFor="new-student-name">学生姓名</Label>
            <Input
              id="new-student-name"
              autoFocus
              maxLength={100}
              disabled={busy}
              value={form.name}
              onChange={set("name")}
            />
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="grid gap-1.5">
              <Label htmlFor="new-student-grade">年级</Label>
              <Input id="new-student-grade" maxLength={50} disabled={busy} value={form.grade} onChange={set("grade")} />
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="new-student-school">学校</Label>
              <Input id="new-student-school" maxLength={200} disabled={busy} value={form.school} onChange={set("school")} />
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="new-student-advisor">顾问</Label>
              <Input
                id="new-student-advisor"
                maxLength={100}
                disabled={busy}
                placeholder="默认跟随当前账号"
                value={form.advisor_name}
                onChange={set("advisor_name")}
              />
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="new-student-phone">电话</Label>
              <Input id="new-student-phone" maxLength={50} disabled={busy} value={form.phone} onChange={set("phone")} />
            </div>
          </div>
          {error ? <p role="alert" className="text-sm text-attention">{error}</p> : null}
          <DialogFooter className="gap-2 sm:gap-0">
            <Button type="button" variant="outline" disabled={busy} onClick={() => onOpenChange(false)}>
              取消
            </Button>
            <Button type="submit" disabled={busy}>{busy ? "建档中…" : "建档并打开 360"}</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export default function Students() {
  const boot = useBoot();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const [addOpen, setAddOpen] = React.useState(false);
  const q = params.get("q") || "";
  const stage = params.get("stage") || "";
  const sort = params.get("sort") === "name" ? "name" : "updated";
  const page = Math.max(1, Number(params.get("page") || "1") || 1);

  const [draft, setDraft] = React.useState(q);
  const [data, setData] = React.useState<ListResponse | null>(null);
  const [error, setError] = React.useState(false);
  const [reload, setReload] = React.useState(0);

  function update(next: Record<string, string>) {
    const p = new URLSearchParams(params);
    Object.entries(next).forEach(([key, value]) => {
      if (value) p.set(key, value);
      else p.delete(key);
    });
    setParams(p, { replace: true });
  }

  React.useEffect(() => {
    setDraft(q);
  }, [q]);

  React.useEffect(() => {
    const timer = window.setTimeout(() => {
      if (draft.trim() !== q) update({ q: draft.trim(), page: "" });
    }, 300);
    return () => window.clearTimeout(timer);
  }, [draft, q]);

  React.useEffect(() => {
    let cancelled = false;
    setError(false);
    setData(null);
    const query = new URLSearchParams({ page: String(page), per_page: String(PER_PAGE), sort });
    if (q) query.set("q", q);
    if (stage) query.set("stage", stage);
    getJSON<ListResponse>("/api/profiling/students?" + query.toString())
      .then((body) => {
        if (!cancelled) setData(body);
      })
      .catch(() => {
        if (!cancelled) setError(true);
      });
    return () => {
      cancelled = true;
    };
  }, [q, stage, sort, page, reload]);

  const counts: Record<string, number> = data ? data.counts : {};
  const allCount = Object.values(counts).reduce((sum, n) => sum + n, 0);
  const totalPages = data ? Math.max(1, Math.ceil(data.total / data.per_page)) : 1;

  return (
    <div>
      <PageHeader
        title="学生档案"
        sub={data ? "共 " + data.total + " 名学生" : undefined}
        actions={
          <div className="flex gap-2">
            {boot.user.role !== "viewer" ? (
              <Button onClick={() => setAddOpen(true)}>＋ 添加学生</Button>
            ) : null}
            {boot.policy.detail_level === "full" ? (
              <Button variant="outline" asChild>
                <a href="/api/export">导出 CSV</a>
              </Button>
            ) : null}
            <Button variant="outline" asChild>
              <a href="/students">旧版学生档案</a>
            </Button>
          </div>
        }
      />

      <div className="mb-4 flex flex-wrap items-center gap-2">
        {CHIPS.map((chip) => {
          const on = chip.key === stage;
          const n = chip.key === "" ? allCount : counts[chip.key] || 0;
          return (
            <button
              key={chip.key || "all"}
              type="button"
              onClick={() => update({ stage: chip.key, page: "" })}
              className={cn(
                "h-8 border px-3 text-sm font-semibold transition-colors",
                on ? "border-rule bg-ink text-white" : "border-line bg-background hover:bg-sunk",
              )}
            >
              {chip.label} <span className={on ? "text-white" : "text-mute"}>{n}</span>
            </button>
          );
        })}
        <span className="text-xs text-mute">按下一步统计</span>
      </div>

      <div className="mb-4 flex flex-wrap items-center gap-2">
        <Input
          className="w-full max-w-sm"
          placeholder="搜索姓名、编号、学校、顾问…（支持拼音）"
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
        />
        <select
          className="h-9 border border-input bg-background px-2 text-sm"
          value={sort}
          onChange={(event) => update({ sort: event.target.value === "name" ? "name" : "", page: "" })}
          aria-label="排序"
        >
          <option value="updated">最近更新</option>
          <option value="name">姓名</option>
        </select>
      </div>

      {error ? (
        <div className="py-10">
          <p className="mb-3">无法载入学生列表。</p>
          <Button variant="outline" onClick={() => setReload((n) => n + 1)}>
            重试
          </Button>
        </div>
      ) : (
        <div className="overflow-x-auto">
          <Table className="min-w-[760px]">
            <TableHeader>
              <TableRow>
                <TableHead>学生</TableHead>
                <TableHead>学校</TableHead>
                <TableHead>顾问</TableHead>
                <TableHead>流程进度</TableHead>
                <TableHead>下一步</TableHead>
                <TableHead>更新</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data === null
                ? Array.from({ length: 6 }).map((_, i) => (
                    <TableRow key={i}>
                      <TableCell colSpan={6}>
                        <Skeleton className="h-4 w-64" />
                      </TableCell>
                    </TableRow>
                  ))
                : data.rows.map((row) => (
                    <TableRow key={row.code}>
                      <TableCell>
                        <Link
                          to={"/students/" + encodeURIComponent(row.code)}
                          className="font-semibold hover:underline"
                        >
                          {row.name || "—"}
                        </Link>
                        <div className="font-mono text-xs text-mute">{row.code}</div>
                      </TableCell>
                      <TableCell>{row.school || "—"}</TableCell>
                      <TableCell>{row.advisor_name || "—"}</TableCell>
                      <TableCell>
                        <StageBar progress={row.progress} />
                      </TableCell>
                      <TableCell>
                        {row.progress.done ? (
                          <span className="text-mute">已完成</span>
                        ) : (
                          <span className="font-semibold">{row.progress.label}</span>
                        )}
                      </TableCell>
                      <TableCell className="text-mute">
                        {row.updated_at ? row.updated_at.slice(0, 10) : "—"}
                      </TableCell>
                    </TableRow>
                  ))}
            </TableBody>
          </Table>
        </div>
      )}

      {data && data.rows.length === 0 && !error ? (
        <div className="py-10 text-center">
          <p className="mb-3 text-mute">暂无匹配的学生</p>
          {q || stage ? (
            <Button variant="outline" onClick={() => update({ q: "", stage: "", page: "" })}>
              清除筛选
            </Button>
          ) : null}
        </div>
      ) : null}

      {data && data.total > data.per_page ? (
        <div className="mt-4 flex items-center gap-3">
          <Button
            variant="outline"
            size="sm"
            disabled={page <= 1}
            onClick={() => update({ page: String(page - 1) })}
          >
            上一页
          </Button>
          <span className="text-sm text-mute">
            第 {page} / {totalPages} 页
          </span>
          <Button
            variant="outline"
            size="sm"
            disabled={page >= totalPages}
            onClick={() => update({ page: String(page + 1) })}
          >
            下一页
          </Button>
        </div>
      ) : null}
      <AddStudentDialog
        open={addOpen}
        onOpenChange={setAddOpen}
        onCreated={(code) => {
          setAddOpen(false);
          navigate("/students/" + encodeURIComponent(code));
        }}
      />
    </div>
  );
}
