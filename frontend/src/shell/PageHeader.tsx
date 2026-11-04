import * as React from "react";

import { useCrumb } from "@/shell/crumbs";

export default function PageHeader({ title, sub, actions }: { title: string; sub?: string; actions?: React.ReactNode }) {
  const { setTitle } = useCrumb();

  React.useEffect(() => {
    document.title = title + " · 凭远 APP·ARK";
  }, [title]);

  React.useEffect(() => {
    setTitle(title);
    return () => setTitle("");
  }, [title, setTitle]);

  return (
    <div className="grid grid-cols-1 gap-3 mb-[18px] md:grid-cols-[minmax(0,1fr)_auto] md:items-end md:gap-6">
      <div>
        <h1 className="text-title-sm md:text-title">{title}</h1>
        {sub ? <p className="mt-[7px] text-mute">{sub}</p> : null}
      </div>
      {actions ? <div>{actions}</div> : null}
    </div>
  );
}
