import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

import { dtShort, fmtFTTime, Section, Tag, useProfile } from "./common";

const MARKS = ["①", "②", "③"];

export default function FirstTouchTab() {
  const { data } = useProfile();
  const ft = data.first_touch;
  const canWrite = data.permissions.can_write;
  const status = ft.status || "not_started";

  let label = "未开始";
  let tone: "strong" | "soft" | "alert" | "plain" = "plain";
  if (status === "completed") {
    label = "已完成" + (ft.reports && ft.reports.length ? " · v" + ft.reports[0].version : "");
    tone = "strong";
  } else if (status === "in_progress") {
    label = "进行中 · " + MARKS[ft.step || 0];
    tone = "soft";
  } else if (status === "needs_y4") {
    label = "需先完成 Y4";
    tone = "alert";
  }

  let sub = "已完成 Y4，可以直接开始首次会谈。";
  if (ft.restricted) sub = "当前账号不能查看 First Touch 内容";
  else if (status === "needs_y4") sub = "该学生还没有完整的 Y4 报告，不能开始会谈。";
  else if (ft.sessionId) sub = "三步会谈：会前准备 · 会谈记录 · 会后整理";

  let action = null;
  if (!ft.restricted) {
    if (!ft.canStart) {
      action = (
        <>
          <Button variant="outline" size="sm" disabled>
            需先完成 Y4
          </Button>
          <Button variant="outline" size="sm" asChild>
            <a href="/generate">去生成 Y4</a>
          </Button>
        </>
      );
    } else {
      let text = "继续会谈";
      if (!canWrite || status === "completed" || !ft.sessionId) {
        text = canWrite && !ft.sessionId ? "开始 First Touch" : "查看 First Touch";
      }
      action = (
        <Button size="sm" asChild>
          <a href={"/first-touch/students/" + data.student.id}>{text}</a>
        </Button>
      );
    }
  }

  return (
    <Section
      title="First Touch"
      sub={sub}
      right={
        <>
          <Tag tone={tone}>{label}</Tag>
          {action}
        </>
      }
    >
      {ft.restricted ? (
        <p className="py-3 font-mono text-sm">
          {ft.updatedAt ? "更新 " + dtShort(ft.updatedAt) : ""}
          {ft.confirmedAt ? " · 报告确认 " + dtShort(ft.confirmedAt) : ""}
        </p>
      ) : (
        <div className="grid gap-5 pb-3">
          {ft.interests && ft.interests.length > 0 ? (
            <div>
              <p className="mb-1.5 text-sm text-mute">兴趣（喜欢 + 擅长 最高的 6 项）</p>
              <div className="flex flex-wrap gap-1.5">
                {ft.interests.map((i) => (
                  <Tag key={i.label} tone="soft">
                    {i.specialFocus ? "★ " : ""}
                    {i.label}
                    {" · " + i.preferenceScore + "/" + i.competenceScore}
                  </Tag>
                ))}
              </div>
              <p className="mt-2 text-sm text-mute">
                {(ft.scoredCount || 0) + " 项已评分 · " + (ft.pendingCount || 0) + " 项待评"}
              </p>
            </div>
          ) : null}
          <div>
            <p className="mb-1.5 text-sm text-mute">已确认报告</p>
            <Table className="min-w-[480px]">
              <TableHeader>
                <TableRow>
                  <TableHead>版本</TableHead>
                  <TableHead>确认时间</TableHead>
                  <TableHead>确认人</TableHead>
                  <TableHead />
                </TableRow>
              </TableHeader>
              <TableBody>
                {(ft.reports || []).map((r) => (
                  <TableRow key={r.id}>
                    <TableCell className="font-mono">{"v" + r.version}</TableCell>
                    <TableCell className="font-mono">{fmtFTTime(r.confirmedAt)}</TableCell>
                    <TableCell>{r.confirmedBy || "—"}</TableCell>
                    <TableCell className="whitespace-nowrap text-right">
                      <span className="inline-flex gap-2">
                        <Button variant="outline" size="sm" asChild>
                          <a href={"/api/growth-talk/reports/" + r.id + "/download.pdf"} target="_blank" rel="noreferrer">
                            PDF
                          </a>
                        </Button>
                        <Button variant="outline" size="sm" asChild>
                          <a href={"/api/growth-talk/reports/" + r.id + "/download.json"} download>
                            JSON
                          </a>
                        </Button>
                      </span>
                    </TableCell>
                  </TableRow>
                ))}
                {!ft.reports || ft.reports.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={4} className="text-mute">
                      还没有已确认的 First Touch 报告。在会谈第 ③ 步确认后出现在这里。
                    </TableCell>
                  </TableRow>
                ) : null}
              </TableBody>
            </Table>
          </div>
        </div>
      )}
    </Section>
  );
}
