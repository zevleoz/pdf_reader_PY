import { useSearchParams } from "react-router-dom";

export function useTab(values: string[], fallback: string, name = "tab"): [string, (v: string) => void] {
  const [params, setParams] = useSearchParams();
  const current = params.get(name);
  const value = current && values.includes(current) ? current : fallback;
  const set = (v: string) => {
    const next = new URLSearchParams(params);
    next.set(name, v);
    setParams(next, { replace: true });
  };
  return [value, set];
}
