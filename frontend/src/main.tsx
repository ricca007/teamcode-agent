import "@fontsource/ibm-plex-sans/400.css";
import "@fontsource/ibm-plex-sans/500.css";
import "@fontsource/ibm-plex-sans/600.css";
import "@fontsource/ibm-plex-mono/400.css";
import "@fontsource/ibm-plex-mono/500.css";

import React from "react";
import ReactDOM from "react-dom/client";

import App from "./App";
import { AuthGate } from "./components/AuthGate";
import "./styles.css";

// 兜底记录未被组件捕获的异常，便于现场排查
window.addEventListener("unhandledrejection", (event) => {
  console.error("[TeamCode] 未处理的 Promise 异常", event.reason);
});
window.addEventListener("error", (event) => {
  console.error("[TeamCode] 未捕获的运行时错误", event.error ?? event.message);
});

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <AuthGate>
      <App />
    </AuthGate>
  </React.StrictMode>,
);
