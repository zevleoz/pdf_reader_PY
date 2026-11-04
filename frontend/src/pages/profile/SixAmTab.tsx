import * as React from "react";

import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { errorText, postJSON } from "@/lib/api";
import { cn } from "@/lib/utils";

import {
  DIMS,
  Empty,
  fieldClass,
  Loading,
  LoadError,
  Section,
  Tag,
  useProfile,
  useResource,
  VERDICT_ZH,
  type SixAmModel,
  type SixAmProfileRow,
  type SixAmReview,
} from "./common";

type ReviewsResp = { profile_id: number | null; reviews: Record<string, SixAmReview> };

/** 6AM 状态与 6AM tab 共用：模型、档案列表、最新团队结论。 */
export function useSixAm() {
  const { data, code } = useProfile();
  const six = data.six_am;
  const model = useResource<{ model: SixAmModel }>("sixam-model", "/api/six-am/model");
  const profiles = useResource<{ profiles: SixAmProfileRow[] }>(
    "sixam-profiles",
    six ? "/students/" + encodeURIComponent(code) + "/api/six-am" : null,
  );
  const reviews = useResource<ReviewsResp>(
    "sixam-reviews",
    six ? "/api/reports/" + six.report_id + "/six-am/reviews" : null,
  );
  const profile = six && profiles.data ? (profiles.data.profiles || []).find((p) => p.id === six.profile_id) : undefined;
  const legacy = profile ? profile.profile.schema !== "6am.v0.6" : false;
  const pending = !!six && (model.status !== "ready" || profiles.status !== "ready" || reviews.status !== "ready");
  const failed = [model, profiles, reviews].find((r) => r.status === "error");
  return { six, model, profiles, reviews, profile, legacy, pending, failed };
}

export function dimName(model: SixAmModel | undefined, dim: string): string {
  return ((model?.dims || []).find((d) => d.id === dim) || { name: "" }).name;
}

export function reviewText(r: SixAmReview): { head: string; note: string; meta: string } {
  const head = (VERDICT_ZH[r.verdict] || r.verdict) + (r.verdict === "adjust" && r.adjusted_state ? "为 " + r.adjusted_state : "");
  const meta = [r.author, r.created_at ? String(r.created_at).slice(0, 10) : ""].filter(Boolean).join(" · ");
  return { head, note: r.note ? "理由：" + r.note : "", meta: meta ? "记录：" + meta : "" };
}

type Draft = { v: string; to: string; note: string };

function ReviewRow({ dim, model, level, review, onSaved }: {
  dim: string;
  model: SixAmModel;
  level: string | undefined;
  review: SixAmReview | undefined;
  onSaved: (dim: string, review: SixAmReview) => void;
}) {
  const { data, notify } = useProfile();
  const writable = data.permissions.can_review;
  const levels = model.levels || [];
  const [draft, setDraft] = React.useState<Draft>({
    v: review?.verdict || "",
    to: review?.adjusted_state || levels[2] || levels[0] || "",
    note: review?.note || "",
  });
  const [busy, setBusy] = React.useState(false);

  async function save() {
    if (!writable || !data.six_am) return;
    if (!draft.v) {
      notify("请先选择团队结论", "error");
      return;
    }
    if (draft.v === "adjust" && !draft.to) {
      notify("请选择调整后的状态", "error");
      return;
    }
    const body: Record<string, unknown> = {
      profile_id: data.six_am.profile_id,
      dim,
      verdict: draft.v,
      note: draft.note.trim(),
    };
    if (draft.v === "adjust") body.adjusted_state = draft.to;
    setBusy(true);
    try {
      const res = await postJSON<{ ok: boolean; review: SixAmReview }>(
        "/api/reports/" + data.six_am.report_id + "/six-am/reviews",
        body,
      );
      onSaved(dim, res.review);
      setDraft({
        v: res.review.verdict || "",
        to: res.review.adjusted_state || levels[2] || levels[0] || "",
        note: res.review.note || "",
      });
      notify("已记录团队结论", "ok");
    } catch (e) {
      notify(errorText(e, "保存失败"), "error");
    } finally {
      setBusy(false);
    }
  }

  const t = review && review.verdict ? reviewText(review) : null;
  return (
    <div className="border-t border-line py-4" data-dim={dim}>
      <div className="flex flex-wrap items-center gap-2">
        <b>{dim + " " + dimName(model, dim)}</b>
        <Tag tone="soft">{level || "—"}</Tag>
      </div>
      {t ? (
        <div className="mt-2 text-sm">
          <p>{t.head}</p>
          {t.note ? <p className="text-mute">{t.note}</p> : null}
          {t.meta ? <p className="text-mute">{t.meta}</p> : null}
        </div>
      ) : (
        <p className="mt-2 text-sm text-mute">尚无团队结论。</p>
      )}
      {writable ? (
        <div className="mt-3 grid gap-3">
          <div className="flex flex-wrap gap-2" role="group" aria-label="团队结论">
            {(["agree", "adjust", "evidence"] as const).map((v) => (
              <button
                key={v}
                type="button"
                aria-pressed={draft.v === v}
                onClick={() => setDraft((d) => ({ ...d, v }))}
                className={cn(
                  "h-8 border px-3 text-sm font-semibold transition-colors",
                  draft.v === v ? "border-rule bg-ink text-white" : "border-line bg-background hover:bg-sunk",
                )}
              >
                {VERDICT_ZH[v]}
              </button>
            ))}
          </div>
          {draft.v === "adjust" ? (
            <div className="flex items-center gap-2">
              <Label htmlFor={"rv-adj-" + dim} className="text-mute">
                调整为
              </Label>
              <select
                id={"rv-adj-" + dim}
                className={cn(fieldClass, "h-9")}
                value={draft.to}
                onChange={(e) => setDraft((d) => ({ ...d, to: e.target.value }))}
              >
                {levels.map((k) => (
                  <option key={k} value={k}>
                    {k}
                  </option>
                ))}
              </select>
            </div>
          ) : null}
          <div className="grid gap-1.5">
            <Label htmlFor={"rv-note-" + dim} className="text-mute">
              理由与跟进
            </Label>
            <textarea
              id={"rv-note-" + dim}
              rows={2}
              className={cn(fieldClass, "w-full py-2")}
              value={draft.note}
              onChange={(e) => setDraft((d) => ({ ...d, note: e.target.value }))}
            />
          </div>
          <div>
            <Button disabled={busy} onClick={save}>
              保存结论
            </Button>
          </div>
        </div>
      ) : null}
    </div>
  );
}

export default function SixAmTab() {
  const { data, cache, refreshProgress } = useProfile();
  const sa = useSixAm();
  const { six } = sa;

  if (!six) {
    return (
      <div>
        <Empty>暂无 6AM 档案</Empty>
        <div className="text-center">
          <Button variant="outline" asChild>
            <a href="/insights/six-am">打开 6AM</a>
          </Button>
        </div>
      </div>
    );
  }
  const viewHref = "/insights/six-am?view=student&report=" + six.report_id;
  if (sa.failed) return <LoadError error={sa.failed.error} onRetry={sa.failed.reload} />;
  if (sa.pending || !sa.model.data || !sa.profiles.data || !sa.reviews.data) return <Loading />;
  if (sa.legacy) {
    return (
      <div className="flex flex-wrap items-center gap-3">
        <p>这份档案按旧规则生成</p>
        <Button variant="outline" asChild>
          <a href={viewHref}>打开 6AM 档案</a>
        </Button>
      </div>
    );
  }
  const model = sa.model.data.model;
  const reviewsData = sa.reviews.data;
  // 只评议最新档案
  const current = reviewsData.profile_id === six.profile_id ? reviewsData.reviews || {} : {};
  const dimsData = (sa.profile?.profile.dims || {}) as Record<string, { level?: string }>;

  function onSaved(dim: string, review: SixAmReview) {
    cache.set("sixam-reviews", { ...reviewsData, reviews: { ...reviewsData.reviews, [dim]: review } });
    void refreshProgress();
  }

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <p className="text-sm">
          版本 v{six.version} · 报告 {data.latest_report?.report_date || "—"}
        </p>
        <Button variant="outline" asChild>
          <a href={viewHref}>打开 6AM 档案（思维导图）</a>
        </Button>
      </div>
      <Section title="团队结论">
        {DIMS.map((dim) => (
          <ReviewRow
            key={dim}
            dim={dim}
            model={model}
            level={dimsData[dim]?.level}
            review={current[dim]}
            onSaved={onSaved}
          />
        ))}
      </Section>
    </div>
  );
}
