import * as React from "react";

export default function PageHeader({ title, sub, actions }: { title: string; sub?: string; actions?: React.ReactNode }) {
  React.useEffect(() => {
    document.title = title + " · 凭远 APP·ARK";
  }, [title]);

  return (
    <div className="grid grid-cols-[minmax(0,1fr)_auto] items-end gap-6 mb-[18px]">
      <div>
        <h1 className="text-title-sm md:text-title">{title}</h1>
        {sub ? <p className="mt-[7px] text-mute">{sub}</p> : null}
      </div>
      {actions ? <div>{actions}</div> : null}
    </div>
  );
}
