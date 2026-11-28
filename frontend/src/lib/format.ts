/** 小型展示格式化工具，避免在组件里散落重复逻辑。 */

import type { InterfaceInfo } from "../types";
import {
  getLocale,
  translate,
  type Locale,
  type TKey,
} from "../i18n/dict";

const clockFormatters: Record<Locale, Intl.DateTimeFormat> = {
  zh: new Intl.DateTimeFormat("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }),
  en: new Intl.DateTimeFormat("en-US", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }),
};

const dateTimeFormatters: Record<Locale, Intl.DateTimeFormat> = {
  zh: new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }),
  en: new Intl.DateTimeFormat("en-US", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }),
};

export function formatClock(
  value: string,
  locale: Locale = getLocale(),
): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "--:--:--";
  }
  return clockFormatters[locale].format(date);
}

export function formatDateTime(
  value: string,
  locale: Locale = getLocale(),
): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return translate("format.timeUnknown", undefined, locale);
  }
  return dateTimeFormatters[locale].format(date);
}

export function shortHash(
  hash: string | null,
  locale: Locale = getLocale(),
): string {
  if (!hash) {
    return translate("format.uncommitted", undefined, locale);
  }
  return hash.slice(0, 7);
}

export function signatureOf(info: InterfaceInfo): string {
  const parts: string[] = [];
  let keywordSeparator = false;
  info.params.forEach((param, index) => {
      if (param.kind === "keyword_only" && !keywordSeparator) {
        parts.push("*");
        keywordSeparator = true;
      }
      if (param.name.startsWith("*")) keywordSeparator = true;
      let text = param.name;
      if (param.annotation) {
        text += `: ${param.annotation}`;
      }
      if (param.default != null) {
        text += ` = ${param.default}`;
      }
      parts.push(text);
      if (param.kind === "positional_only" && info.params[index + 1]?.kind !== "positional_only") {
        parts.push("/");
      }
  });
  const params = parts.join(", ");

  let prefix = "def ";
  if (info.kind === "class") {
    prefix = "class ";
  } else if (info.is_async) {
    prefix = "async def ";
  }

  const signature = `${prefix}${info.name}(${params})`;
  return info.returns ? `${signature} -> ${info.returns}` : signature;
}

export function interfaceToMarkdown(
  info: InterfaceInfo,
  locale: Locale = getLocale(),
): string {
  const label = (key: TKey, value: string) =>
    `- ${translate(key, undefined, locale)}：${value}`;
  const rows = [
    `### \`${info.name}\``,
    "",
    "```python",
    signatureOf(info),
    "```",
    "",
    label("format.mdType", info.kind),
    label("format.mdModule", `\`${info.module}\``),
    label("format.mdFile", `\`${info.file_path}\``),
    label("format.mdVersion", `v${info.version}`),
  ];
  if (info.commit_hash) {
    rows.push(label("format.mdCommit", `\`${info.commit_hash}\``));
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
