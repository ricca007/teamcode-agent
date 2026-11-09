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
import { useAppStore } from "../store/useAppStore";
import { ErrorBanner, LoadingPanel } from "./States";

type Mode = "loading" | "auth" | "setup" | "pending" | "ready";
type AuthTab = "login" | "register";
type SetupTab = "create" | "join";

export function AuthGate({ children }: { children: ReactNode }) {
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
          <LoadingPanel label="正在恢复登录状态" />
        </div>
      </div>
    );
  }

  if (mode === "pending") {
    return (
      <div className="auth-screen">
        <div className="panel auth-card">
          <p className="eyebrow">等待队长批准</p>
          <h1 className="auth-title">已申请加入团队</h1>
          <p className="auth-hint">
            团队 ID：<code>{pendingProjectId}</code>
            <br />
            队长批准后会自动进入，不需要重新登录。
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
              返回
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
          <p className="eyebrow">{userName || "已登录"}</p>
          <h1 className="auth-title">创建或加入团队</h1>
          <div className="segmented" role="group" aria-label="团队方式">
            <button
              type="button"
              aria-pressed={setupTab === "create"}
              onClick={() => setSetupTab("create")}
            >
              创建团队
            </button>
            <button
              type="button"
              aria-pressed={setupTab === "join"}
              onClick={() => setSetupTab("join")}
            >
              加入团队
            </button>
          </div>
          {error ? <ErrorBanner message={error} /> : null}
          {setupTab === "create" ? (
            <form className="auth-form" onSubmit={handleCreate}>
              <label>
                团队名称
                <input
                  value={teamName}
                  onChange={(event) => setTeamName(event.target.value)}
                  required
                />
              </label>
              <label>
                代码仓库路径（必须是 Git 仓库）
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
                {busy ? "创建中" : "创建并成为队长"}
              </button>
            </form>
          ) : (
            <form className="auth-form" onSubmit={handleJoin}>
              <label>
                团队 ID
                <input
                  value={joinProjectId}
                  onChange={(event) => setJoinProjectId(event.target.value)}
                  placeholder="例如 p_demo"
                  required
                />
              </label>
              <button
                type="submit"
                className="btn btn--primary"
                disabled={busy}
              >
                {busy ? "申请中" : "申请加入"}
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
        <p className="eyebrow">TeamCode</p>
        <h1 className="auth-title">登录或注册</h1>
        <p className="auth-hint">
          一个账号可以加入多个团队；在不同团队里可以是队长或组员，
          也可同时在多个项目中拥有任务。
        </p>
        <div className="segmented" role="group" aria-label="登录方式">
          <button
            type="button"
            aria-pressed={authTab === "login"}
            onClick={() => setAuthTab("login")}
          >
            登录
          </button>
          <button
            type="button"
            aria-pressed={authTab === "register"}
            onClick={() => setAuthTab("register")}
          >
            注册
          </button>
        </div>
        {error ? <ErrorBanner message={error} /> : null}
        {authTab === "login" ? (
          <form className="auth-form" onSubmit={handleLogin}>
            <label>
              邮箱
              <input
                type="email"
                value={loginEmail}
                onChange={(event) => setLoginEmail(event.target.value)}
                required
              />
            </label>
            <label>
              密码
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
              {busy ? "登录中" : "登录"}
            </button>
          </form>
        ) : (
          <form className="auth-form" onSubmit={handleRegister}>
            <label>
              昵称
              <input
                value={regName}
                onChange={(event) => setRegName(event.target.value)}
                required
              />
            </label>
            <label>
              邮箱
              <input
                type="email"
                value={regEmail}
                onChange={(event) => setRegEmail(event.target.value)}
                required
              />
            </label>
            <label>
              密码（至少 6 位）
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
              {busy ? "注册中" : "注册"}
            </button>
          </form>
        )}
      </div>
    </div>
  );
}
