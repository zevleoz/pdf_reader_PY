import { csrfToken } from "@/lib/boot";

/** 请求失败：message 形如 "HTTP 404"，status 为状态码，serverMessage 为服务端给出的 error 文本（如有）。 */
export class ApiError extends Error {
  status: number;
  serverMessage: string;
  constructor(status: number, serverMessage = "") {
    super("HTTP " + status);
    this.status = status;
    this.serverMessage = serverMessage;
  }
}

async function readError(resp: Response): Promise<ApiError> {
  let msg = "";
  try {
    const body = await resp.clone().json();
    if (body && typeof body.error === "string") msg = body.error;
  } catch {
    // 不是 JSON：只保留状态码
  }
  return new ApiError(resp.status, msg);
}

async function request<T>(url: string, init: RequestInit): Promise<T> {
  const resp = await fetch(url, { credentials: "same-origin", ...init });
  if (resp.status === 401) {
    window.location.href = "/login";
    throw new Error("unauthenticated");
  }
  if (!resp.ok) {
    throw await readError(resp);
  }
  return (await resp.json()) as T;
}

/** 读 JSON；未登录跳到登录页，其他失败抛错由页面显示。 */
export function getJSON<T>(url: string): Promise<T> {
  return request<T>(url, {});
}

function send<T>(method: string, url: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = { "X-CSRF-Token": csrfToken() };
  let payload: string | undefined;
  if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }
  return request<T>(url, { method, headers, body: payload });
}

export function postJSON<T>(url: string, body?: unknown): Promise<T> {
  return send<T>("POST", url, body);
}

export function putJSON<T>(url: string, body?: unknown): Promise<T> {
  return send<T>("PUT", url, body);
}

export function deleteJSON<T>(url: string): Promise<T> {
  return send<T>("DELETE", url);
}

/** 取出可显示的错误文本：服务端的 error 优先，否则 HTTP 状态。 */
export function errorText(err: unknown, fallback = "操作失败"): string {
  if (err instanceof ApiError) return err.serverMessage || err.message;
  if (err instanceof Error) return err.message;
  return fallback;
}
