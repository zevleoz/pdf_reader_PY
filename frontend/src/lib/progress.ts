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
