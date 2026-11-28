import { useMemo, useState } from "react";

import { downloadInterfaceMarkdown, errorMessage, refreshInterfaces } from "../api/client";
import { KIND_KEY, useLocale, useT, type TKey } from "../i18n";
import { interfaceToMarkdown, shortHash, signatureOf } from "../lib/format";
import { useAppStore } from "../store/useAppStore";
import type { InterfaceInfo } from "../types";
import { EmptyState, ErrorBanner, LoadingPanel } from "./States";

const KIND_FILTERS: Array<{
  value: InterfaceInfo["kind"] | "all";
  label: TKey;
}> = [
  { value: "all", label: "kind.all" },
  { value: "function", label: "kind.function" },
  { value: "method", label: "kind.method" },
  { value: "class", label: "kind.class" },
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
  const t = useT();
  const locale = useLocale();
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
      setNotice(t("interfaces.rescanned"));
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
      setNotice(t("interfaces.copyFailed"));
    }
  }

  return (
    <section className="page">
      <header className="page-head">
        <div>
          <p className="eyebrow">{t("interfaces.eyebrow")}</p>
          <h1>{t("nav.interfaces")}</h1>
          <p className="page-head__desc">{t("interfaces.desc")}</p>
        </div>
        <div className="page-head__actions">
          <button
            type="button"
            className="btn btn--ghost"
            onClick={() => void handleRescan()}
            disabled={scanning}
          >
            {scanning ? t("interfaces.scanning") : t("interfaces.rescan")}
          </button>
          <button
            type="button"
            className="btn btn--primary"
            onClick={() => void downloadInterfaceMarkdown(projectId, locale).catch(
              (downloadError) => setNotice(errorMessage(downloadError)),
            )}
          >
            {t("interfaces.download")}
          </button>
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
          <LoadingPanel label={t("interfaces.loading")} />
        </div>
      ) : (
        <div className="split split--interfaces">
          <div className="panel list-panel">
            <div className="list-panel__tools">
              <label className="search">
                <SearchIcon />
                <span className="sr-only">{t("interfaces.search")}</span>
                <input
                  type="search"
                  value={query}
                  placeholder={t("interfaces.searchPlaceholder")}
                  onChange={(event) => setInterfaceQuery(event.target.value)}
                />
              </label>
              <div
                className="segmented segmented--sm"
                role="group"
                aria-label={t("interfaces.kindFilter")}
              >
                {KIND_FILTERS.map((filter) => (
                  <button
                    key={filter.value}
                    type="button"
                    aria-pressed={kind === filter.value}
                    onClick={() => setInterfaceKind(filter.value)}
                  >
                    {t(filter.label)}
                  </button>
                ))}
              </div>
            </div>

            <div className="panel__head">
              <p className="eyebrow">{t("interfaces.list")}</p>
              <span className="mono panel__count">
                {filtered.length} / {interfaces.length}
              </span>
            </div>

            <div className="list-scroll">
              {filtered.length === 0 ? (
                <EmptyState
                  title={
                    interfaces.length === 0
                      ? t("interfaces.emptyTitle")
                      : t("interfaces.mismatchTitle")
                  }
                  description={
                    interfaces.length === 0
                      ? t("interfaces.emptyDesc")
                      : t("interfaces.mismatchDesc")
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
                        <span>{t(KIND_KEY[info.kind])}</span>
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
                      {t(KIND_KEY[selected.kind])} · {selected.module}
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
                    aria-label={t("interfaces.copySignatureAria")}
                    onClick={() => void handleCopy(signatureOf(selected), "signature")}
                  >
                    {copied === "signature"
                      ? t("common.copied")
                      : t("interfaces.copySignature")}
                  </button>
                </div>

                {selected.docstring ? (
                  <p className="detail-doc">{selected.docstring}</p>
                ) : (
                  <p className="detail-doc detail-doc--muted">
                    {t("interfaces.noDocstring")}
                  </p>
                )}

                <section className="detail-section">
                  <h3 className="section-title">{t("interfaces.params")}</h3>
                  {selected.params.length === 0 ? (
                    <p className="muted">{t("interfaces.noParams")}</p>
                  ) : (
                    <table className="param-table">
                      <thead>
                        <tr>
                          <th scope="col">{t("interfaces.param")}</th>
                          <th scope="col">{t("interfaces.type")}</th>
                          <th scope="col">{t("interfaces.default")}</th>
                        </tr>
                      </thead>
                      <tbody>
                        {selected.params.map((param) => (
                          <tr key={param.name}>
                            <td className="mono">{param.name}</td>
                            <td className="mono">
                              {param.annotation ?? t("interfaces.notAnnotated")}
                            </td>
                            <td className="mono">{param.default ?? "-"}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                </section>

                <section className="detail-section">
                  <h3 className="section-title">{t("interfaces.metadata")}</h3>
                  <dl className="meta-grid">
                    <div>
                      <dt>{t("interfaces.module")}</dt>
                      <dd className="mono">{selected.module}</dd>
                    </div>
                    <div>
                      <dt>{t("interfaces.location")}</dt>
                      <dd className="mono">
                        {selected.file_path}
                        {selected.lineno ? `:${selected.lineno}` : ""}
                      </dd>
                    </div>
                    <div>
                      <dt>{t("interfaces.returns")}</dt>
                      <dd className="mono">
                        {selected.returns ?? t("common.none")}
                      </dd>
                    </div>
                    <div>
                      <dt>{t("interfaces.commit")}</dt>
                      <dd className="mono">
                        {shortHash(selected.commit_hash, locale)}
                      </dd>
                    </div>
                    <div>
                      <dt>{t("interfaces.decorators")}</dt>
                      <dd className="mono">
                        {selected.decorators?.length
                          ? selected.decorators.map((item) => `@${item}`).join(", ")
                          : t("common.none")}
                      </dd>
                    </div>
                    <div>
                      <dt>{t("interfaces.async")}</dt>
                      <dd>{selected.is_async ? t("common.yes") : t("common.no")}</dd>
                    </div>
                  </dl>
                </section>

                {selected.dependencies.length > 0 ? (
                  <section className="detail-section">
                    <h3 className="section-title">
                      {t("interfaces.dependencies")}
                    </h3>
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
                      void handleCopy(
                        interfaceToMarkdown(selected, locale),
                        "markdown",
                      )
                    }
                  >
                    {copied === "markdown"
                      ? t("interfaces.markdownCopied")
                      : t("interfaces.copyMarkdown")}
                  </button>
                </div>
              </article>
            ) : (
              <EmptyState
                title={t("interfaces.selectTitle")}
                description={t("interfaces.selectDesc")}
              />
            )}
          </div>
        </div>
      )}
    </section>
  );
}
