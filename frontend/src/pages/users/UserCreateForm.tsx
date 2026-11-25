import * as React from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

import { CONTROL_CLASS, ROLE_DEFAULTS, type CreatePayload, type Role } from "./model";

type FormState = {
  username: string;
  password: string;
  role: Role;
  advisor_name: string;
  display_name: string;
  student_scope: string;
  detail_level: string;
  m1_access: boolean;
  office_ids: number[];
  is_assessor: boolean;
};

function initialForm(): FormState {
  return {
    username: "",
    password: "",
    role: "viewer",
    advisor_name: "",
    display_name: "",
    office_ids: [],
    is_assessor: false,
    ...ROLE_DEFAULTS.viewer,
  };
}

function applyRole(form: FormState, role: Role): FormState {
  const defaults = ROLE_DEFAULTS[role];
  const student_scope = defaults.student_scope;
  return {
    ...form,
    role,
    student_scope,
    detail_level: defaults.detail_level,
    m1_access: defaults.m1_access,
    is_assessor: role === "front" ? false : form.is_assessor,
    advisor_name: form.advisor_name,
  };
}

export default function UserCreateForm({
  busy,
  locations,
  onCreate,
}: {
  busy: boolean;
  locations: { id: number; name: string }[];
  onCreate: (payload: CreatePayload) => Promise<string | null>;
}) {
  const [form, setForm] = React.useState<FormState>(initialForm);
  const [error, setError] = React.useState("");
  const [notice, setNotice] = React.useState("");

  const isAdmin = form.role === "admin";
  const isViewer = form.role === "viewer";
  const isFront = form.role === "front";
  const showAdvisor = form.role === "admin" || form.role === "advisor";
  const needsOffice = isFront || form.is_assessor;

  function changeRole(role: Role) {
    setForm((current) => applyRole(current, role));
  }

  function changeScope(student_scope: string) {
    setForm((current) => ({ ...current, student_scope }));
  }

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    setError("");
    setNotice("");

    const username = form.username.trim();
    if (!username) {
      setError("请输入账号");
      return;
    }
    if (!form.password) {
      setError("请输入初始密码");
      return;
    }
    const advisor_name = form.advisor_name.trim();
    if (form.student_scope === "own" && !advisor_name) {
      setError("名下学生范围需要绑定顾问姓名");
      return;
    }
    if (needsOffice && form.office_ids.length === 0) {
      setError(isFront ? "前台账号需要绑定办公室" : "测评师需要绑定办公室");
      return;
    }

    const failure = await onCreate({
      username,
      password: form.password,
      role: form.role,
      advisor_name,
      display_name: form.display_name.trim(),
      student_scope: form.student_scope,
      detail_level: form.detail_level,
      m1_access: form.m1_access ? 1 : 0,
      office_id: form.office_ids[0] ?? null,
      office_ids: form.office_ids,
      is_assessor: form.is_assessor ? 1 : 0,
    });
    if (failure) {
      setError(failure);
      return;
    }

    setNotice("已创建：" + username);
    setForm((current) => ({ ...applyRole(current, current.role), username: "", password: "", advisor_name: "", display_name: "" }));
  }

  return (
    <section className="min-w-0 border-t-2 border-rule pt-[9px]" aria-labelledby="users-create-title">
      <h2 id="users-create-title" className="mb-2.5 text-sm font-bold">
        新增用户
      </h2>
      <form className="space-y-3" onSubmit={(event) => void submit(event)}>
        <div className="grid gap-1.5">
          <Label htmlFor="nu">账号</Label>
          <Input
            id="nu"
            value={form.username}
            autoComplete="off"
            placeholder="登录账号"
            disabled={busy}
            onChange={(event) => setForm((current) => ({ ...current, username: event.target.value }))}
          />
        </div>

        <div className="grid gap-1.5">
          <Label htmlFor="np">初始密码</Label>
          <Input
            id="np"
            type="password"
            value={form.password}
            autoComplete="new-password"
            placeholder="初始密码"
            disabled={busy}
            onChange={(event) => setForm((current) => ({ ...current, password: event.target.value }))}
          />
        </div>

        <div className="grid gap-1.5">
          <Label htmlFor="nr">角色</Label>
          <select
            id="nr"
            className={CONTROL_CLASS}
            value={form.role}
            disabled={busy}
            onChange={(event) => changeRole(event.target.value as Role)}
          >
            <option value="viewer">只读</option>
            <option value="advisor">顾问</option>
            <option value="admin">管理员</option>
            <option value="front">前台</option>
          </select>
        </div>

        <div className="grid gap-1.5">
          <span className="text-sm font-medium leading-none">办公室{needsOffice ? "（至少一个）" : "（可选）"}</span>
          <div className="grid grid-cols-2 gap-x-3 gap-y-1.5">
            {locations.map((l) => (
              <label key={l.id} className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  className="h-4 w-4 accent-ink"
                  checked={form.office_ids.includes(l.id)}
                  disabled={busy}
                  onChange={(event) => setForm((current) => ({
                    ...current,
                    office_ids: event.target.checked
                      ? [...current.office_ids, l.id]
                      : current.office_ids.filter((id) => id !== l.id),
                  }))}
                />
                <span>{l.name}</span>
              </label>
            ))}
          </div>
          <p className="text-xs text-mute">第一个勾选的办公室为主办公室；新增授权的办公室需要单独排班后才可预约。</p>
        </div>

        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            className="h-4 w-4 accent-ink"
            checked={form.is_assessor}
            disabled={busy || isFront}
            onChange={(event) => setForm((current) => ({ ...current, is_assessor: event.target.checked }))}
          />
          <span>可接待 Y4（测评师）</span>
        </label>

        {showAdvisor ? (
          <div className="grid gap-1.5">
            <Label htmlFor="na">
              绑定顾问（{form.student_scope === "own" ? "名下学生范围必填" : "可选，工作台默认「我的学生」"}）
            </Label>
            <Input
              id="na"
              value={form.advisor_name}
              autoComplete="off"
              placeholder="顾问姓名"
              disabled={busy}
              onChange={(event) => setForm((current) => ({ ...current, advisor_name: event.target.value }))}
            />
          </div>
        ) : null}

        <div className="grid gap-1.5">
          <Label htmlFor="nd">显示名（可选）</Label>
          <Input
            id="nd"
            value={form.display_name}
            autoComplete="off"
            placeholder="显示名"
            disabled={busy}
            onChange={(event) => setForm((current) => ({ ...current, display_name: event.target.value }))}
          />
        </div>

        <div className="grid gap-1.5">
          <Label htmlFor="nsc">可见学生</Label>
          <select
            id="nsc"
            className={CONTROL_CLASS}
            value={form.student_scope}
            disabled={busy || isAdmin || isFront}
            onChange={(event) => changeScope(event.target.value)}
          >
            <option value="all">全部学生</option>
            <option value="own">名下学生</option>
            {isFront ? <option value="none">无档案范围</option> : null}
          </select>
        </div>

        <div className="grid gap-1.5">
          <Label htmlFor="ndl">可见内容</Label>
          <select
            id="ndl"
            className={CONTROL_CLASS}
            value={form.detail_level}
            disabled={busy || isAdmin || isFront}
            onChange={(event) => setForm((current) => ({ ...current, detail_level: event.target.value }))}
          >
            <option value="full">完整</option>
            <option value="summary">概要</option>
          </select>
        </div>

        <div className="grid gap-1.5">
          <span className="text-sm font-medium leading-none">可用平台</span>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              className="h-4 w-4 accent-ink"
              checked={form.m1_access}
              disabled={busy || isAdmin || isViewer || isFront}
              onChange={(event) => setForm((current) => ({ ...current, m1_access: event.target.checked }))}
            />
            <span>心有灵析</span>
          </label>
        </div>

        <Button type="submit" className="w-full" disabled={busy}>
          {busy ? "添加中…" : "添加"}
        </Button>

        {error ? (
          <p role="status" className="text-sm text-attention">
            {error}
          </p>
        ) : null}
        {notice ? (
          <p role="status" className="text-sm text-s0">
            {notice}
          </p>
        ) : null}

        <p className="text-xs leading-relaxed text-mute">
          完整：可看家长联系方式、问卷答案和分数、解读会纪要，可导出。概要：只看学生档案、Y4、问卷完成状态和 6AM。前台：仅当日预约与账号交接，无档案与报告入口。
        </p>
      </form>
    </section>
  );
}
