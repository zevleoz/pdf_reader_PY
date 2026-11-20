export type Role = "admin" | "advisor" | "viewer";

export type UserRow = {
  id: number;
  username: string;
  display_name: string;
  role: Role | string;
  advisor_name?: string;
  student_scope?: string;
  detail_level?: string;
  m1_access?: number;
  m1_admin?: number;
  is_active?: number;
};

export type ListResponse = { ok: boolean; users: UserRow[]; limited?: boolean; error?: string };

export type CheckResponse = {
  ok: boolean;
  authenticated: boolean;
  user_id: number | null;
  role: string | null;
  display_name: string;
  advisor_name: string;
};

export type Me = {
  user_id: number;
  role: string;
  display_name: string;
  advisor_name: string;
};

export type CreatePayload = {
  username: string;
  password: string;
  role: Role;
  advisor_name: string;
  display_name: string;
  student_scope: string;
  detail_level: string;
  m1_access: number;
};

export const ROLE_LABEL: Record<string, string> = { admin: "管理员", advisor: "顾问", viewer: "只读" };

export const ROLE_DEFAULTS: Record<Role, { student_scope: string; detail_level: string; m1_access: boolean }> = {
  admin: { student_scope: "all", detail_level: "full", m1_access: true },
  advisor: { student_scope: "own", detail_level: "full", m1_access: true },
  viewer: { student_scope: "all", detail_level: "summary", m1_access: false },
};

export const PERM_OK = "权限已更新，最多 1 分钟内生效";

export const CONTROL_CLASS =
  "h-9 w-full border border-input bg-background px-2 text-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:opacity-50";

export const ROW_CONTROL_CLASS =
  "h-8 border border-input bg-background px-2 text-[12.5px] focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:opacity-50";
