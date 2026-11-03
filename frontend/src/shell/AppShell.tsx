import * as React from "react";
import { Menu } from "lucide-react";
import { Outlet } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet";
import Rail from "@/shell/Rail";

export default function AppShell() {
  const [open, setOpen] = React.useState(false);

  return (
    <div className="md:grid md:h-screen md:grid-cols-[216px_minmax(0,1fr)]">
      <div className="hidden overflow-y-auto md:block">
        <Rail />
      </div>
      <div className="md:overflow-y-auto">
        <div className="flex h-14 items-center bg-shell px-4 text-shell-foreground md:hidden">
          <div className="font-bold">学生 Profiling</div>
          <Button
            variant="ghost"
            size="icon"
            aria-label="打开导航"
            className="ml-auto text-shell-foreground hover:bg-white/15"
            onClick={() => setOpen(true)}
          >
            <Menu />
          </Button>
        </div>
        <main className="px-4 py-6 md:px-10 md:py-8">
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
  );
}
