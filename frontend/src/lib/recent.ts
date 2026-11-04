/** 最近查看的学生档案（只存在本浏览器里；存储不可用时页面照常工作）。 */
export type RecentStudent = { code: string; name: string };

const KEY = "ark.recent.v1";
const MAX = 6;

export function readRecent(): RecentStudent[] {
  try {
    const raw = window.localStorage.getItem(KEY);
    if (!raw) return [];
    const list = JSON.parse(raw);
    if (!Array.isArray(list)) return [];
    return list
      .filter((x) => x && typeof x.code === "string" && x.code && typeof x.name === "string")
      .slice(0, MAX)
      .map((x) => ({ code: x.code as string, name: x.name as string }));
  } catch {
    return [];
  }
}

export function recordRecent(code: string, name: string): void {
  if (!code) return;
  try {
    const next = [{ code, name }, ...readRecent().filter((x) => x.code !== code)].slice(0, MAX);
    window.localStorage.setItem(KEY, JSON.stringify(next));
  } catch {
    // 存储不可用：忽略
  }
}
