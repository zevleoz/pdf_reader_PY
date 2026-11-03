import { NavLink, useLocation } from "react-router-dom";
import { LogOut } from "lucide-react";

import { Button } from "@/components/ui/button";
import { logout, useBoot } from "@/lib/boot";
import { cn } from "@/lib/utils";
import type { NavLink as NavLinkType } from "@/lib/boot";

const rowBase = "flex h-10 w-full items-center gap-2.5 px-2.5 text-[14.5px] font-medium transition-colors";
const rowIdle = cn(rowBase, "hover:bg-white/15");
const rowActive = cn(rowBase, "bg-on text-on-foreground font-bold");

function linkTo(href: string): string {
  return href.slice("/app".length);
}

function RailLink({ link, active }: { link: NavLinkType; active: boolean }) {
  const className = active ? rowActive : rowIdle;

  if (link.href.startsWith("/app/")) {
    return (
      <NavLink to={linkTo(link.href)} className={className}>
        {link.label}
      </NavLink>
    );
  }

  return (
    <a
      href={link.href}
      className={className}
      target={link.blank ? "_blank" : undefined}
      rel={link.blank ? "noopener" : undefined}
    >
      {link.label}
    </a>
  );
}

export default function Rail() {
  const boot = useBoot();
  const location = useLocation();
  const here = "/app" + location.pathname;
  const multiPlatform = boot.platforms.length > 1;

  const brand = (
    <div className="px-1.5 pb-[22px]">
      <div className="text-[14.5px] font-bold leading-tight">学生 Profiling</div>
      <div className="text-xs">凭远 APP·ARK</div>
    </div>
  );

  return (
    <div className="flex h-full flex-col bg-shell text-shell-foreground px-3 py-[18px]">
      {multiPlatform ? (
        <a href="/platforms" className="hover:opacity-80">
          {brand}
        </a>
      ) : (
        brand
      )}

      <nav>
        {boot.nav.map((group) => {
          const showTitle =
            group.links.length > 1 ||
            (group.links.length === 1 && group.links[0].label !== group.title);
          return (
            <div key={group.key}>
              {showTitle ? (
                <div className="mx-2.5 mt-3.5 mb-1 text-xs font-semibold">{group.title}</div>
              ) : null}
              {group.links.map((link) => {
                const inApp = link.href.startsWith("/app/");
                const active =
                  inApp && (here === link.href || here.startsWith(link.href + "/"));
                return <RailLink key={link.key} link={link} active={active} />;
              })}
            </div>
          );
        })}
      </nav>

      <div className="mt-auto">
        <div className="mx-1.5 my-3 h-px bg-white/30" />
        {multiPlatform ? (
          <a href="/platforms" className={rowIdle}>
            选择平台
          </a>
        ) : null}
        <div className="flex items-center gap-2 px-1.5 pt-2.5 text-[12.5px] leading-tight">
          <div className="flex h-7 w-7 items-center justify-center bg-shell-foreground text-shell font-bold">
            {boot.user.display_name.slice(0, 1)}
          </div>
          <div>
            <div>{boot.user.display_name}</div>
            <div>{boot.user.role_label}</div>
          </div>
          <Button
            variant="ghost"
            size="icon"
            aria-label="退出登录"
            title="退出登录"
            className="ml-auto text-shell-foreground hover:bg-white/15"
            onClick={() => logout()}
          >
            <LogOut size={16} />
          </Button>
        </div>
      </div>
    </div>
  );
}
