import { useNavigate } from "react-router-dom";

import type { NavLink } from "@/lib/boot";

/** 跟侧栏一致地打开一个链接：应用内走路由，其他整页跳转，blank 开新标签。 */
export function useGoLink(): (link: NavLink) => void {
  const navigate = useNavigate();
  return (link) => {
    if (link.href.startsWith("/app/")) {
      navigate(link.href.slice("/app".length));
    } else if (link.blank) {
      window.open(link.href, "_blank", "noopener");
    } else {
      window.location.href = link.href;
    }
  };
}
