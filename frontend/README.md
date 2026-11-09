# TeamCode Dashboard

React + TypeScript 协作控制台，只连接真实后端（不再提供本地演示数据）。

## 开发

```bash
npm install
npm run dev
```

Vite 会把 `/api` 与 `/ws` 代理到 `http://127.0.0.1:8000`（可用
`VITE_BACKEND_HTTP` 覆盖）。侧栏可以切换项目 ID，默认读取
`VITE_PROJECT_ID`（默认 `p_001`）。

## 构建

```bash
npm run build
```
