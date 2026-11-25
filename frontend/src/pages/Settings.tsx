import * as React from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { errorText, getJSON, postJSON } from "@/lib/api";
import PageHeader from "@/shell/PageHeader";

type Profile = {
  ok: boolean;
  username: string;
  display_name: string;
  role: string;
  role_label: string;
  error?: string;
};

type ProfileState =
  | { status: "loading" }
  | { status: "ready"; profile: Profile }
  | { status: "error"; error: string };

export default function Settings() {
  const [profileState, setProfileState] = React.useState<ProfileState>({ status: "loading" });
  const [current, setCurrent] = React.useState("");
  const [next, setNext] = React.useState("");
  const [confirm, setConfirm] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");
  const [notice, setNotice] = React.useState("");

  React.useEffect(() => {
    let cancelled = false;
    getJSON<Profile>("/api/account")
      .then((data) => {
        if (cancelled) return;
        if (!data.ok) {
          setProfileState({ status: "error", error: data.error || "无法载入账号信息" });
          return;
        }
        setProfileState({ status: "ready", profile: data });
      })
      .catch((err) => {
        if (cancelled) return;
        setProfileState({ status: "error", error: errorText(err, "无法载入账号信息") });
      });
    return () => {
      cancelled = true;
    };
  }, []);

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    setError("");
    setNotice("");
    if (!current) {
      setError("请输入当前密码");
      return;
    }
    if (!next) {
      setError("请输入新密码");
      return;
    }
    if (next !== confirm) {
      setError("两次输入的新密码不一致");
      return;
    }
    setBusy(true);
    try {
      const data = await postJSON<{ ok: boolean; message?: string; error?: string }>(
        "/api/account/password",
        { current_password: current, new_password: next, confirm_password: confirm },
      );
      if (!data.ok) {
        setError(data.error || "修改失败");
        return;
      }
      setCurrent("");
      setNext("");
      setConfirm("");
      setNotice(data.message || "密码已修改。");
    } catch (err) {
      setError(errorText(err, "修改失败"));
    } finally {
      setBusy(false);
    }
  }

  const profile = profileState.status === "ready" ? profileState.profile : null;

  return (
    <div>
      <PageHeader title="个人设置" sub="查看当前登录账号并修改登录密码。" />

      {profileState.status === "loading" ? (
        <p className="text-mute">正在载入账号信息…</p>
      ) : null}

      {profileState.status === "error" ? (
        <div className="border-t-2 border-rule px-4 py-11 text-center">
          <b className="mb-1 block text-base text-ink">无法载入账号信息</b>
          <p className="text-sm text-mute">{profileState.error}</p>
        </div>
      ) : null}

      {profile ? (
        <section className="max-w-[560px] border-t-2 border-rule pt-[9px]" aria-labelledby="settings-account-title">
          <h2 id="settings-account-title" className="mb-2.5 text-sm font-bold">
            账号与密码
          </h2>
          <form className="space-y-3" onSubmit={(event) => void submit(event)}>
            <div className="grid gap-1.5">
              <Label htmlFor="set-username">登录名</Label>
              <Input id="set-username" value={profile.username} readOnly disabled autoComplete="username" />
              <p className="text-xs text-mute">
                当前身份：{profile.role_label}。登录名不可在此修改。
              </p>
            </div>

            <div className="grid gap-1.5">
              <Label htmlFor="set-current">当前密码</Label>
              <Input
                id="set-current"
                type="password"
                value={current}
                autoComplete="current-password"
                placeholder="当前密码"
                disabled={busy}
                onChange={(event) => setCurrent(event.target.value)}
              />
            </div>

            <div className="grid gap-1.5">
              <Label htmlFor="set-new">新密码</Label>
              <Input
                id="set-new"
                type="password"
                value={next}
                autoComplete="new-password"
                placeholder="新密码"
                disabled={busy}
                onChange={(event) => setNext(event.target.value)}
              />
            </div>

            <div className="grid gap-1.5">
              <Label htmlFor="set-confirm">确认新密码</Label>
              <Input
                id="set-confirm"
                type="password"
                value={confirm}
                autoComplete="new-password"
                placeholder="再次输入新密码"
                disabled={busy}
                onChange={(event) => setConfirm(event.target.value)}
              />
            </div>

            <Button type="submit" className="w-full" disabled={busy}>
              {busy ? "保存中…" : "保存"}
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
              修改成功后当前登录状态保持有效，下次登录请使用新密码。密码只提交给服务端校验，不会保存在浏览器中。
            </p>
          </form>
        </section>
      ) : null}
    </div>
  );
}
