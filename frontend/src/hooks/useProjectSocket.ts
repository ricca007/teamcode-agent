/**
 * WebSocket 订阅与断线重连。
 *
 * - 按事件类型把处理交给 store，组件不直接接触 socket；
 * - 断线后指数退避重连，上限 15 秒；
 * - 定期发送 ping，服务端返回 pong（用于确认连接活性）。
 */

import { useEffect } from "react";

import { WS_BASE, getAuthToken } from "../api/client";
import { useAppStore } from "../store/useAppStore";
import type { WSEvent } from "../types";

export function useProjectSocket(): void {
  const projectId = useAppStore((state) => state.projectId);
  const handleEvent = useAppStore((state) => state.handleEvent);
  const setConnection = useAppStore((state) => state.setConnection);
  const load = useAppStore((state) => state.load);

  useEffect(() => {
    let socket: WebSocket | null = null;
    let retryTimer: number | undefined;
    let pingTimer: number | undefined;
    let attempts = 0;
    let disposed = false;

    const connect = () => {
      if (disposed) {
        return;
      }
      setConnection("connecting");
      const token = getAuthToken();
      const query = token ? `?token=${encodeURIComponent(token)}` : "";
      socket = new WebSocket(
        `${WS_BASE}/ws/projects/${encodeURIComponent(projectId)}${query}`,
      );

      socket.onopen = () => {
        const wasReconnect = attempts > 0;
        attempts = 0;
        setConnection("open");
        if (wasReconnect) {
          // 断线期间的事件不会补发：重连后主动全量刷新，避免界面停留在旧状态
          console.info("[TeamCode] WebSocket 重连成功，重新拉取项目数据");
          void load(true);
        }
        pingTimer = window.setInterval(() => {
          if (socket?.readyState === WebSocket.OPEN) {
            socket.send("ping");
          }
        }, 25000);
      };

      socket.onmessage = (message) => {
        try {
          const raw = JSON.parse(message.data) as { type?: string };
          if (raw.type === "pong") {
            return;
          }
          handleEvent(raw as WSEvent);
        } catch {
          console.warn("[TeamCode] 收到非 JSON 的 WebSocket 消息，已忽略");
        }
      };

      socket.onclose = () => {
        window.clearInterval(pingTimer);
        if (disposed) {
          return;
        }
        setConnection("closed");
        const delay = Math.min(15000, 1000 * 2 ** attempts);
        attempts += 1;
        retryTimer = window.setTimeout(connect, delay);
      };

      socket.onerror = () => {
        console.warn("[TeamCode] WebSocket 连接异常，准备重连");
        socket?.close();
      };
    };

    connect();

    return () => {
      disposed = true;
      window.clearTimeout(retryTimer);
      window.clearInterval(pingTimer);
      socket?.close();
      socket = null;
    };
  }, [projectId, handleEvent, setConnection, load]);
}
