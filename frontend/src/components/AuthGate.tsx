import {
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type ReactNode,
} from "react";

import {
  createProject,
  errorMessage,
  getAuthToken,
  getMe,
  getMyProjects,
  joinTeam,
  loginAccount,
  registerAccount,
  setAuthToken,
  type AuthResult,
  type ProjectSummary,
} from "../api/client";
import { useT } from "../i18n";
import { useAppStore } from "../store/useAppStore";
import { LanguageToggle } from "./LanguageToggle";
import { ErrorBanner, LoadingPanel } from "./States";

type Mode = "loading" | "auth" | "setup" | "pending" | "ready";
type AuthTab = "login" | "register";
type SetupTab = "create" | "join";

export function AuthGate({ children }: { children: ReactNode }) {
  const t = useT();
  const [mode, setMode] = useState<Mode>("loading");
  const [authTab, setAuthTab] = useState<AuthTab>("login");
  const [setupTab, setSetupTab] = useState<SetupTab>("create");
  const [userName, setUserName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [loginEmail, setLoginEmail] = useState("");
  const [loginPassword, setLoginPassword] = useState("");
  const [regName, setRegName] = useState("");
  const [regEmail, setRegEmail] = useState("");
  const [regPassword, setRegPassword] = useState("");

  const [teamName, setTeamName] = useState("");
  const [repoPath, setRepoPath] = useState("");
  const [joinProjectId, setJoinProjectId] = useState("");
  const [pendingProjectId, setPendingProjectId] = useState<string | null>(null);

  const pollRef = useRef<number | undefined>(undefined);

  const [userId, setUserId] = useState("");

  const applyProjects = (
    projects: ProjectSummary[],
    name: string,
    id: string,
  ) => {
    if (projects.length === 0) {
      setMode("setup");
      return;
    }
    const saved = window.localStorage.getItem("tc_project_id");
    const chosen = projects.find((item) => item.id === saved) ?? projects[0];
    const store = useAppStore.getState();
    store.setAuth(chosen.role, name, id);
    store.setProjects(projects);
    store.selectProject(chosen);
    setMode("ready");
  };

  const bootstrap = async () => {
    if (!getAuthToken()) {
      setMode("auth");
      return;
    }
    try {
      const me = await getMe();
      setUserName(me.name);
      setUserId(me.user_id);
      window.localStorage.setItem("tc_user_name", me.name);
      applyProjects(await getMyProjects(), me.name, me.user_id);
    } catch {
      setAuthToken("");
      setMode("auth");
    }
  };

  useEffect(() => {
    void bootstrap();
    return () => window.clearInterval(pollRef.current);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const completeAuth = async (result: AuthResult) => {
    setAuthToken(result.token);
    window.localStorage.setItem("tc_user_name", result.user.name);
    setUserName(result.user.name);
    setUserId(result.user.id);
    applyProjects(await getMyProjects(), result.user.name, result.user.id);
  };

  const handleLogin = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await completeAuth(
        await loginAccount({
          email: loginEmail.trim(),
          password: loginPassword,
        }),
      );
    } catch (loginError) {
      setError(errorMessage(loginError));
    } finally {
      setBusy(false);
    }
  };

  const handleRegister = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await completeAuth(
        await registerAccount({
          name: regName.trim(),
          email: regEmail.trim(),
          password: regPassword,
        }),
      );
    } catch (registerError) {
      setError(errorMessage(registerError));
    } finally {
      setBusy(false);
    }
  };

  const handleCreate = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await createProject({
        name: teamName.trim(),
        repo_path: repoPath.trim(),
      });
      applyProjects(await getMyProjects(), userName, userId);
    } catch (createError) {
      setError(errorMessage(createError));
    } finally {
      setBusy(false);
    }
  };

  const handleJoin = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await joinTeam(joinProjectId.trim());
      setPendingProjectId(joinProjectId.trim());
      setMode("pending");
    } catch (joinError) {
      setError(errorMessage(joinError));
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => {
    if (mode !== "pending" || pendingProjectId === null) {
      return;
    }
    const check = async () => {
      try {
        const projects = await getMyProjects();
        if (projects.some((item) => item.id === pendingProjectId)) {
          applyProjects(projects, userName, userId);
        }
      } catch (pollError) {
        setError(errorMessage(pollError));
      }
    };
    void check();
    pollRef.current = window.setInterval(() => void check(), 2000);
    return () => window.clearInterval(pollRef.current);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode, pendingProjectId, userName, userId]);

  if (mode === "ready") {
    return <>{children}</>;
  }

  if (mode === "loading") {
    return (
      <div className="auth-screen">
        <div className="panel auth-card">
          <div className="auth-lang">
            <LanguageToggle />
          </div>
          <LoadingPanel label={t("auth.restoring")} />
        </div>
      </div>
    );
  }

  if (mode === "pending") {
    return (
      <div className="auth-screen">
        <div className="panel auth-card">
          <div className="auth-lang">
            <LanguageToggle />
          </div>
          <p className="eyebrow">{t("auth.pendingEyebrow")}</p>
          <h1 className="auth-title">{t("auth.pendingTitle")}</h1>
          <p className="auth-hint">
            {t("auth.teamId")}：<code>{pendingProjectId}</code>
            <br />
            {t("auth.autoEnter")}
          </p>
          {error ? <ErrorBanner message={error} /> : null}
          <div className="auth-actions">
            <button
              type="button"
              className="btn btn--ghost"
              onClick={() => {
                setPendingProjectId(null);
                setMode("setup");
              }}
            >
              {t("auth.back")}
            </button>
          </div>
        </div>
      </div>
    );
  }

  if (mode === "setup") {
    return (
      <div className="auth-screen">
        <div className="panel auth-card">
          <div className="auth-lang">
            <LanguageToggle />
          </div>
          <p className="eyebrow">{userName || t("auth.loggedIn")}</p>
          <h1 className="auth-title">{t("auth.setupTitle")}</h1>
          <div className="segmented" role="group" aria-label={t("auth.teamMode")}>
            <button
              type="button"
              aria-pressed={setupTab === "create"}
              onClick={() => setSetupTab("create")}
            >
              {t("auth.createTeam")}
            </button>
            <button
              type="button"
              aria-pressed={setupTab === "join"}
              onClick={() => setSetupTab("join")}
            >
              {t("auth.joinTeam")}
            </button>
          </div>
          {error ? <ErrorBanner message={error} /> : null}
          {setupTab === "create" ? (
            <form className="auth-form" onSubmit={handleCreate}>
              <label>
                {t("auth.teamName")}
                <input
                  value={teamName}
                  onChange={(event) => setTeamName(event.target.value)}
                  required
                />
              </label>
              <label>
                {t("auth.repoPath")}
                <input
                  value={repoPath}
                  onChange={(event) => setRepoPath(event.target.value)}
                  placeholder="/path/to/repo"
                  required
                />
              </label>
              <button
                type="submit"
                className="btn btn--primary"
                disabled={busy}
              >
                {busy ? t("auth.creating") : t("auth.createBecomeLeader")}
              </button>
            </form>
          ) : (
            <form className="auth-form" onSubmit={handleJoin}>
              <label>
                {t("auth.teamId")}
                <input
                  value={joinProjectId}
                  onChange={(event) => setJoinProjectId(event.target.value)}
                  placeholder={t("auth.teamIdPlaceholder")}
                  required
                />
              </label>
              <button
                type="submit"
                className="btn btn--primary"
                disabled={busy}
              >
                {busy ? t("auth.applying") : t("auth.applyJoin")}
              </button>
            </form>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="auth-screen">
      <div className="panel auth-card">
        <div className="auth-lang">
          <LanguageToggle />
        </div>
        <p className="eyebrow">TeamCode</p>
        <h1 className="auth-title">{t("auth.loginOrRegister")}</h1>
        <p className="auth-hint">{t("auth.hint")}</p>
        <div className="segmented" role="group" aria-label={t("auth.loginMode")}>
          <button
            type="button"
            aria-pressed={authTab === "login"}
            onClick={() => setAuthTab("login")}
          >
            {t("auth.login")}
          </button>
          <button
            type="button"
            aria-pressed={authTab === "register"}
            onClick={() => setAuthTab("register")}
          >
            {t("auth.register")}
          </button>
        </div>
        {error ? <ErrorBanner message={error} /> : null}
        {authTab === "login" ? (
          <form className="auth-form" onSubmit={handleLogin}>
            <label>
              {t("auth.email")}
              <input
                type="email"
                value={loginEmail}
                onChange={(event) => setLoginEmail(event.target.value)}
                required
              />
            </label>
            <label>
              {t("auth.password")}
              <input
                type="password"
                value={loginPassword}
                onChange={(event) => setLoginPassword(event.target.value)}
                required
              />
            </label>
            <button
              type="submit"
              className="btn btn--primary"
              disabled={busy}
            >
              {busy ? t("auth.loggingIn") : t("auth.login")}
            </button>
          </form>
        ) : (
          <form className="auth-form" onSubmit={handleRegister}>
            <label>
              {t("auth.nickname")}
              <input
                value={regName}
                onChange={(event) => setRegName(event.target.value)}
                required
              />
            </label>
            <label>
              {t("auth.email")}
              <input
                type="email"
                value={regEmail}
                onChange={(event) => setRegEmail(event.target.value)}
                required
              />
            </label>
            <label>
              {t("auth.passwordMin")}
              <input
                type="password"
                value={regPassword}
                onChange={(event) => setRegPassword(event.target.value)}
                minLength={6}
                required
              />
            </label>
            <button
              type="submit"
              className="btn btn--primary"
              disabled={busy}
            >
              {busy ? t("auth.registering") : t("auth.register")}
            </button>
          </form>
        )}
      </div>
    </div>
  );
}
