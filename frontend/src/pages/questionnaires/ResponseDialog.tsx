import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import type { ScoreLine, ScoreSet } from "@/pages/profile/common";

type Option = { value: unknown; label: string };
type Question = { id: string | number; title: string; type?: string; options?: Option[] };
export type ResponseResp = {
  ok: boolean;
  response?: { answers?: Record<string, unknown> };
  schema?: { questions?: Question[] };
  scores?: ScoreSet | null;
};
export type ResponseView = { title: string; data: ResponseResp };

function answerRows(data: ResponseResp): { id: string | number; title: string; answer: string }[] {
  const answers = data.response?.answers || {};
  const questions = data.schema?.questions || [];
  const optMap = (q: Question) => {
    const m: Record<string, string> = {};
    (q.options || []).forEach((o) => {
      m[String(o.value)] = o.label;
    });
    return m;
  };
  return questions.map((q) => {
    const v = answers[String(q.id)];
    let label: unknown = v;
    if (q.type === "multi" && Array.isArray(v)) {
      const m = optMap(q);
      label = v.map((x) => m[String(x)] || x).join("、");
    } else if (q.options) {
      label = optMap(q)[String(v)] || v;
    }
    const empty = label === undefined || label === null || label === "";
    return { id: q.id, title: q.title, answer: empty ? "（未作答）" : String(label) };
  });
}

function Line({ line, total }: { line: ScoreLine; total?: boolean }) {
  const name = total ? line.label : line.name;
  const band = line.band ? line.band.label + (!total && line.band.advice ? "，" + line.band.advice : "") : "";
  return (
    <div className="flex flex-wrap items-baseline gap-x-2 border-b border-line py-1.5 text-sm">
      <span className={total ? "font-bold" : undefined}>{name}</span>
      <b>{line.score === null ? "未完成" : line.score}</b>
      <span className="text-mute">
        {line.min} ~ {line.max}
      </span>
      <span>{band}</span>
    </div>
  );
}

export default function ResponseDialog({ view, onClose }: { view: ResponseView | null; onClose: () => void }) {
  const scores = view?.data.scores || null;
  return (
    <Dialog open={view !== null} onOpenChange={(open) => (open ? null : onClose())}>
      <DialogContent className="max-w-[560px] sm:rounded-none shadow-none">
        <DialogHeader>
          <DialogTitle>{view?.title}</DialogTitle>
        </DialogHeader>
        {view ? (
          <div className="max-h-[60vh] overflow-auto">
            {scores ? (
              <div>
                {scores.total ? <Line line={scores.total} total /> : null}
                {(scores.dimensions || []).map((d, i) => (
                  <Line key={(d.name || "") + i} line={d} />
                ))}
                {(scores.flags || []).map((x) => (
                  <div key={x.id} className="mt-2 bg-s3-bg px-3 py-2 text-sm text-s3">
                    {x.label}：选择「{x.answer}」
                  </div>
                ))}
              </div>
            ) : null}
            {scores ? <h5 className="mb-1.5 mt-3.5 text-sm font-bold">原始答案</h5> : null}
            {answerRows(view.data).map((qa) => (
              <div key={qa.id} className="border-b border-line py-1.5 text-sm">
                <div className="text-mute">{qa.title}</div>
                <div className="break-words">{qa.answer}</div>
              </div>
            ))}
          </div>
        ) : null}
        <DialogFooter className="gap-2 sm:gap-0">
          <Button onClick={onClose}>关闭</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
