import * as React from "react";
import * as DialogPrimitive from "@radix-ui/react-dialog";
import { Search } from "lucide-react";
import { useNavigate } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { Dialog, DialogOverlay, DialogPortal } from "@/components/ui/dialog";
import { getJSON } from "@/lib/api";
import { useBoot } from "@/lib/boot";
import { cn } from "@/lib/utils";
import { buildJumps, buildRail, type Jump } from "@/shell/railModel";
import { useGoLink } from "@/shell/useGoLink";

type PaletteCtx = { open: boolean; setOpen: (open: boolean) => void };
const PaletteContext = React.createContext<PaletteCtx>({ open: false, setOpen: () => {} });

export function usePalette(): PaletteCtx {
  return React.useContext(PaletteContext);
}

const isMac = typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform);

export function PaletteProvider({ children }: { children: React.ReactNode }) {
  const [open, setOpen] = React.useState(false);

  React.useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setOpen((v) => !v);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const value = React.useMemo(() => ({ open, setOpen }), [open]);
  return (
    <PaletteContext.Provider value={value}>
      {children}
      <CommandPalette />
    </PaletteContext.Provider>
  );
}

/** 顶栏（桌面）和红色顶条（手机）上的搜索按钮。 */
export function SearchButton({ compact = false }: { compact?: boolean }) {
  const { setOpen } = usePalette();
  if (compact) {
    return (
      <Button
        variant="ghost"
        size="icon"
        data-palette-trigger=""
        aria-label="搜索学生或跳转"
        className="ml-auto text-shell-foreground hover:bg-white/15"
        onClick={() => setOpen(true)}
      >
        <Search size={16} />
      </Button>
    );
  }
  return (
    <button
      type="button"
      data-palette-trigger=""
      onClick={() => setOpen(true)}
      className="ml-auto flex h-8 min-w-[240px] items-center gap-2 bg-sunk px-2.5 text-[13px] text-mute transition-colors hover:bg-sunk/80"
    >
      <Search size={16} className="shrink-0" aria-hidden />
      <span>搜索学生或跳转</span>
      <kbd className="ml-auto font-sans text-[11.5px] font-semibold leading-none">{isMac ? "⌘K" : "Ctrl K"}</kbd>
    </button>
  );
}

type StudentRow = { code: string; name: string; school: string };
type Result =
  | { kind: "student"; id: string; row: StudentRow }
  | { kind: "jump"; id: string; jump: Jump };

function CommandPalette() {
  const { open, setOpen } = usePalette();

  const returnFocus = (event: Event) => {
    event.preventDefault();
    const buttons = Array.from(document.querySelectorAll<HTMLElement>("[data-palette-trigger]"));
    const visible = buttons.find((b) => b.offsetParent !== null);
    (visible ?? buttons[0])?.focus();
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogPortal>
        <DialogOverlay className="bg-black/40" />
        <DialogPrimitive.Content
          aria-describedby={undefined}
          onCloseAutoFocus={returnFocus}
          className="fixed left-1/2 top-[9vh] z-50 w-[min(600px,calc(100%-24px))] -translate-x-1/2 overflow-hidden bg-background shadow-[0_26px_60px_-22px_rgba(0,0,0,0.6)]"
        >
          <DialogPrimitive.Title className="sr-only">搜索</DialogPrimitive.Title>
          <PaletteBody close={() => setOpen(false)} />
        </DialogPrimitive.Content>
      </DialogPortal>
    </Dialog>
  );
}

function PaletteBody({ close }: { close: () => void }) {
  const boot = useBoot();
  const navigate = useNavigate();
  const go = useGoLink();
  const jumps = React.useMemo(() => buildJumps(buildRail(boot)), [boot]);
  const mainJumps = React.useMemo(() => {
    const keys = new Set(buildRail(boot).main.map((m) => m.key));
    return jumps.filter((j) => keys.has(j.key));
  }, [boot, jumps]);

  const [text, setText] = React.useState("");
  const [students, setStudents] = React.useState<StudentRow[]>([]);
  const [settledQ, setSettledQ] = React.useState("");
  const [index, setIndex] = React.useState(0);
  const listRef = React.useRef<HTMLUListElement>(null);

  const q = text.trim();

  React.useEffect(() => {
    if (!q) {
      setStudents([]);
      setSettledQ("");
      return;
    }
    let cancelled = false;
    const timer = window.setTimeout(() => {
      const query = new URLSearchParams({ q, per_page: "8", sort: "name" });
      getJSON<{ rows: StudentRow[] }>("/api/profiling/students?" + query.toString())
        .then((body) => {
          if (!cancelled) {
            setStudents(body.rows ?? []);
            setSettledQ(q);
          }
        })
        .catch(() => {
          if (!cancelled) {
            setStudents([]);
            setSettledQ(q);
          }
        });
    }, 200);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [q]);

  const results: Result[] = React.useMemo(() => {
    if (!q) return mainJumps.map((jump) => ({ kind: "jump", id: "j:" + jump.key, jump }));
    const lower = q.toLowerCase();
    const matched = jumps.filter(
      (j) => j.label.toLowerCase().includes(lower) || (j.group ?? "").toLowerCase().includes(lower),
    );
    return [
      ...students.map((row): Result => ({ kind: "student", id: "s:" + row.code, row })),
      ...matched.map((jump): Result => ({ kind: "jump", id: "j:" + jump.key, jump })),
    ];
  }, [q, students, jumps, mainJumps]);

  const searching = q !== "" && settledQ !== q;
  const selected = Math.min(index, Math.max(0, results.length - 1));

  React.useEffect(() => {
    const el = listRef.current?.querySelector<HTMLElement>('[aria-selected="true"]');
    el?.scrollIntoView?.({ block: "nearest" });
  }, [selected, results]);

  const run = (result: Result | undefined) => {
    if (!result) return;
    close();
    if (result.kind === "student") navigate("/students/" + encodeURIComponent(result.row.code));
    else go(result.jump.link);
  };

  const onKeyDown = (event: React.KeyboardEvent) => {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setIndex(Math.min(selected + 1, results.length - 1));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setIndex(Math.max(selected - 1, 0));
    } else if (event.key === "Enter" && !event.nativeEvent.isComposing) {
      event.preventDefault();
      run(results[selected]);
    }
  };

  return (
    <div onKeyDown={onKeyDown}>
      <input
        autoFocus
        autoComplete="off"
        spellCheck={false}
        placeholder="搜索学生或跳转"
        aria-label="搜索学生或跳转"
        value={text}
        onChange={(e) => {
          setText(e.target.value);
          setIndex(0);
        }}
        className="h-[52px] w-full border-0 border-b-2 border-rule bg-transparent px-4 text-base outline-none"
      />
      <ul ref={listRef} role="listbox" className="m-0 max-h-[48vh] list-none overflow-auto p-1.5">
        {results.map((result, i) => (
          <li
            key={result.id}
            role="option"
            aria-selected={i === selected}
            onMouseMove={() => setIndex(i)}
            onClick={() => run(result)}
            className={cn(
              "flex cursor-pointer items-center gap-2.5 px-2.5 py-2 text-left",
              i === selected && "bg-foreground text-background",
            )}
          >
            {result.kind === "student" ? (
              <>
                <span>{result.row.name}</span>
                <small className="ml-auto text-[12.5px] opacity-70">
                  {result.row.school ? result.row.code + " · " + result.row.school : result.row.code}
                </small>
              </>
            ) : (
              <>
                <span>{result.jump.label}</span>
                <small className="ml-auto text-[12.5px] opacity-70">跳转</small>
              </>
            )}
          </li>
        ))}
        {results.length === 0 && !searching ? <li className="px-2.5 py-3.5 text-mute">没有匹配，试试拼音首字母</li> : null}
      </ul>
      <div className="flex gap-3.5 border-t border-line px-3.5 py-[7px] text-xs text-mute">
        <span>↑↓ 移动</span>
        <span>Enter 打开</span>
        <span>Esc 关闭</span>
      </div>
    </div>
  );
}
