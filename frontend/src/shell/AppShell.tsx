import * as React from "react";
import { Menu } from "lucide-react";
import { Link, Outlet, useLocation } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet";
import { CrumbProvider, PARENT_LABELS, useCrumb } from "@/shell/crumbs";
import { PaletteProvider, SearchButton } from "@/shell/palette";
import Rail from "@/shell/Rail";

function TopBar() {
  const { title } = useCrumb();
  const parts = useLocation().pathname.split("/").filter(Boolean);
  const parent = parts.length > 1 ? PARENT_LABELS[parts[0]] : undefined;

  return (
    <div className="hidden h-12 shrink-0 items-center gap-2.5 px-7 text-[13px] text-mute md:flex">
      {parent && title ? (
        <div className="flex items-center gap-1.5">
          <Link to={"/" + parts[0]} className="hover:text-ink hover:underline">
            {parent}
          </Link>
          <span>/</span>
          <b className="font-semibold text-ink">{title}</b>
        </div>
      ) : null}
      <SearchButton />
    </div>
  );
}

export default function AppShell() {
  const [open, setOpen] = React.useState(false);

  return (
    <CrumbProvider>
      <PaletteProvider>
        <div className="md:grid md:h-screen md:grid-cols-[216px_minmax(0,1fr)]">
          <div className="hidden overflow-y-auto md:block">
            <Rail />
          </div>
          <div className="md:flex md:h-screen md:flex-col">
            <div className="flex h-14 items-center bg-shell px-4 text-shell-foreground md:hidden">
              <div className="font-bold">学生 Profiling</div>
              <SearchButton compact />
              <Button
                variant="ghost"
                size="icon"
                aria-label="打开导航"
                className="text-shell-foreground hover:bg-white/15"
                onClick={() => setOpen(true)}
              >
                <Menu />
              </Button>
            </div>
            <TopBar />
            <main className="px-4 py-6 md:flex-1 md:overflow-y-auto md:px-10 md:pb-8 md:pt-2">
              <Outlet />
            </main>
          </div>
          <Sheet open={open} onOpenChange={setOpen}>
            <SheetContent
              side="left"
              aria-describedby={undefined}
              className="w-[216px] border-0 bg-shell p-0 text-shell-foreground md:hidden"
              onClickCapture={(event) => {
                if ((event.target as HTMLElement).closest("a")) {
                  setOpen(false);
                }
              }}
            >
              <SheetTitle className="sr-only">导航</SheetTitle>
              <Rail />
            </SheetContent>
          </Sheet>
        </div>
      </PaletteProvider>
    </CrumbProvider>
  );
}
