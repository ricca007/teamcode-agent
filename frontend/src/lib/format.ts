/** 小型展示格式化工具，避免在组件里散落重复逻辑。 */

import type { AgentStatus, InterfaceInfo, TaskStatus } from "../types";

export const STATUS_LABEL: Record<TaskStatus | AgentStatus, string> = {
  // A 的任务状态
  planned: "待处理",
  in_progress: "进行中",
  blocked: "阻塞",
  completed: "已完成",
  cancelled: "已取消",
  // B 的 Agent 会话状态
  pending: "待启动",
  running: "运行中",
  paused: "已暂停",
  succeeded: "已完成",
  failed: "失败",
  terminated: "已终止",
};

export const KIND_LABEL: Record<InterfaceInfo["kind"], string> = {
  function: "函数",
  method: "方法",
  class: "类",
};

const clockFormatter = new Intl.DateTimeFormat("zh-CN", {
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hour12: false,
});

const dateTimeFormatter = new Intl.DateTimeFormat("zh-CN", {
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});

export function formatClock(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "--:--:--";
  }
  return clockFormatter.format(date);
}

export function formatDateTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "时间未知";
  }
  return dateTimeFormatter.format(date);
}

export function shortHash(hash: string | null): string {
  if (!hash) {
    return "工作区未提交";
  }
  return hash.slice(0, 7);
}

export function signatureOf(info: InterfaceInfo): string {
  const params = info.params
    .map((param) => {
      let text = param.name;
      if (param.annotation) {
        text += `: ${param.annotation}`;
      }
      if (param.default !== null) {
        text += ` = ${param.default}`;
      }
      return text;
    })
    .join(", ");

  let prefix = "def ";
  if (info.kind === "class") {
    prefix = "class ";
  } else if (info.is_async) {
    prefix = "async def ";
  }

  const signature = `${prefix}${info.name}(${params})`;
  return info.returns ? `${signature} -> ${info.returns}` : signature;
}

export function interfaceToMarkdown(info: InterfaceInfo): string {
  const rows = [
    `### \`${info.name}\``,
    "",
    "```python",
    signatureOf(info),
    "```",
    "",
    `- 类型：${info.kind}`,
    `- 模块：\`${info.module}\``,
    `- 文件：\`${info.file_path}\``,
    `- 版本：v${info.version}`,
  ];
  if (info.commit_hash) {
    rows.push(`- 提交：\`${info.commit_hash}\``);
  }
  if (info.docstring) {
    rows.push("", info.docstring);
  }
  return rows.join("\n");
}

export interface DiffStats {
  additions: number;
  deletions: number;
}

export function diffStats(diff: string): DiffStats {
  let additions = 0;
  let deletions = 0;
  for (const line of diff.split("\n")) {
    if (line.startsWith("+") && !line.startsWith("+++")) {
      additions += 1;
    } else if (line.startsWith("-") && !line.startsWith("---")) {
      deletions += 1;
    }
  }
  return { additions, deletions };
}

export function basename(path: string): string {
  const parts = path.split("/");
  return parts[parts.length - 1] || path;
}
