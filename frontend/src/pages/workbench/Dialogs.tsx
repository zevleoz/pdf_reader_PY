import * as React from "react";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { cn } from "@/lib/utils";

import type { Notify } from "./model";

/** 与旧版工作台、问卷 tab 相同的三种分发方式（原文）。 */
export const DELIVERIES: { key: string; label: string; desc: string }[] = [
  { key: "account", label: "问卷中心账号（推荐）", desc: "学生登录后看到自己所有待完成的问卷" },
  { key: "link", label: "在线链接", desc: "生成一次性作答链接（7 天有效）" },
  { key: "both", label: "两者都发", desc: "链接与账号同时生成" },
];

export function ConfirmDialog({
  title,
  busy,
  onCancel,
  onConfirm,
}: {
  title: string;
  busy: boolean;
  onCancel: () => void;
  onConfirm: (delivery: string) => void;
}) {
  const [delivery, setDelivery] = React.useState("account");
  return (
    <Dialog open onOpenChange={(open) => (open ? null : onCancel())}>
      <DialogContent className="sm:rounded-none shadow-none">
        <DialogHeader>
          <DialogTitle>确认分发</DialogTitle>
        </DialogHeader>
        <div className="text-sm">
          <b>{title}</b>
        </div>
        <div className="grid gap-2" role="radiogroup" aria-label="分发方式">
          {DELIVERIES.map((d) => (
            <button
              key={d.key}
              type="button"
              role="radio"
              aria-checked={delivery === d.key}
              onClick={() => setDelivery(d.key)}
              className={cn(
                "border px-3 py-2 text-left text-sm",
                delivery === d.key ? "border-rule bg-sunk" : "border-line hover:bg-sunk",
              )}
            >
              <b className="block">{d.label}</b>
              <span className="text-xs text-mute">{d.desc}</span>
            </button>
          ))}
        </div>
        <DialogFooter className="gap-2 sm:gap-0">
          <Button variant="outline" onClick={onCancel}>
            取消
          </Button>
          <Button disabled={busy} onClick={() => onConfirm(delivery)}>
            确认并分发
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export type Pkg = { title: string; text: string; note: string };

export function PackageDialog({ pkg, onClose, notify }: { pkg: Pkg; onClose: () => void; notify: Notify }) {
  function copy() {
    if (!pkg.text) return;
    if (navigator.clipboard) {
      navigator.clipboard.writeText(pkg.text).then(
        () => notify("已复制", "ok"),
        () => notify("复制失败，请手动选择", "error"),
      );
    } else {
      notify("请手动选择文本复制");
    }
  }
  return (
    <Dialog open onOpenChange={(open) => (open ? null : onClose())}>
      <DialogContent className="sm:rounded-none shadow-none">
        <DialogHeader>
          <DialogTitle>{pkg.title}</DialogTitle>
        </DialogHeader>
        {pkg.note ? <p className="text-sm text-mute">{pkg.note}</p> : null}
        <pre className="max-h-[50vh] overflow-auto whitespace-pre-wrap break-words border border-line bg-sunk p-3 font-mono text-xs">
          {pkg.text}
        </pre>
        <DialogFooter className="gap-2 sm:gap-0">
          <Button variant="outline" onClick={copy}>
            复制
          </Button>
          <Button onClick={onClose}>关闭</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
