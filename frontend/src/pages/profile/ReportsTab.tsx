import * as React from "react";

import { Button } from "@/components/ui/button";
import { getJSON } from "@/lib/api";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

import { Empty, Section, useProfile } from "./common";

type Y4Status = {
  round_id: number | null;
  report_id: number | null;
  build: { state: string; pdf_ready: boolean; name_stale: boolean };
};

function y4State(status: Y4Status | null | undefined): string {
  if (status === undefined) return "读取中…";
  if (status === null) return "无法读取报告状态";
  const { build } = status;
  if (build.name_stale) return "学生姓名已更新，现有成品已过期";
  if (build.pdf_ready) return "可下载";
  if (build.state === "queued" || build.state === "running") return "生成中";
  return "尚未生成";
}

/** B：报告交付集中到个案内。只呈现现有成品与入口，不重新生成、不改版本选择。 */
export default function ReportsTab() {
  const { data, setTab } = useProfile();
  const { student, latest_report, six_am, first_touch } = data;
  const base = "/students/" + encodeURIComponent(student.code) + "/api/y4";
  const [status, setStatus] = React.useState<Y4Status | null>();
  React.useEffect(() => {
    let active = true;
    getJSON<Y4Status>(base + "/status")
      .then((result) => { if (active) setStatus(result); })
      .catch(() => { if (active) setStatus(null); });
    return () => { active = false; };
  }, [base, student.name]);
  const y4Ready = !!status?.build.pdf_ready;
  const round = status?.round_id ? "轮次 #" + status.round_id
    : status?.report_id ? "报告 #" + status.report_id : "—";
  const ftReports = first_touch.restricted ? [] : first_touch.reports || [];

  return (
    <div>
      <Section title="报告与下载">
        <div className="overflow-x-auto">
          <Table className="min-w-[620px]">
            <TableHeader>
              <TableRow>
                <TableHead>报告</TableHead>
                <TableHead>版本 / 轮次</TableHead>
                <TableHead>状态</TableHead>
                <TableHead className="text-right">操作</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              <TableRow>
                <TableCell className="font-semibold">Y4 综合测评报告</TableCell>
                <TableCell className="font-mono">
                  {y4Ready ? "v2 · " + round : round}
                </TableCell>
                <TableCell>{y4State(status)}</TableCell>
                <TableCell className="whitespace-nowrap text-right">
                  <span className="inline-flex gap-2">
                    <Button variant="outline" size="sm" onClick={() => setTab("y4")}>
                      查看
                    </Button>
                    {y4Ready ? (
                      <Button variant="outline" size="sm" asChild>
                        <a href={base + "/build/file"}>下载 PDF</a>
                      </Button>
                    ) : (
                      <Button variant="outline" size="sm" disabled>
                        下载 PDF
                      </Button>
                    )}
                  </span>
                </TableCell>
              </TableRow>
              {ftReports.length === 0 ? (
                <TableRow>
                  <TableCell className="font-semibold">First Touch 会谈报告</TableCell>
                  <TableCell className="font-mono">—</TableCell>
                  <TableCell>{first_touch.restricted ? "无权查看" : "尚无已确认版本"}</TableCell>
                  <TableCell className="text-right">
                    <Button variant="outline" size="sm" onClick={() => setTab("first_touch")}>
                      查看
                    </Button>
                  </TableCell>
                </TableRow>
              ) : (
                ftReports.map((r) => (
                  <TableRow key={"ft-" + r.id}>
                    <TableCell className="font-semibold">First Touch 会谈报告</TableCell>
                    <TableCell className="font-mono">{"v" + r.version}</TableCell>
                    <TableCell>已确认</TableCell>
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
                ))
              )}
              <TableRow>
                <TableCell className="font-semibold">6AM 初步诊断与支持建议</TableCell>
                <TableCell className="font-mono">{six_am ? "v" + six_am.version : "—"}</TableCell>
                <TableCell>{six_am ? "已生成" : "尚未生成"}</TableCell>
                <TableCell className="text-right">
                  <Button variant="outline" size="sm" onClick={() => setTab("six_am")}>
                    {six_am ? "查看" : "去生成"}
                  </Button>
                </TableCell>
              </TableRow>
            </TableBody>
          </Table>
        </div>
      </Section>

      <Section title="交付与权限">
        <div className="grid gap-1.5 text-sm">
          <p>本页只汇集档案内已有的报告入口；成品、版本和下载沿用原有接口与账号归属。</p>
          <p>对外电子交付按既有流程在解读与签约确认后安排；系统按账号权限提供同一份成品。</p>
          <p className="text-mute">促签个案的签约状态尚未在系统中记录，对外交付前请人工核对。</p>
        </div>
      </Section>

      {!latest_report && !six_am && ftReports.length === 0 ? (
        <Empty>生成或确认后的报告会显示在这里。</Empty>
      ) : null}
    </div>
  );
}
