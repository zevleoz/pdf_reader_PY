export type Stage = {
  key: string;
  label: string;
  required: boolean;
  state: "done" | "todo" | "not_used";
  at: string | null;
};

export type Progress = {
  stages: Stage[];
  next: { key: string; label: string } | null;
  done: boolean;
  label: string;
};

/** 阶段状态文字（"已完成 2026-10-01" / "未完成" / "可选，未使用" / "可选，未完成"）。 */
export function stageState(stage: Stage): string {
  if (stage.state === "done") {
    return "已完成" + (stage.at ? " " + stage.at.slice(0, 10) : "");
  }
  if (stage.state === "not_used") return "可选，未使用";
  return stage.required ? "未完成" : "可选，未完成";
}

export function stageTitle(stage: Stage): string {
  return stage.label + "：" + stageState(stage);
}

/** 档案页六步条下面那一行小字（不带天数）。current = 当前下一步所在阶段。 */
export function trackLine(stage: Stage, current: boolean): string {
  if (stage.state === "done") {
    return "已完成" + (stage.at ? " " + stage.at.slice(0, 10) : "");
  }
  if (current) return "进行中";
  if (!stage.required && stage.state === "todo") return "进行中";
  if (stage.state === "not_used") return "可选，未开始";
  return "未开始";
}
