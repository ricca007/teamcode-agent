import { useEffect, useState, type FormEvent } from "react";

import {
  createApiKey,
  errorMessage,
  listApiKeys,
  revokeApiKey,
  type ApiKeyRow,
  type CreatedApiKey,
} from "../api/client";
import { useAppStore } from "../store/useAppStore";
import { ErrorBanner } from "./States";

export function ApiKeysPanel() {
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
      setNotice("API Key 只显示一次，请立即复制保存");
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
      setNotice(`已撤销 ${key.name}`);
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
      setNotice("已复制到剪贴板");
    } catch {
      setNotice("复制失败，请手动选择");
    }
  };

  return (
    <section className="page">
      <header className="page-head">
        <div>
          <p className="eyebrow">程序化访问</p>
          <h1>API Key</h1>
          <p className="page-head__desc">
            给 Coding Agent、CLI 或外部脚本使用的长期凭据。Key 继承你的账号和项目角色，
            可随时撤销。
          </p>
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
          <p className="eyebrow">新建 Key</p>
        </div>
        <form className="auth-form" onSubmit={handleCreate}>
          <label>
            用途名称
            <input
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="例如 claude-code-lin"
            />
          </label>
          <label className="checkbox">
            <input
              type="checkbox"
              checked={scopeToProject}
              onChange={(event) => setScopeToProject(event.target.checked)}
            />
            仅限当前项目 {projectId}
          </label>
          <button type="submit" className="btn btn--primary" disabled={busy}>
            {busy ? "创建中" : "生成 API Key"}
          </button>
        </form>
        {created ? (
          <div className="key-reveal">
            <p className="auth-hint">请立即复制，关闭后无法再次查看：</p>
            <code className="key-reveal__value">{created.raw_key}</code>
            <button
              type="button"
              className="btn btn--tiny"
              onClick={() => void copy(created.raw_key)}
            >
              复制
            </button>
          </div>
        ) : null}
      </div>

      <div className="panel">
        <div className="panel__head">
          <p className="eyebrow">已有 Key</p>
          <span className="mono panel__count">{keys.length}</span>
        </div>
        {keys.length === 0 ? (
          <p className="auth-hint">还没有 API Key。</p>
        ) : (
          <div className="team-list">
            {keys.map((key) => (
              <div className="team-row" key={key.id}>
                <div>
                  <p className="team-row__name">
                    {key.name}
                    {key.revoked ? "（已撤销）" : ""}
                  </p>
                  <p className="auth-hint mono">
                    {key.prefix}… · {key.project_id ?? "全部项目"} ·{" "}
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
                    撤销
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
