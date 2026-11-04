import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { cn } from "@/lib/utils";

import { fmtDate, Tag, type ScoreBand, type ScoreLine, type ScoreSet } from "./common";

function scoreText(b: ScoreLine): string {
  return b.score === null || b.score === undefined ? "未完成（" + b.answered + "/" + b.item_count + "）" : String(b.score);
}

function BandCell({ band }: { band: ScoreBand }) {
  if (!band) return <span className="text-mute">—</span>;
  const tone = band.tone === "danger" ? "alert" : band.tone === "ok" ? "strong" : "plain";
  return (
    <>
      <Tag tone={tone}>{band.label}</Tag>
      {band.advice ? <span className="ml-1.5 text-xs">{band.advice}</span> : null}
    </>
  );
}

/** 一份问卷的得分表（Y4 画像的补充问卷得分与问卷 tab 共用）。 */
export default function ScoreTable({ s }: { s: ScoreSet }) {
  const groups: { title: string; dims: ScoreLine[] }[] = [];
  (s.dimensions || []).forEach((d) => {
    const last = groups[groups.length - 1];
    const title = d.group || "";
    if (last && last.title === title) last.dims.push(d);
    else groups.push({ title, dims: [d] });
  });
  const total = s.total;
  return (
    <div>
      <Table className="min-w-[560px] table-fixed">
        <TableHeader>
          <TableRow>
            <TableHead>维度</TableHead>
            <TableHead className="w-[100px] text-right">得分</TableHead>
            <TableHead className="w-[110px] text-right">取值范围</TableHead>
            <TableHead className="w-[42%]">分档</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {total ? (
            <TableRow className="font-bold">
              <TableCell>{total.label}</TableCell>
              <TableCell className="text-right tabular-nums">{scoreText(total)}</TableCell>
              <TableCell className="text-right font-mono">
                {total.min} ~ {total.max}
              </TableCell>
              <TableCell>{total.band ? <BandCell band={total.band} /> : null}</TableCell>
            </TableRow>
          ) : null}
          {groups.map((g, gi) => (
            <GroupRows key={gi + g.title} title={g.title} dims={g.dims} />
          ))}
        </TableBody>
      </Table>
      {(s.flags || []).map((x) => (
        <div key={x.id} className={cn("my-2 border border-attention bg-tint px-3 py-2 text-sm text-attention")}>
          {x.label + "：选择「" + x.answer + "」"}
          {s.reviewed_at ? "（" + (s.reviewed_by || "顾问") + " 已于 " + fmtDate(s.reviewed_at) + " 标记跟进）" : ""}
        </div>
      ))}
    </div>
  );
}

function GroupRows({ title, dims }: { title: string; dims: ScoreLine[] }) {
  return (
    <>
      {title ? (
        <TableRow>
          <TableCell colSpan={4} className="bg-sunk text-xs font-semibold text-mute">
            {title}
          </TableCell>
        </TableRow>
      ) : null}
      {dims.map((d) => (
        <TableRow key={d.name}>
          <TableCell>{d.name}</TableCell>
          <TableCell className="text-right tabular-nums">{scoreText(d)}</TableCell>
          <TableCell className="text-right font-mono">
            {d.min} ~ {d.max}
          </TableCell>
          <TableCell>
            <BandCell band={d.band} />
          </TableCell>
        </TableRow>
      ))}
    </>
  );
}
