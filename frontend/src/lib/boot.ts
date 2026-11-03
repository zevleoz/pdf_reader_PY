import { createContext, createElement, useContext, useEffect, useState, type ReactNode } from "react";

export type NavLink = { key: string; label: string; href: string; icon?: string; blank?: boolean };
export type NavGroup = { key: string; title: string; links: NavLink[] };
export type Platform = { key: string; title: string; desc: string; href: string; blank: boolean };
export type Boot = {
  user: { display_name: string; role: string; role_label: string };
  policy: { role: string; student_scope: string; detail_level: string; m1_access: number | boolean };
  nav: NavGroup[];
  platforms: Platform[];
};

export function csrfToken(): string {
  const meta = document.querySelector<HTMLMetaElement>('meta[name="csrf-token"]');
  return meta ? meta.content : "";
}

export async function logout(): Promise<void> {
  try {
    await fetch("/api/admin/logout", {
      method: "POST",
      headers: { "X-CSRF-Token": csrfToken() },
      credentials: "same-origin",
    });
  } catch {
    // 请求失败也照样离开页面
  }
  window.location.href = "/login";
}

const BootContext = createContext<Boot | null>(null);

export function useBoot(): Boot {
  const boot = useContext(BootContext);
  if (!boot) {
    throw new Error("useBoot 必须在 BootProvider 内使用");
  }
  return boot;
}

type BootState =
  | { status: "loading" }
  | { status: "error" }
  | { status: "ready"; boot: Boot };

export function BootProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<BootState>({ status: "loading" });

  useEffect(() => {
    let cancelled = false;

    fetch("/api/app/boot", { credentials: "same-origin" })
      .then((resp) => {
        if (resp.status === 401) {
          window.location.href = "/login";
          return null;
        }
        if (!resp.ok) {
          throw new Error("boot failed");
        }
        return resp.json() as Promise<Boot>;
      })
      .then((boot) => {
        if (!cancelled && boot) {
          setState({ status: "ready", boot });
        }
      })
      .catch(() => {
        if (!cancelled) {
          setState({ status: "error" });
        }
      });

    return () => {
      cancelled = true;
    };
  }, []);

  if (state.status === "loading") {
    return createElement("p", { className: "p-8 text-mute" }, "正在载入…");
  }

  if (state.status === "error") {
    return createElement(
      "div",
      null,
      createElement("p", { className: "p-8" }, "无法载入账号信息。"),
      createElement("a", { className: "underline", href: "/login" }, "重新登录"),
    );
  }

  return createElement(BootContext.Provider, { value: state.boot }, children);
}
