import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, ".", "VITE_");
  const backendHttp = env.VITE_BACKEND_HTTP || "http://127.0.0.1:8000";
  const backendWs = backendHttp.replace(/^http/, "ws");

  return {
    plugins: [react()],
    server: {
      port: 5173,
      // 开发时同源代理，避免浏览器跨域；部署在独立域名时改用 VITE_API_BASE
      proxy: {
        "/api": { target: backendHttp, changeOrigin: true },
        "/ws": { target: backendWs, ws: true },
      },
    },
  };
});
