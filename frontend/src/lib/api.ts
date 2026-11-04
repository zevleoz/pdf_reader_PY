/** 读 JSON；未登录跳到登录页，其他失败抛错由页面显示。 */
export async function getJSON<T>(url: string): Promise<T> {
  const resp = await fetch(url, { credentials: "same-origin" });
  if (resp.status === 401) {
    window.location.href = "/login";
    throw new Error("unauthenticated");
  }
  if (!resp.ok) {
    throw new Error("HTTP " + resp.status);
  }
  return (await resp.json()) as T;
}
