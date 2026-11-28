import { useEffect, useState, type FormEvent } from "react";

import {
  createApiKey,
  errorMessage,
  listApiKeys,
  revokeApiKey,
  type ApiKeyRow,
  type CreatedApiKey,
} from "../api/client";
import { useT } from "../i18n";
import { useAppStore } from "../store/useAppStore";
import { ErrorBanner } from "./States";

export function ApiKeysPanel() {
  const t = useT();
  const projectId = useAppStore((state) => state.projectId);
  const [keys, setKeys] = useState<ApiKeyRow[]>([]);
  const [name, setName] = useState("coding-agent");
  const [scopeToProject, setScopeToProject] = useState(false);
  const [created, setCreated] = useState<CreatedApiKey | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const refresh = async () => {
    try {
      setKeys(await listApiKeys());
    } catch (loadError) {
      setError(errorMessage(loadError));
    }
  };

  useEffect(() => {
    void refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleCreate = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    setNotice(null);
    setCreated(null);
    try {
      const key = await createApiKey(
        name.trim() || "coding-agent",
        scopeToProject ? projectId : undefined,
      );
      setCreated(key);
      setNotice(t("apikeys.onlyOnce"));
      await refresh();
    } catch (createError) {
      setError(errorMessage(createError));
    } finally {
      setBusy(false);
    }
  };

  const handleRevoke = async (key: ApiKeyRow) => {
    setBusy(true);
    setError(null);
    try {
      await revokeApiKey(key.id);
      setNotice(t("apikeys.revokedNotice", { name: key.name }));
      await refresh();
    } catch (revokeError) {
      setError(errorMessage(revokeError));
    } finally {
      setBusy(false);
    }
  };

  const copy = async (text: string) => {
    try {
      await navigator.clipboard.writeText(text);
      setNotice(t("common.copiedClipboard"));
    } catch {
      setNotice(t("apikeys.copyFailed"));
    }
  };

  return (
    <section className="page">
      <header className="page-head">
        <div>
          <p className="eyebrow">{t("apikeys.eyebrow")}</p>
          <h1>{t("nav.apikeys")}</h1>
          <p className="page-head__desc">{t("apikeys.desc")}</p>
        </div>
      </header>

      {notice ? (
        <p className="inline-notice" role="status">
          {notice}
        </p>
      ) : null}
      {error ? <ErrorBanner message={error} /> : null}

      <div className="panel">
        <div className="panel__head">
          <p className="eyebrow">{t("apikeys.newKey")}</p>
        </div>
        <form className="auth-form" onSubmit={handleCreate}>
          <label>
            {t("apikeys.purpose")}
            <input
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder={t("apikeys.purposePlaceholder")}
            />
          </label>
          <label className="checkbox">
            <input
              type="checkbox"
              checked={scopeToProject}
              onChange={(event) => setScopeToProject(event.target.checked)}
            />
            {t("apikeys.scopeOnly", { project: projectId })}
          </label>
          <button type="submit" className="btn btn--primary" disabled={busy}>
            {busy ? t("apikeys.creating") : t("apikeys.create")}
          </button>
        </form>
        {created ? (
          <div className="key-reveal">
            <p className="auth-hint">{t("apikeys.copyNow")}</p>
            <code className="key-reveal__value">{created.raw_key}</code>
            <button
              type="button"
              className="btn btn--tiny"
              onClick={() => void copy(created.raw_key)}
            >
              {t("common.copy")}
            </button>
          </div>
        ) : null}
      </div>

      <div className="panel">
        <div className="panel__head">
          <p className="eyebrow">{t("apikeys.existing")}</p>
          <span className="mono panel__count">{keys.length}</span>
        </div>
        {keys.length === 0 ? (
          <p className="auth-hint">{t("apikeys.empty")}</p>
        ) : (
          <div className="team-list">
            {keys.map((key) => (
              <div className="team-row" key={key.id}>
                <div>
                  <p className="team-row__name">
                    {key.name}
                    {key.revoked ? t("apikeys.revokedSuffix") : ""}
                  </p>
                  <p className="auth-hint mono">
                    {key.prefix}… ·{" "}
                    {key.project_id ?? t("apikeys.allProjects")} ·{" "}
                    {key.created_at.slice(0, 19)}
                  </p>
                </div>
                {!key.revoked ? (
                  <button
                    type="button"
                    className="btn btn--tiny"
                    disabled={busy}
                    onClick={() => void handleRevoke(key)}
                  >
                    {t("apikeys.revoke")}
                  </button>
                ) : null}
              </div>
            ))}
          </div>
        )}
      </div>
    </section>
  );
}
