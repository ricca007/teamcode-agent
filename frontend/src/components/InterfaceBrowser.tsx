import { useMemo, useState } from "react";

import { API_BASE, errorMessage, refreshInterfaces } from "../api/client";
import {
  KIND_LABEL,
  interfaceToMarkdown,
  shortHash,
  signatureOf,
} from "../lib/format";
import { useAppStore } from "../store/useAppStore";
import type { InterfaceInfo } from "../types";
import { EmptyState, ErrorBanner, LoadingPanel } from "./States";

const KIND_FILTERS: Array<{ value: InterfaceInfo["kind"] | "all"; label: string }> = [
  { value: "all", label: "全部" },
  { value: "function", label: "函数" },
  { value: "method", label: "方法" },
  { value: "class", label: "类" },
];

function SearchIcon() {
  return (
    <svg
      width="14"
      height="14"
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      aria-hidden="true"
    >
      <circle cx="7" cy="7" r="4.5" />
      <path d="m10.5 10.5 3 3" />
    </svg>
  );
}

export function InterfaceBrowser() {
  const interfaces = useAppStore((state) => state.interfaces);
  const loading = useAppStore((state) => state.loading);
  const error = useAppStore((state) => state.error);
  const projectId = useAppStore((state) => state.projectId);
  const load = useAppStore((state) => state.load);
  const query = useAppStore((state) => state.interfaceQuery);
  const kind = useAppStore((state) => state.interfaceKind);
  const selectedInterfaceId = useAppStore((state) => state.selectedInterfaceId);
  const setInterfaceQuery = useAppStore((state) => state.setInterfaceQuery);
  const setInterfaceKind = useAppStore((state) => state.setInterfaceKind);
  const selectInterface = useAppStore((state) => state.selectInterface);

  const [scanning, setScanning] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [copied, setCopied] = useState<"signature" | "markdown" | null>(null);

  const filtered = useMemo(() => {
    const keyword = query.trim().toLowerCase();
    return interfaces.filter((info) => {
      if (kind !== "all" && info.kind !== kind) {
        return false;
      }
      if (!keyword) {
        return true;
      }
      const haystack =
        `${info.name} ${info.module} ${info.file_path} ${info.docstring ?? ""}`.toLowerCase();
      return haystack.includes(keyword);
    });
  }, [interfaces, query, kind]);

  const selected =
    filtered.find((info) => info.interface_id === selectedInterfaceId) ??
    filtered[0] ??
    null;

  async function handleRescan() {
    setScanning(true);
    setNotice(null);
    try {
      await refreshInterfaces(projectId);
      await load();
      setNotice("接口已重新扫描");
    } catch (scanError) {
      setNotice(errorMessage(scanError));
    } finally {
      setScanning(false);
    }
  }

  async function handleCopy(text: string, target: "signature" | "markdown") {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(target);
      window.setTimeout(() => setCopied(null), 1600);
    } catch {
      setNotice("复制失败，请手动选择文本");
    }
  }

  return (
    <section className="page">
      <header className="page-head">
        <div>
          <p className="eyebrow">接口注册中心</p>
          <h1>接口浏览</h1>
          <p className="page-head__desc">
            AST 自动提取的函数签名、参数与版本。每位成员的 Coding Agent
            通过同一份文档获取接口契约。
          </p>
        </div>
        <div className="page-head__actions">
          <button
            type="button"
            className="btn btn--ghost"
            onClick={() => void handleRescan()}
            disabled={scanning}
          >
            {scanning ? "扫描中" : "重新扫描"}
          </button>
          <a
            className="btn btn--primary"
            href={`${API_BASE}/api/projects/${encodeURIComponent(projectId)}/interfaces?format=markdown`}
            target="_blank"
            rel="noreferrer"
          >
            下载 Markdown
          </a>
        </div>
      </header>

      {notice ? (
        <p className="inline-notice" role="status">
          {notice}
        </p>
      ) : null}

      {error ? (
        <ErrorBanner message={error} onRetry={() => void load()} />
      ) : null}

      {loading && interfaces.length === 0 ? (
        <div className="panel">
          <LoadingPanel label="正在加载接口注册中心" />
        </div>
      ) : (
        <div className="split split--interfaces">
          <div className="panel list-panel">
            <div className="list-panel__tools">
              <label className="search">
                <SearchIcon />
                <span className="sr-only">搜索接口</span>
                <input
                  type="search"
                  value={query}
                  placeholder="搜索名称、模块或路径"
                  onChange={(event) => setInterfaceQuery(event.target.value)}
                />
              </label>
              <div
                className="segmented segmented--sm"
                role="group"
                aria-label="接口类型筛选"
              >
                {KIND_FILTERS.map((filter) => (
                  <button
                    key={filter.value}
                    type="button"
                    aria-pressed={kind === filter.value}
                    onClick={() => setInterfaceKind(filter.value)}
                  >
                    {filter.label}
                  </button>
                ))}
              </div>
            </div>

            <div className="panel__head">
              <p className="eyebrow">接口列表</p>
              <span className="mono panel__count">
                {filtered.length} / {interfaces.length}
              </span>
            </div>

            <div className="list-scroll">
              {filtered.length === 0 ? (
                <EmptyState
                  title={interfaces.length === 0 ? "接口注册中心暂无数据" : "没有匹配的接口"}
                  description={
                    interfaces.length === 0
                      ? "运行 teamcode pull-interfaces，或点击重新扫描。"
                      : "换一个关键词，或把类型筛选切回全部。"
                  }
                />
              ) : (
                filtered.map((info) => {
                  const isActive = selected?.interface_id === info.interface_id;
                  return (
                    <button
                      key={info.interface_id}
                      type="button"
                      className={`iface-row${isActive ? " is-active" : ""}`}
                      aria-pressed={isActive}
                      onClick={() => selectInterface(info.interface_id)}
                    >
                      <span className="iface-row__name mono">{info.name}</span>
                      <span className="iface-row__meta">
                        <span>{KIND_LABEL[info.kind]}</span>
                        <span className="mono">v{info.version}</span>
                      </span>
                      <span className="iface-row__module mono" title={info.file_path}>
                        {info.module}
                      </span>
                    </button>
                  );
                })
              )}
            </div>
          </div>

          <div className="panel detail-panel">
            {selected ? (
              <article>
                <header className="detail-head">
                  <div>
                    <p className="eyebrow">
                      {KIND_LABEL[selected.kind]} · {selected.module}
                    </p>
                    <h2 className="detail-head__name mono">{selected.name}</h2>
                  </div>
                  <span className="chip chip--version mono">v{selected.version}</span>
                </header>

                <div className="code-block">
                  <code>{signatureOf(selected)}</code>
                  <button
                    type="button"
                    className="btn btn--tiny"
                    aria-label="复制函数签名"
                    onClick={() => void handleCopy(signatureOf(selected), "signature")}
                  >
                    {copied === "signature" ? "已复制" : "复制签名"}
                  </button>
                </div>

                {selected.docstring ? (
                  <p className="detail-doc">{selected.docstring}</p>
                ) : (
                  <p className="detail-doc detail-doc--muted">
                    这个接口还没有 docstring。
                  </p>
                )}

                <section className="detail-section">
                  <h3 className="section-title">参数</h3>
                  {selected.params.length === 0 ? (
                    <p className="muted">无参数</p>
                  ) : (
                    <table className="param-table">
                      <thead>
                        <tr>
                          <th scope="col">参数</th>
                          <th scope="col">类型</th>
                          <th scope="col">默认值</th>
                        </tr>
                      </thead>
                      <tbody>
                        {selected.params.map((param) => (
                          <tr key={param.name}>
                            <td className="mono">{param.name}</td>
                            <td className="mono">{param.annotation ?? "未标注"}</td>
                            <td className="mono">{param.default ?? "-"}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                </section>

                <section className="detail-section">
                  <h3 className="section-title">元数据</h3>
                  <dl className="meta-grid">
                    <div>
                      <dt>模块</dt>
                      <dd className="mono">{selected.module}</dd>
                    </div>
                    <div>
                      <dt>位置</dt>
                      <dd className="mono">
                        {selected.file_path}
                        {selected.lineno ? `:${selected.lineno}` : ""}
                      </dd>
                    </div>
                    <div>
                      <dt>返回类型</dt>
                      <dd className="mono">{selected.returns ?? "无"}</dd>
                    </div>
                    <div>
                      <dt>提交</dt>
                      <dd className="mono">{shortHash(selected.commit_hash)}</dd>
                    </div>
                    <div>
                      <dt>装饰器</dt>
                      <dd className="mono">
                        {selected.decorators?.length
                          ? selected.decorators.map((item) => `@${item}`).join(", ")
                          : "无"}
                      </dd>
                    </div>
                    <div>
                      <dt>异步</dt>
                      <dd>{selected.is_async ? "是" : "否"}</dd>
                    </div>
                  </dl>
                </section>

                {selected.dependencies.length > 0 ? (
                  <section className="detail-section">
                    <h3 className="section-title">依赖接口</h3>
                    <ul className="dep-list">
                      {selected.dependencies.map((dependency) => (
                        <li key={dependency} className="mono">
                          {dependency}
                        </li>
                      ))}
                    </ul>
                  </section>
                ) : null}

                <div className="detail-actions">
                  <button
                    type="button"
                    className="btn btn--ghost"
                    onClick={() =>
                      void handleCopy(interfaceToMarkdown(selected), "markdown")
                    }
                  >
                    {copied === "markdown" ? "已复制 Markdown" : "复制 Markdown"}
                  </button>
                </div>
              </article>
            ) : (
              <EmptyState
                title="选择一个接口"
                description="左侧列表展示由 AST 提取的函数、方法与类签名。"
              />
            )}
          </div>
        </div>
      )}
    </section>
  );
}
