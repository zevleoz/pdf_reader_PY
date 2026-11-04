import * as React from "react";
import { NavLink, useLocation } from "react-router-dom";
import { LogOut, type LucideIcon } from "lucide-react";

import { Button } from "@/components/ui/button";
import { logout, useBoot } from "@/lib/boot";
import { cn } from "@/lib/utils";
import type { NavLink as NavLinkType } from "@/lib/boot";
import { buildRail } from "@/shell/railModel";

const rowBase = "flex w-full items-center gap-2.5 px-2.5 text-left transition-colors";
const rowIdle = "hover:bg-white/15";
const rowActive = "bg-on text-on-foreground font-bold";
const sizes = {
  main: "h-10 text-[14.5px] font-medium",
  old: "h-8 text-[13px] font-normal opacity-90",
  sub: "h-[30px] pl-9 text-[13px] font-normal",
} as const;

function rowClass(size: keyof typeof sizes, active: boolean): string {
  return cn(rowBase, sizes[size], active ? rowActive : rowIdle);
}

function RailLink({
  link,
  label,
  icon: Icon,
  size,
  active,
}: {
  link: NavLinkType;
  label: string;
  icon?: LucideIcon;
  size: keyof typeof sizes;
  active: boolean;
}) {
  const className = rowClass(size, active);
  const content = (
    <>
      {Icon ? <Icon size={16} className="shrink-0" aria-hidden /> : null}
      <span>{label}</span>
    </>
  );

  if (link.href.startsWith("/app/")) {
    return (
      <NavLink to={link.href.slice("/app".length)} className={className}>
        {content}
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
      {content}
    </a>
  );
}

export default function Rail() {
  const boot = useBoot();
  const location = useLocation();
  const here = "/app" + location.pathname;
  const multiPlatform = boot.platforms.length > 1;
  const model = React.useMemo(() => buildRail(boot), [boot]);
  const [openKey, setOpenKey] = React.useState<string | null>(null);

  const isActive = (link: NavLinkType) =>
    link.href.startsWith("/app/") && (here === link.href || here.startsWith(link.href + "/"));

  const brand = (
    <div className="flex items-center gap-2.5 px-1.5 pb-[22px] text-left">
      <img src="/m1/assets/login_crest_white.png" alt="" width={36} height={36} className="h-9 w-9 shrink-0" />
      <span>
        <span className="block text-[14.5px] font-bold leading-tight">学生 Profiling</span>
        <span className="block text-xs leading-snug">{multiPlatform ? "切换平台" : "凭远 APP·ARK"}</span>
      </span>
    </div>
  );

  return (
    <div className="flex h-full flex-col bg-shell text-shell-foreground px-3 py-[18px]">
      {multiPlatform ? (
        <a href="/platforms" className="transition-opacity hover:opacity-80" aria-label="切换平台">
          {brand}
        </a>
      ) : (
        brand
      )}

      <nav>
        {model.main.map((item) => (
          <RailLink
            key={item.key}
            link={item.link}
            label={item.label}
            icon={item.icon}
            size="main"
            active={isActive(item.link)}
          />
        ))}

        {model.old.length ? <div className="mx-1.5 my-3 h-px bg-white/30" /> : null}

        {model.old.map((section) => {
          if (section.links.length === 1) {
            const link = section.links[0];
            return (
              <RailLink
                key={section.key}
                link={link}
                label={section.label}
                icon={section.icon}
                size="old"
                active={isActive(link)}
              />
            );
          }
          const Icon = section.icon;
          const open = openKey === section.key;
          const hasActive = section.links.some(isActive);
          return (
            <div key={section.key}>
              <button
                type="button"
                aria-expanded={open}
                className={rowClass("old", hasActive && !open)}
                onClick={() => setOpenKey(open ? null : section.key)}
              >
                <Icon size={16} className="shrink-0" aria-hidden />
                <span>{section.label}</span>
              </button>
              {open
                ? section.links.map((link) => (
                    <RailLink key={link.key} link={link} label={link.label} size="sub" active={isActive(link)} />
                  ))
                : null}
            </div>
          );
        })}

        {model.other.length ? (
          <>
            <div className="mx-2.5 mt-3.5 mb-1 text-xs font-semibold">其他平台</div>
            {model.other.map((item) => (
              <RailLink
                key={item.key}
                link={item.link}
                label={item.label}
                icon={item.icon}
                size="old"
                active={isActive(item.link)}
              />
            ))}
          </>
        ) : null}
      </nav>

      <div className="mt-auto">
        <div className="flex items-center gap-2 px-1.5 pt-2.5 text-[12.5px] leading-tight">
          <div className="flex h-7 w-7 items-center justify-center bg-shell-foreground text-shell font-bold">
            {boot.user.display_name.slice(0, 1)}
          </div>
          <div>
            <div className="font-bold">{boot.user.display_name}</div>
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
