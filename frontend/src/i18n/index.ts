/**
 * React 侧的 i18n 入口：订阅当前语言并提供 t() 函数。
 * 非组件代码请直接使用 ./dict 中的 translate / getLocale / setLocale。
 */

import { useCallback, useSyncExternalStore } from "react";

import type { AgentStatus, InterfaceInfo, TaskStatus } from "../types";
import {
  getLocale,
  subscribe,
  translate,
  type Locale,
  type Params,
  type TKey,
} from "./dict";

export * from "./dict";

export function useLocale(): Locale {
  return useSyncExternalStore(subscribe, getLocale, getLocale);
}

export function useT() {
  const locale = useLocale();
  return useCallback(
    (key: TKey, params?: Params) => translate(key, params, locale),
    [locale],
  );
}

export type TFunction = ReturnType<typeof useT>;

export const STATUS_KEY: Record<TaskStatus | AgentStatus, TKey> = {
  planned: "status.planned",
  in_progress: "status.in_progress",
  blocked: "status.blocked",
  completed: "status.completed",
  cancelled: "status.cancelled",
  pending: "status.pending",
  running: "status.running",
  paused: "status.paused",
  succeeded: "status.succeeded",
  failed: "status.failed",
  terminated: "status.terminated",
};

export const KIND_KEY: Record<InterfaceInfo["kind"], TKey> = {
  function: "kind.function",
  method: "kind.method",
  class: "kind.class",
};
