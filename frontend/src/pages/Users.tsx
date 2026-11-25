import * as React from "react";
import { RefreshCw } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError, deleteJSON, errorText, getJSON, postJSON, putJSON } from "@/lib/api";
import { cn } from "@/lib/utils";
import PageHeader from "@/shell/PageHeader";

import { PERM_OK, type CheckResponse, type CreatePayload, type ListResponse, type Me, type Role, type UserRow } from "./users/model";
import UserCreateForm from "./users/UserCreateForm";
import UserTable from "./users/UserTable";

type IdentityState =
  | { status: "loading" }
  | { status: "ready"; me: Me }
  | { status: "unauth" }
  | { status: "error"; error: string };

type ListState =
  | { status: "loading" }
  | { status: "ready"; data: ListResponse }
  | { status: "denied"; error: string }
  | { status: "error"; error: string };

type DialogState =
  | { kind: "password"; user: UserRow }
  | { kind: "advisor"; user: UserRow }
  | { kind: "delete"; user: UserRow };

type MutationResult = { ok: true } | { ok: false; error: string };

function StatePanel({ title, line, action }: { title: string; line?: string; action?: React.ReactNode }) {
  return (
    <div className="border-t-2 border-rule px-4 py-11 text-center">
      <b className="mb-1 block text-base text-ink">{title}</b>
      {line ? <p className="text-sm text-mute">{line}</p> : null}
      {action ? <div className="mt-3">{action}</div> : null}
    </div>
  );
}

function LoadingPanel() {
  return (
    <div className="border-t-2 border-rule py-4" aria-busy="true">
      <Skeleton className="mb-3 h-4 w-64 max-w-full" />
      <Skeleton className="mb-3 h-4 w-48 max-w-full" />
      <Skeleton className="h-4 w-56 max-w-full" />
    </div>
  );
}

export default function Users() {
  const [identity, setIdentity] = React.useState<IdentityState>({ status: "loading" });
  const [identityReload, setIdentityReload] = React.useState(0);
  const [listState, setListState] = React.useState<ListState>({ status: "loading" });
  const [notice, setNotice] = React.useState<{ kind: "ok" | "error"; text: string } | null>(null);
  const [creating, setCreating] = React.useState(false);
  const [busyIds, setBusyIds] = React.useState<Set<number>>(new Set());
  const [locations, setLocations] = React.useState<{ id: number; name: string }[]>([]);
  const busyRef = React.useRef<Set<number>>(new Set());
  const listSeq = React.useRef(0);

  const loadList = React.useCallback(async () => {
    const seq = ++listSeq.current;
    setListState({ status: "loading" });
    try {
      const data = await getJSON<ListResponse>("/api/users");
      if (seq !== listSeq.current) return;
      if (!data.ok) {
        setListState({ status: "error", error: data.error || "加载失败" });
        return;
      }
      setListState({ status: "ready", data });
    } catch (error) {
      if (seq !== listSeq.current) return;
      if (error instanceof ApiError && error.status === 403) {
        setListState({ status: "denied", error: errorText(error, "无权访问") });
      } else {
        setListState({ status: "error", error: errorText(error, "加载失败") });
      }
    }
  }, []);

  React.useEffect(() => {
    let cancelled = false;
    setIdentity({ status: "loading" });
    setListState({ status: "loading" });
    getJSON<CheckResponse>("/api/admin/check")
      .then((data) => {
        if (cancelled) return;
        if (!data.ok) {
          setIdentity({ status: "error", error: "无法确认登录身份。" });
        } else if (!data.authenticated || data.user_id == null) {
          setIdentity({ status: "unauth" });
        } else {
          setIdentity({
            status: "ready",
            me: {
              user_id: data.user_id,
              role: data.role || "",
              display_name: data.display_name || "",
              advisor_name: data.advisor_name || "",
            },
          });
        }
      })
      .catch((error) => {
        if (cancelled) return;
        setIdentity({ status: "error", error: errorText(error, "无法确认登录身份。") });
      });
    return () => {
      cancelled = true;
    };
  }, [identityReload]);

  React.useEffect(() => {
    if (identity.status === "ready") {
      void loadList();
      getJSON<{ locations: { id: number; name: string }[] }>("/api/locations")
        .then((r) => setLocations(r.locations))
        .catch(() => setLocations([]));
    }
  }, [identity.status, loadList]);

  function markBusy(id: number, busy: boolean) {
    if (busy) busyRef.current.add(id);
    else busyRef.current.delete(id);
    setBusyIds(new Set(busyRef.current));
  }

  async function sendPut(id: number, payload: Record<string, unknown>): Promise<MutationResult> {
    try {
      const data = await putJSON<{ ok: boolean; error?: string }>("/api/users/" + id, payload);
      if (!data.ok) return { ok: false, error: data.error || "操作失败" };
      return { ok: true };
    } catch (error) {
      return { ok: false, error: errorText(error, "操作失败") };
    }
  }

  async function runRowMutation(id: number, payload: Record<string, unknown>, okText: string) {
    if (busyRef.current.has(id)) return;
    markBusy(id, true);
    try {
      const result = await sendPut(id, payload);
      if (result.ok) setNotice({ kind: "ok", text: okText });
      else setNotice({ kind: "error", text: result.error });
      await loadList();
    } finally {
      markBusy(id, false);
    }
  }

  async function createUser(payload: CreatePayload): Promise<string | null> {
    setCreating(true);
    try {
      const data = await postJSON<{ ok: boolean; error?: string }>("/api/users", payload);
      if (!data.ok) return data.error || "创建失败";
      await loadList();
      return null;
    } catch (error) {
      return errorText(error, "创建失败");
    } finally {
      setCreating(false);
    }
  }

  function changeRole(user: UserRow, role: Role) {
    const payload: Record<string, unknown> = { role };
    if (role !== "advisor") payload.advisor_name = "";
    void runRowMutation(user.id, payload, "角色已更新");
  }

  function changeScope(user: UserRow, scope: string) {
    void runRowMutation(user.id, { student_scope: scope }, PERM_OK);
  }

  async function changeOffice(user: UserRow, officeIds: number[]) {
    if (busyRef.current.has(user.id)) return;
    markBusy(user.id, true);
    try {
      const data = await putJSON<{
        ok: boolean;
        error?: string;
        reassignments?: { booking_id: number; student_name: string; appointment_time: string }[];
      }>("/api/users/" + user.id, {
        office_ids: officeIds,
        office_id: officeIds[0] ?? null,
      });
      if (!data.ok) {
        setNotice({ kind: "error", text: data.error || "办公室更新失败" });
      } else {
        const pending = data.reassignments || [];
        setNotice({
          kind: "ok",
          text: pending.length
            ? `办公室已更新。${pending.length} 个未来预约需重新安排：` +
              pending.slice(0, 3).map((item) => `${item.student_name} ${item.appointment_time.slice(5, 16).replace("T", " ")}`).join("、") +
              (pending.length > 3 ? " 等" : "")
            : "办公室已更新",
        });
      }
      await loadList();
    } catch (error) {
      setNotice({ kind: "error", text: errorText(error, "办公室更新失败") });
    } finally {
      markBusy(user.id, false);
    }
  }

  function changeAssessor(user: UserRow, checked: boolean) {
    void runRowMutation(user.id, { is_assessor: checked ? 1 : 0 }, "测评师设置已更新");
  }

  function changeDetail(user: UserRow, detail: string) {
    void runRowMutation(user.id, { detail_level: detail }, PERM_OK);
  }

  function changeM1(user: UserRow, checked: boolean) {
    void runRowMutation(user.id, { m1_access: checked ? 1 : 0 }, PERM_OK);
  }

  function changeM1Admin(user: UserRow, checked: boolean) {
    void runRowMutation(user.id, { m1_admin: checked ? 1 : 0 }, PERM_OK);
  }

  function toggleActive(user: UserRow) {
    const turningOn = !user.is_active;
    void runRowMutation(user.id, { is_active: turningOn ? 1 : 0 }, turningOn ? "已启用" : "已停用");
  }

  const [dialog, setDialog] = React.useState<DialogState | null>(null);
  const [dialogValue, setDialogValue] = React.useState("");
  const [dialogError, setDialogError] = React.useState("");
  const [dialogBusy, setDialogBusy] = React.useState(false);

  function openDialog(next: DialogState) {
    setDialog(next);
    setDialogError("");
    setDialogValue(next.kind === "advisor" ? next.user.advisor_name || "" : "");
  }

  function closeDialog() {
    if (dialogBusy) return;
    setDialog(null);
    setDialogError("");
    setDialogValue("");
  }

  async function confirmDialog() {
    const current = dialog;
    if (!current || dialogBusy) return;
    setDialogError("");
    if (current.kind === "password" && !dialogValue) {
      setDialogError("密码不能为空");
      return;
    }
    setDialogBusy(true);
    try {
      if (current.kind === "delete") {
        let data: { ok: boolean; error?: string };
        try {
          data = await deleteJSON<{ ok: boolean; error?: string }>("/api/users/" + current.user.id);
        } catch (error) {
          setDialogError(errorText(error, "删除失败"));
          return;
        }
        if (!data.ok) {
          setDialogError(data.error || "删除失败");
          return;
        }
        setNotice({ kind: "ok", text: "已删除" });
      } else {
        const payload = current.kind === "password" ? { password: dialogValue } : { advisor_name: dialogValue.trim() };
        const result = await sendPut(current.user.id, payload);
        if (!result.ok) {
          setDialogError(result.error);
          return;
        }
        setNotice({ kind: "ok", text: current.kind === "password" ? "密码已重置" : "绑定顾问已更新" });
      }
      setDialog(null);
      await loadList();
    } finally {
      setDialogBusy(false);
    }
  }

  let sub = "正在载入…";
  if (identity.status === "ready") {
    if (listState.status === "ready") {
      sub = listState.data.limited ? "开关顾问账号的心有灵析权限。" : "创建账号、分配角色与绑定顾问。仅管理员可见。";
    } else if (listState.status === "denied") {
      sub = "无权访问。";
    } else if (listState.status === "error") {
      sub = "无法载入用户列表。";
    }
  } else if (identity.status === "unauth") {
    sub = "登录状态已失效。";
  } else if (identity.status === "error") {
    sub = "无法确认登录身份。";
  }

  const dialogTitle = dialog ? (dialog.kind === "password" ? "重置密码" : dialog.kind === "advisor" ? "绑定顾问" : "删除用户") : "";
  const dialogAction = dialog ? (dialog.kind === "password" ? "重置密码" : dialog.kind === "advisor" ? "保存" : "确认删除") : "";

  return (
    <div>
      <PageHeader
        title="用户管理"
        sub={sub}
        actions={
          <a href="/system/users" className="text-xs text-mute hover:underline">
            旧版用户管理
          </a>
        }
      />

      {identity.status === "loading" ? <LoadingPanel /> : null}

      {identity.status === "unauth" ? (
        <StatePanel
          title="未登录"
          line="登录状态已失效，请重新登录。"
          action={
            <Button asChild variant="outline">
              <a href="/login">去登录</a>
            </Button>
          }
        />
      ) : null}

      {identity.status === "error" ? (
        <StatePanel
          title="无法确认登录身份"
          line={identity.error}
          action={
            <Button variant="outline" onClick={() => setIdentityReload((n) => n + 1)}>
              重试
            </Button>
          }
        />
      ) : null}

      {identity.status === "ready" && listState.status === "loading" ? <LoadingPanel /> : null}

      {identity.status === "ready" && listState.status === "denied" ? (
        <StatePanel title="无权访问" line={listState.error || "该账号没有用户管理的权限。"} />
      ) : null}

      {identity.status === "ready" && listState.status === "error" ? (
        <StatePanel
          title="无法载入用户列表"
          line={listState.error}
          action={
            <Button variant="outline" onClick={() => void loadList()}>
              重试
            </Button>
          }
        />
      ) : null}

      {identity.status === "ready" && listState.status === "ready" ? (
        <div
          className={cn(
            "grid grid-cols-1 gap-4",
            !listState.data.limited && "lg:grid-cols-[minmax(280px,360px)_minmax(0,1fr)]",
          )}
        >
          {listState.data.limited ? null : (
            <UserCreateForm busy={creating} locations={locations} onCreate={createUser} />
          )}

          <section className="min-w-0 border-t-2 border-rule pt-[9px]" aria-labelledby="users-list-title">
            <div className="mb-2.5 flex flex-wrap items-center gap-x-2 gap-y-1">
              <h2 id="users-list-title" className="text-sm font-bold">
                用户列表
              </h2>
              <div className="ml-auto">
                <Button variant="outline" size="sm" onClick={() => void loadList()}>
                  <RefreshCw className="h-3.5 w-3.5" aria-hidden="true" />
                  刷新
                </Button>
              </div>
            </div>

            {notice ? (
              <p
                role="status"
                aria-live="polite"
                className={cn("mb-2.5 text-sm", notice.kind === "error" ? "text-attention" : "text-s0")}
              >
                {notice.text}
              </p>
            ) : null}

            {listState.data.users.length === 0 ? (
              <StatePanel title="暂无用户" />
            ) : (
              <UserTable
                users={listState.data.users}
                limited={listState.data.limited === true}
                meId={identity.me.user_id}
                busyIds={busyIds}
                locations={locations}
                onRole={changeRole}
                onOffice={changeOffice}
                onAssessor={changeAssessor}
                onScope={changeScope}
                onDetail={changeDetail}
                onM1={changeM1}
                onM1Admin={changeM1Admin}
                onToggleActive={toggleActive}
                onResetPassword={(user) => openDialog({ kind: "password", user })}
                onEditAdvisor={(user) => openDialog({ kind: "advisor", user })}
                onDelete={(user) => openDialog({ kind: "delete", user })}
              />
            )}
          </section>
        </div>
      ) : null}

      <Dialog
        open={dialog !== null}
        onOpenChange={(open) => {
          if (!open) closeDialog();
        }}
      >
        <DialogContent className="max-h-[calc(100vh-2rem)] w-[calc(100vw-2rem)] max-w-md overflow-y-auto sm:rounded-none">
          <DialogHeader>
            <DialogTitle>{dialogTitle}</DialogTitle>
          </DialogHeader>

          {dialog?.kind === "delete" ? (
            <p className="text-sm">确认删除账号「{dialog.user.username}」？此操作不可撤销。</p>
          ) : null}

          {dialog?.kind === "password" ? (
            <div className="grid gap-1.5">
              <Label htmlFor="ud-value">新密码</Label>
              <Input
                id="ud-value"
                type="password"
                autoComplete="new-password"
                autoFocus
                value={dialogValue}
                onChange={(event) => setDialogValue(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter") {
                    event.preventDefault();
                    void confirmDialog();
                  }
                }}
              />
              <p className="text-xs text-mute">旧密码将立即失效。取消不会发送请求。</p>
            </div>
          ) : null}

          {dialog?.kind === "advisor" ? (
            <div className="grid gap-1.5">
              <Label htmlFor="ud-value">顾问姓名</Label>
              <Input
                id="ud-value"
                value={dialogValue}
                autoComplete="off"
                autoFocus
                onChange={(event) => setDialogValue(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter") {
                    event.preventDefault();
                    void confirmDialog();
                  }
                }}
              />
              <p className="text-xs text-mute">用于数据隔离。取消不会发送请求。</p>
            </div>
          ) : null}

          {dialogError ? (
            <p role="status" className="text-sm text-attention">
              {dialogError}
            </p>
          ) : null}

          <DialogFooter className="gap-2 sm:gap-0">
            <Button variant="outline" disabled={dialogBusy} onClick={closeDialog}>
              取消
            </Button>
            <Button disabled={dialogBusy || (dialog?.kind === "password" && !dialogValue)} onClick={() => void confirmDialog()}>
              {dialogBusy ? "处理中…" : dialogAction}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
