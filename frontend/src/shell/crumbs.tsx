import * as React from "react";

type Crumb = { title: string; setTitle: (title: string) => void };

const CrumbContext = React.createContext<Crumb>({ title: "", setTitle: () => {} });

/** 页面标题由 PageHeader 写入，顶栏的面包屑从这里读。 */
export function CrumbProvider({ children }: { children: React.ReactNode }) {
  const [title, setTitle] = React.useState("");
  const value = React.useMemo(() => ({ title, setTitle }), [title]);
  return <CrumbContext.Provider value={value}>{children}</CrumbContext.Provider>;
}

export function useCrumb(): Crumb {
  return React.useContext(CrumbContext);
}

/** 上级页面的名称，按路径第一段。 */
export const PARENT_LABELS: Record<string, string> = { students: "学生档案" };
