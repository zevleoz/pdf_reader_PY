import * as React from "react";
import { Link } from "react-router-dom";

import type { NavLink } from "@/lib/boot";
import { useGoLink } from "@/shell/useGoLink";

import { pad2, weekday, type Upcoming } from "./model";

export function SideTitle({ children, right }: { children: React.ReactNode; right?: React.ReactNode }) {
  return (
    <h2 className="mb-2.5 flex items-center gap-2 border-t-2 border-rule pt-[9px] text-sm font-bold">
      {children}
      {right ? <span className="ml-auto flex gap-1.5">{right}</span> : null}
    </h2>
  );
}

const miniClass = "flex w-full items-center gap-2.5 border-b border-line py-2 text-left hover:[&_b]:underline";

/* ------------------------------------------------------------ 接下来的预约 */
export function UpcomingList({ rows, bookingsLink }: { rows: Upcoming[]; bookingsLink: NavLink | null }) {
  const go = useGoLink();
  return (
    <section aria-label="接下来的预约">
      <SideTitle
        right={
          bookingsLink ? (
            <button type="button" className="text-[12.5px] font-semibold text-hl hover:underline" onClick={() => go(bookingsLink)}>
              打开日历
            </button>
          ) : null
        }
      >
        接下来的预约
      </SideTitle>
      {rows.length === 0 ? (
        <p className="py-3 text-sm text-mute">暂无待完成的预约</p>
      ) : (
        rows.map((u) => {
          const when = new Date(u.appointment_time);
          const valid = !isNaN(when.getTime());
          const body = (
            <>
              <span className="min-w-0">
                <b className="font-semibold">{u.student_name}</b>
                <small className="block text-[12.5px] leading-[1.3] text-mute">{"顾问 " + u.advisor_name}</small>
              </span>
              <span className="ml-auto whitespace-nowrap text-right text-[13px] font-semibold">
                {valid ? when.getMonth() + 1 + "/" + when.getDate() + " " + weekday(when) : ""}
                <br />
                {valid ? pad2(when.getHours()) + ":" + pad2(when.getMinutes()) : ""}
              </span>
            </>
          );
          return u.student_code ? (
            <Link
              key={u.booking_id}
              to={"/students/" + encodeURIComponent(u.student_code) + "?tab=schedule"}
              className={miniClass}
            >
              {body}
            </Link>
          ) : bookingsLink ? (
            <button key={u.booking_id} type="button" className={miniClass} onClick={() => go(bookingsLink)}>
              {body}
            </button>
          ) : (
            <div key={u.booking_id} className="flex w-full items-center gap-2.5 border-b border-line py-2 text-left">
              {body}
            </div>
          );
        })
      )}
    </section>
  );
}
