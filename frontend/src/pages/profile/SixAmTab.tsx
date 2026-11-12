import * as React from "react";
import { useSearchParams } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { errorText, getJSON, postJSON } from "@/lib/api";
import { cn } from "@/lib/utils";

import {
  Chip,
  DIMS,
  Empty,
  fieldClass,
  levelTone,
  Loading,
  LoadError,
  Section,
  useProfile,
  useResource,
  VERDICT_ZH,
  type SixAmModel,
  type SixAmProfileRow,
  type SixAmReview,
  type SixAmView,
} from "./common";
import { loadMindmap, mindmapHTML } from "./sixamShim";
import "./sixam.css";

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
        <Chip tone={levelTone(level, model.levels)}>{level || "—"}</Chip>
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

const A_DIMS = ["A1", "A2", "A3", "A4", "A5"];
const BTN = "inline-flex h-7 items-center gap-1.5 border px-2.5 text-[12.5px] font-semibold transition-colors";

function firstDim(view: SixAmView): string {
  const hit = (view.profile.order || []).find((id) => A_DIMS.includes(id));
  return hit || "A1";
}

function dimIds(view: SixAmView): string[] {
  const order = (view.profile.order || []).filter((id) => A_DIMS.includes(id));
  return order.length ? order : A_DIMS;
}

type TalkRecord = { result: string; causes: string[]; note: string; set_level?: string };

/** 与 student.js 的 gatherTalk 同：没选结论返回 null。 */
function gatherTalk(box: HTMLElement): { dim: string; record: TalkRecord } | null {
  const pressed = box.querySelector('[data-talk-result][aria-pressed="true"]');
  if (!pressed) return null;
  const record: TalkRecord = { result: pressed.getAttribute("data-talk-result") || "", causes: [], note: "" };
  box.querySelectorAll("[data-talk-cause]:checked").forEach((input) => {
    record.causes.push(input.getAttribute("data-talk-cause") || "");
  });
  const note = box.querySelector<HTMLInputElement>("[data-talk-note]");
  if (note) record.note = note.value.trim();
  if (record.result === "set") {
    const level = box.querySelector<HTMLSelectElement>("[data-talk-level]");
    record.set_level = level ? level.value : "关注";
  }
  return { dim: box.getAttribute("data-talk") || "", record };
}

type FtDraft = { judgement: string; time_on_liked: string; confirmed_full: string; can_split: string; can_commit: string; complaint: string };

function triValue(v: boolean | null | undefined): string {
  return v === true ? "true" : v === false ? "false" : "";
}
function triOut(v: string): boolean | null {
  return v === "" ? null : v === "true";
}

function ftDraftOf(view: SixAmView): FtDraft {
  const inputs = view.profile.inputs || {};
  const ft = inputs.ft || {};
  const complaint = inputs.parent && typeof inputs.parent.complaint === "object" ? inputs.parent.complaint : {};
  return {
    judgement: ft.goal?.judgement || "",
    time_on_liked: triValue(ft.goal?.time_on_liked),
    confirmed_full: triValue(ft.schedule?.confirmed_full),
    can_split: triValue(ft.standard_task?.can_split),
    can_commit: triValue(ft.standard_task?.can_commit),
    complaint: (complaint && complaint.text) || "",
  };
}

const SELECT = cn(fieldClass, "h-9 w-full");

function FtField({ id, label, value, options, onChange }: {
  id: string;
  label: string;
  value: string;
  options: [string, string][];
  onChange: (v: string) => void;
}) {
  return (
    <div className="grid gap-1.5">
      <Label htmlFor={id} className="text-mute">
        {label}
      </Label>
      <select id={id} className={SELECT} value={value} onChange={(e) => onChange(e.target.value)}>
        {options.map(([v, t]) => (
          <option key={v} value={v}>
            {t}
          </option>
        ))}
      </select>
    </div>
  );
}

function FtDrawer({ view, open, busy, onOpenChange, onSave }: {
  view: SixAmView;
  open: boolean;
  busy: boolean;
  onOpenChange: (open: boolean) => void;
  onSave: (body: Record<string, unknown>) => void;
}) {
  const [d, setD] = React.useState<FtDraft>(() => ftDraftOf(view));
  React.useEffect(() => {
    if (open) setD(ftDraftOf(view));
  }, [open, view]);
  const set = (k: keyof FtDraft) => (v: string) => setD((x) => ({ ...x, [k]: v }));
  const TRI: [string, string][] = [["", "未问"], ["true", "是"], ["false", "否"]];
  const YN: [string, string][] = [["", "—"], ["true", "是"], ["false", "否"]];
  function save() {
    onSave({
      ft: {
        goal: { judgement: d.judgement || null, time_on_liked: triOut(d.time_on_liked) },
        standard_task: { can_split: triOut(d.can_split), can_commit: triOut(d.can_commit) },
        schedule: { confirmed_full: triOut(d.confirmed_full) },
      },
      parent: { complaint: { text: d.complaint.trim() } },
    });
  }
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="w-full overflow-y-auto sm:max-w-[440px]" aria-describedby={undefined}>
        <SheetHeader>
          <SheetTitle>录入 First Touch</SheetTitle>
        </SheetHeader>
        <div className="mt-4 grid gap-4">
          <fieldset className="grid gap-3 border border-line p-3">
            <legend className="px-1 text-[12.5px] font-semibold text-ink-2">目标认同</legend>
            <FtField
              id="ft-judge"
              label="学生是否认同目标"
              value={d.judgement}
              options={[["", "—"], ["认同", "认同"], ["部分认同", "部分认同"], ["不认同", "不认同"]]}
              onChange={set("judgement")}
            />
          </fieldset>
          <fieldset className="grid gap-3 border border-line p-3">
            <legend className="px-1 text-[12.5px] font-semibold text-ink-2">时间</legend>
            <FtField id="ft-liked" label="时间主要花在喜欢的事上" value={d.time_on_liked} options={TRI} onChange={set("time_on_liked")} />
            <FtField id="ft-full" label="会谈前确认时间排满" value={d.confirmed_full} options={TRI} onChange={set("confirmed_full")} />
          </fieldset>
          <fieldset className="grid gap-3 border border-line p-3">
            <legend className="px-1 text-[12.5px] font-semibold text-ink-2">标准化任务</legend>
            <FtField id="ft-split" label="能拆出步骤" value={d.can_split} options={YN} onChange={set("can_split")} />
            <FtField id="ft-commit" label="能开始" value={d.can_commit} options={YN} onChange={set("can_commit")} />
          </fieldset>
          <fieldset className="grid gap-3 border border-line p-3">
            <legend className="px-1 text-[12.5px] font-semibold text-ink-2">家长主诉</legend>
            <textarea
              aria-label="家长主诉"
              rows={4}
              className={cn(fieldClass, "w-full py-2")}
              value={d.complaint}
              onChange={(e) => set("complaint")(e.target.value)}
            />
          </fieldset>
          <div className="flex gap-2">
            <Button disabled={busy} onClick={save}>
              保存
            </Button>
            <Button variant="outline" onClick={() => onOpenChange(false)}>
              取消
            </Button>
          </div>
        </div>
      </SheetContent>
    </Sheet>
  );
}

function A6Panel({ view }: { view: SixAmView }) {
  const a6 = view.profile.a6 || {};
  const ranked = a6.ranked || [];
  const top = ranked.filter((r) => r.top);
  const others = ranked.filter((r) => !r.top);
  const avoid = a6.avoid || [];
  const item = (r: (typeof ranked)[number], i: number) => (
    <li key={i} className="a6item">
      <span className="nm">{r.name || ""}</span>
      {r.fit_label === "慎用" ? <span className="warn">慎用</span> : null}
      {(r.why || []).map((t, j) => (
        <span key={j} className="why">
          {t}
        </span>
      ))}
    </li>
  );
  return (
    <div className="a6">
      <h2>先用</h2>
      {top.length ? <ul className="a6list">{top.map(item)}</ul> : <p className="text-mute">—</p>}
      <details className="a6more">
        <summary>其他（{others.length}）</summary>
        {others.length ? <ul className="a6list">{others.map(item)}</ul> : <p className="text-mute">—</p>}
      </details>
      <h2>不用</h2>
      {avoid.length ? (
        <ul className="a6list">
          {avoid.map((r, i) => (
            <li key={i} className="a6item">
              <span className="nm">{r.name || ""}</span>
              <span className="no">{r.why || ""}</span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-mute">—</p>
      )}
    </div>
  );
}

/** 6AM 学生视图：逻辑与 static/js/six_am/student.js 一致，导图 HTML 仍由 mindmap.js 生成。 */
function StudentView({ reportId, model, writable, onChanged }: {
  reportId: number;
  model: SixAmModel;
  writable: boolean;
  onChanged: () => void;
}) {
  const { notify } = useProfile();
  const [params, setParams] = useSearchParams();
  const [view, setView] = React.useState<SixAmView | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [mmReady, setMmReady] = React.useState(false);
  const [mmError, setMmError] = React.useState<string | null>(null);
  const [drawer, setDrawer] = React.useState(false);
  const [busy, setBusy] = React.useState(false);
  const base = "/api/reports/" + encodeURIComponent(String(reportId)) + "/six-am";

  const fetchView = React.useCallback(
    async (profileId?: number | string) => {
      setError(null);
      try {
        const res = await getJSON<SixAmView>(base + (profileId != null ? "?profile_id=" + encodeURIComponent(String(profileId)) : ""));
        setView(res);
      } catch (e) {
        setView(null);
        setError(errorText(e, "加载失败"));
      }
    },
    [base],
  );

  React.useEffect(() => {
    void fetchView();
  }, [fetchView]);

  React.useEffect(() => {
    let live = true;
    loadMindmap().then(
      () => live && setMmReady(true),
      (e: unknown) => live && setMmError(errorText(e, "思维导图脚本加载失败")),
    );
    return () => {
      live = false;
    };
  }, []);

  // 写入后档案的版本 +1：显示新档案，刷新评议与进度
  function applyWrite(res: SixAmView) {
    setView(res);
    onChanged();
  }

  async function write(path: "inputs" | "generate", body?: Record<string, unknown>, done?: () => void) {
    setBusy(true);
    try {
      const res = await postJSON<SixAmView>(base + "/" + path, body);
      applyWrite(res);
      done?.();
    } catch (e) {
      notify(errorText(e, "保存失败"), "error");
    } finally {
      setBusy(false);
    }
  }

  const dimParam = params.get("dim");
  const dim = dimParam && (A_DIMS.includes(dimParam) || dimParam === "A6") ? dimParam : view ? firstDim(view) : "A1";
  function pickDim(id: string) {
    const next = new URLSearchParams(params);
    next.set("dim", id);
    setParams(next, { replace: true });
  }

  const html = React.useMemo(
    () => (view && mmReady && !view.legacy && dim !== "A6" ? mindmapHTML(model, dim, view.profile, writable) : ""),
    [view, mmReady, dim, model, writable],
  );

  function onMapClick(e: React.MouseEvent<HTMLDivElement>) {
    const target = (e.target as HTMLElement).closest<HTMLElement>("[data-talk-result],[data-talk-save],[data-talk-clear]");
    if (!target || !writable) return;
    if (target.hasAttribute("data-talk-result")) {
      const group = target.parentElement;
      group?.querySelectorAll("[data-talk-result]").forEach((b) => b.setAttribute("aria-pressed", String(b === target)));
      const box = target.closest<HTMLElement>("[data-talk]");
      const level = box?.querySelector<HTMLElement>("[data-talk-level]");
      if (level) level.hidden = target.getAttribute("data-talk-result") !== "set";
      return;
    }
    const box = target.closest<HTMLElement>("[data-talk]");
    if (!box) return;
    if (target.hasAttribute("data-talk-save")) {
      const got = gatherTalk(box);
      if (!got) {
        notify("先选择 证实 / 未证实 / 调整为", "error");
        return;
      }
      void write("inputs", { talks: { [got.dim]: got.record } });
      return;
    }
    void write("inputs", { talks: { [box.getAttribute("data-talk") || ""]: null } });
  }

  if (error) {
    return (
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <p>{error}</p>
        {writable ? (
          <Button disabled={busy} onClick={() => void write("generate")}>
            生成
          </Button>
        ) : null}
        <Button variant="outline" onClick={() => void fetchView()}>
          重试
        </Button>
      </div>
    );
  }
  if (!view) return <Loading />;

  const dimsData = view.profile.dims || {};
  const flags = view.profile.flags || {};
  const versions = view.versions || [];
  const a6Name = model.a6?.name || "";

  return (
    <div>
      {view.legacy ? null : (
        <div className="mb-3 flex flex-wrap items-center gap-2" role="group" aria-label="维度">
          {dimIds(view).map((id) => (
            <button
              key={id}
              type="button"
              aria-pressed={dim === id}
              onClick={() => pickDim(id)}
              className={cn(BTN, dim === id ? "border-rule bg-ink text-white" : "border-line bg-background hover:bg-sunk")}
            >
              {id + " " + dimName(model, id)}
              <Chip tone={levelTone(dimsData[id]?.level, model.levels)} className="h-[18px]">
                {dimsData[id]?.level || "—"}
              </Chip>
            </button>
          ))}
          <button
            type="button"
            aria-pressed={dim === "A6"}
            onClick={() => pickDim("A6")}
            className={cn(BTN, dim === "A6" ? "border-rule bg-ink text-white" : "border-line bg-background hover:bg-sunk")}
          >
            {"A6 " + a6Name}
          </button>
        </div>
      )}
      {flags.safety ? (
        <div className="mb-3 border border-s3 bg-s3-bg px-3 py-2 text-[13px] text-s3" role="status">
          <b>情绪安全复核</b>
        </div>
      ) : null}
      {flags.answer_state ? (
        <div className="mb-3 border border-s1 bg-s1-bg px-3 py-2 text-[13px] text-s1" role="status">
          <b>答题状态提示</b>
        </div>
      ) : null}
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <p className="flex items-center gap-1.5 text-sm">
          <span className="text-mute">版本</span>
          {versions.length > 1 ? (
            <select
              aria-label="版本"
              className={cn(fieldClass, "h-8")}
              value={String(view.profile_id)}
              onChange={(e) => void fetchView(e.target.value)}
            >
              {versions.map((v) => (
                <option key={v.profile_id} value={String(v.profile_id)}>
                  {"v" + v.version}
                </option>
              ))}
            </select>
          ) : (
            <span>v{view.version}</span>
          )}
          <span>· 报告 {view.report_date || "—"}</span>
        </p>
        {writable ? (
          <div className="ml-auto flex flex-wrap items-center gap-2">
            {view.legacy ? null : (
              <Button variant="outline" size="sm" onClick={() => setDrawer(true)}>
                录入 First Touch
              </Button>
            )}
            <Button variant="outline" size="sm" disabled={busy} onClick={() => void write("generate")}>
              {view.legacy ? "按新规则重新生成" : "重新生成"}
            </Button>
          </div>
        ) : null}
      </div>
      {view.legacy ? (
        <p>这份档案按旧规则生成</p>
      ) : mmError ? (
        <p>{mmError}</p>
      ) : dim === "A6" ? (
        <div className="sx-panel">
          <A6Panel view={view} />
        </div>
      ) : !mmReady ? (
        <Loading />
      ) : (
        <div className="sx-panel" onClick={onMapClick} dangerouslySetInnerHTML={{ __html: html }} />
      )}
      {writable && !view.legacy ? (
        <FtDrawer
          view={view}
          open={drawer}
          busy={busy}
          onOpenChange={setDrawer}
          onSave={(body) => void write("inputs", body, () => setDrawer(false))}
        />
      ) : null}
    </div>
  );
}

export default function SixAmTab() {
  const { data, cache, refreshProgress, refreshPage, notify } = useProfile();
  const sa = useSixAm();
  const { six } = sa;
  const writable = data.permissions.can_write;

  const [genBusy, setGenBusy] = React.useState(false);

  if (!six) {
    const rid = data.latest_report?.id;
    async function generate() {
      if (!rid) return;
      setGenBusy(true);
      try {
        await postJSON("/api/reports/" + rid + "/six-am/generate");
        cache.invalidate("sixam-model", "sixam-profiles", "sixam-reviews");
        await refreshPage();
        void refreshProgress();
      } catch (e) {
        notify(errorText(e, "生成失败"), "error");
      } finally {
        setGenBusy(false);
      }
    }
    return (
      <div>
        <Empty>暂无 6AM 档案</Empty>
        <div className="text-center">
          {writable && rid ? (
            <Button disabled={genBusy} onClick={() => void generate()}>
              生成
            </Button>
          ) : !writable ? (
            <a className="text-sm underline" href="/insights/six-am">
              打开 6AM
            </a>
          ) : null}
        </div>
      </div>
    );
  }
  if (sa.failed) return <LoadError error={sa.failed.error} onRetry={sa.failed.reload} />;
  if (!sa.model.data || !sa.profiles.data || !sa.reviews.data) return <Loading />;
  const model = sa.model.data.model;
  const reviewsData = sa.reviews.data;
  // 只评议最新档案
  const current = reviewsData.profile_id === six.profile_id ? reviewsData.reviews || {} : {};
  const dimsData = (sa.profile?.profile.dims || {}) as Record<string, { level?: string }>;

  function onSaved(dim: string, review: SixAmReview) {
    cache.set("sixam-reviews", { ...reviewsData, reviews: { ...reviewsData.reviews, [dim]: review } });
    void refreshProgress();
  }

  // 写入（会谈记录 / First Touch / 重新生成）后：新档案已显示，这里刷新评议、档案列表与进度
  async function onChanged() {
    const rid = String(six!.report_id);
    const code = encodeURIComponent(data.student.code);
    try {
      const [reviews, profiles] = await Promise.all([
        getJSON<ReviewsResp>("/api/reports/" + rid + "/six-am/reviews"),
        getJSON<{ profiles: SixAmProfileRow[] }>("/students/" + code + "/api/six-am"),
      ]);
      cache.set("sixam-reviews", reviews);
      cache.set("sixam-profiles", profiles);
    } catch {
      // 保留旧数据
    }
    await refreshPage();
    void refreshProgress();
  }

  return (
    <div className="sixam">
      <StudentView reportId={six.report_id} model={model} writable={writable} onChanged={() => void onChanged()} />
      {sa.legacy ? null : (
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
      )}
    </div>
  );
}
