import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { cn } from "@/lib/utils";

import { ROLE_LABEL, ROW_CONTROL_CLASS, type Role, type UserRow } from "./model";

type Props = {
  users: UserRow[];
  limited: boolean;
  meId: number;
  busyIds: ReadonlySet<number>;
  locations: { id: number; name: string }[];
  onRole: (user: UserRow, role: Role) => void;
  onOffice: (user: UserRow, officeId: string) => void;
  onAssessor: (user: UserRow, checked: boolean) => void;
  onScope: (user: UserRow, scope: string) => void;
  onDetail: (user: UserRow, detail: string) => void;
  onM1: (user: UserRow, checked: boolean) => void;
  onM1Admin: (user: UserRow, checked: boolean) => void;
  onToggleActive: (user: UserRow) => void;
  onResetPassword: (user: UserRow) => void;
  onEditAdvisor: (user: UserRow) => void;
  onDelete: (user: UserRow) => void;
};

function StatusBadge({ active }: { active: boolean }) {
  return (
    <span
      className={cn(
        "inline-flex h-[22px] items-center gap-1.5 whitespace-nowrap px-2 text-[12.5px] font-semibold",
        active ? "bg-s0-bg text-s0" : "bg-sunk text-ink-2",
      )}
    >
      <span className="h-1.5 w-1.5 rounded-full bg-current" aria-hidden="true" />
      {active ? "启用" : "停用"}
    </span>
  );
}

function Check({
  checked,
  disabled,
  label,
  ariaLabel,
  onChange,
}: {
  checked: boolean;
  disabled: boolean;
  label: string;
  ariaLabel: string;
  onChange: (checked: boolean) => void;
}) {
  return (
    <label className={cn("flex items-center gap-1.5 whitespace-nowrap text-sm", disabled && "text-mute")}>
      <input
        type="checkbox"
        className="h-4 w-4 accent-ink"
        checked={checked}
        disabled={disabled}
        aria-label={ariaLabel}
        onChange={(event) => onChange(event.target.checked)}
      />
      <span>{label}</span>
    </label>
  );
}

function LimitedTable({ users, meId, busyIds, onM1 }: Pick<Props, "users" | "meId" | "busyIds" | "onM1">) {
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>账号</TableHead>
          <TableHead>显示名</TableHead>
          <TableHead>角色</TableHead>
          <TableHead>心有灵析</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {users.map((user) => {
          const canToggle = user.role === "advisor" && user.id !== meId;
          return (
            <TableRow key={user.id}>
              <TableCell className="break-words font-semibold">{user.username}</TableCell>
              <TableCell className="break-words">{user.display_name || "—"}</TableCell>
              <TableCell>{ROLE_LABEL[user.role] || user.role}</TableCell>
              <TableCell>
                <Check
                  checked={user.m1_access === 1}
                  disabled={!canToggle || busyIds.has(user.id)}
                  label="心有灵析"
                  ariaLabel={"心有灵析：" + user.username}
                  onChange={(checked) => onM1(user, checked)}
                />
              </TableCell>
            </TableRow>
          );
        })}
      </TableBody>
    </Table>
  );
}

export default function UserTable(props: Props) {
  const { users, limited, meId, busyIds, locations, onRole, onOffice, onAssessor, onScope, onDetail, onM1, onM1Admin, onToggleActive, onResetPassword, onEditAdvisor, onDelete } = props;

  if (limited) {
    return <LimitedTable users={users} meId={meId} busyIds={busyIds} onM1={onM1} />;
  }

  return (
    <Table className="min-w-[1180px]">
      <TableHeader>
        <TableRow>
          <TableHead>账号</TableHead>
          <TableHead>显示名</TableHead>
          <TableHead>角色</TableHead>
          <TableHead>办公室</TableHead>
          <TableHead>测评师</TableHead>
          <TableHead>绑定顾问</TableHead>
          <TableHead>可见学生</TableHead>
          <TableHead>可见内容</TableHead>
          <TableHead>心有灵析</TableHead>
          <TableHead>心有灵析管理</TableHead>
          <TableHead>状态</TableHead>
          <TableHead>操作</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {users.map((user) => {
          const busy = busyIds.has(user.id);
          const admin = user.role === "admin";
          const active = Boolean(user.is_active);
          const m1AdminEditable = user.role === "advisor" && user.m1_access === 1;
          return (
            <TableRow key={user.id}>
              <TableCell className="whitespace-nowrap font-semibold">{user.username}</TableCell>
              <TableCell className="break-words">{user.display_name || "—"}</TableCell>
              <TableCell>
                <select
                  className={ROW_CONTROL_CLASS}
                  value={user.role}
                  disabled={busy}
                  aria-label={"角色：" + user.username}
                  onChange={(event) => onRole(user, event.target.value as Role)}
                >
                  <option value="admin">管理员</option>
                  <option value="advisor">顾问</option>
                  <option value="viewer">只读</option>
                  <option value="front">前台</option>
                </select>
              </TableCell>
              <TableCell>
                <select
                  className={ROW_CONTROL_CLASS}
                  value={user.office_id ?? ""}
                  disabled={busy}
                  aria-label={"办公室：" + user.username}
                  onChange={(event) => onOffice(user, event.target.value)}
                >
                  <option value="">未绑定</option>
                  {locations.map((l) => (
                    <option key={l.id} value={l.id}>{l.name}</option>
                  ))}
                </select>
              </TableCell>
              <TableCell>
                <Check
                  checked={user.is_assessor === 1}
                  disabled={busy || user.role === "front" || user.role === "viewer"}
                  label="测评师"
                  ariaLabel={"测评师：" + user.username}
                  onChange={(checked) => onAssessor(user, checked)}
                />
              </TableCell>
              <TableCell className="break-words">{user.advisor_name || "—"}</TableCell>
              <TableCell>
                <select
                  className={ROW_CONTROL_CLASS}
                  value={user.student_scope || "all"}
                  disabled={busy || admin || user.role === "front"}
                  aria-label={"可见学生：" + user.username}
                  onChange={(event) => onScope(user, event.target.value)}
                >
                  <option value="all">全部学生</option>
                  <option value="own">名下学生</option>
                  {user.role === "front" ? <option value="none">无档案范围</option> : null}
                </select>
                {user.role === "front" ? <div className="mt-1 text-[11.5px] text-mute">仅当日预约交接</div> : null}
              </TableCell>
              <TableCell>
                <select
                  className={ROW_CONTROL_CLASS}
                  value={user.detail_level || "full"}
                  disabled={busy || admin}
                  aria-label={"可见内容：" + user.username}
                  onChange={(event) => onDetail(user, event.target.value)}
                >
                  <option value="full">完整</option>
                  <option value="summary">概要</option>
                </select>
              </TableCell>
              <TableCell>
                <Check
                  checked={user.m1_access === 1}
                  disabled={busy || admin || user.role === "viewer"}
                  label="心有灵析"
                  ariaLabel={"心有灵析：" + user.username}
                  onChange={(checked) => onM1(user, checked)}
                />
              </TableCell>
              <TableCell>
                <Check
                  checked={user.m1_admin === 1}
                  disabled={busy || !m1AdminEditable}
                  label="心有灵析管理"
                  ariaLabel={"心有灵析管理：" + user.username}
                  onChange={(checked) => onM1Admin(user, checked)}
                />
              </TableCell>
              <TableCell>
                <StatusBadge active={active} />
              </TableCell>
              <TableCell>
                <div className="flex flex-wrap items-center gap-1.5">
                  <Button variant="outline" size="sm" disabled={busy} onClick={() => onResetPassword(user)}>
                    重置密码
                  </Button>
                  <Button variant="outline" size="sm" disabled={busy} onClick={() => onToggleActive(user)}>
                    {active ? "停用" : "启用"}
                  </Button>
                  <Button variant="outline" size="sm" disabled={busy} onClick={() => onEditAdvisor(user)}>
                    顾问
                  </Button>
                  {user.id === meId ? null : (
                    <Button
                      variant="ghost"
                      size="sm"
                      className="text-attention hover:text-attention"
                      disabled={busy}
                      onClick={() => onDelete(user)}
                    >
                      删除
                    </Button>
                  )}
                </div>
              </TableCell>
            </TableRow>
          );
        })}
      </TableBody>
    </Table>
  );
}
