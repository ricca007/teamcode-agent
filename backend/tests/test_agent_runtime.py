import asyncio
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from app.agent_runtime.cli_adapter import CLIAdapter, CLIAdapterConfig
from app.agent_runtime.execution import ExecutionService
from app.agent_runtime.mock_adapter import MockAdapter
from app.agent_runtime.session_manager import SessionManager
from app.api.execution import ExecutionAPI
from app.errors import (
    AdapterError,
    InvalidStateTransitionError,
    InvalidTaskError,
    PermissionDeniedError,
    TaskAlreadyRunningError,
    WorkspaceError,
)
from app.git_ops.workspace import collect_changes, commit_changes, create_workspace
from app.log_stream import LogBroker
from app.schemas.core import AgentStatus, TaskSpec
from app.security.path_policy import validate_paths


def run_git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-c", "user.name=Role2 Test", "-c", "user.email=role2@example.invalid", *args],
        cwd=str(repo),
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise AssertionError(result.stderr or result.stdout)
    return result.stdout


def make_repo(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    run_git(root, "init")
    run_git(root, "checkout", "-b", "main")
    (root / "README.md").write_text("initial\n", encoding="utf-8")
    run_git(root, "add", "README.md")
    run_git(root, "commit", "-m", "initial")
    return root


def make_task(task_id="t1", owner="u1", allowed=("src/**",)) -> TaskSpec:
    return TaskSpec(
        task_id=task_id,
        title="Test task",
        description="Create a small module",
        owner_id=owner,
        allowed_paths=tuple(allowed),
        acceptance_criteria=(),
    )


class LogBrokerTests(unittest.IsolatedAsyncioTestCase):
    async def test_history_replays_missed_events(self):
        broker = LogBroker()
        await broker.publish("p1", {"type": "agent.log", "payload": {"message": "one"}})
        await broker.publish("p1", {"type": "agent.log", "payload": {"message": "two"}})
        self.assertEqual(
            [event["payload"]["message"] for event in broker.history("p1")],
            ["one", "two"],
        )
        queue = broker.subscribe("p1", after_event_id=1)
        self.assertEqual(queue.get_nowait()["payload"]["message"], "two")
        broker.close()
        with self.assertRaises(RuntimeError):
            broker.subscribe("p1")


class PathPolicyTests(unittest.TestCase):
    def test_rejects_parent_absolute_and_symlink_escape(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            root.mkdir()
            outside = Path(tmp) / "outside.txt"
            outside.write_text("secret", encoding="utf-8")
            (root / "link").symlink_to(outside)

            result = validate_paths(
                root,
                ["../escape.py", "/tmp/absolute.py", "link/read.txt"],
                ["src/**"],
            )
            self.assertFalse(result.ok)
            self.assertEqual(len(result.rejected), 3)
            self.assertTrue(any("parent traversal" in reason for _, reason in result.rejected))
            self.assertTrue(any("absolute" in reason for _, reason in result.rejected))
            self.assertTrue(any("escapes project root" in reason for _, reason in result.rejected))

    def test_allowed_directory_and_glob_are_case_insensitive(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = validate_paths(
                root,
                ["SRC/app.py", "docs/api.md"],
                ["src", "docs/**"],
            )
            self.assertTrue(result.ok)
            self.assertEqual(result.allowed, ("SRC/app.py", "docs/api.md"))

    def test_reserved_metadata_paths_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = validate_paths(
                Path(tmp),
                [".git/config", "src/.teamcode/cache.json"],
                ["**"],
            )
            self.assertFalse(result.ok)
            self.assertEqual(len(result.rejected), 2)
            self.assertTrue(
                all(
                    "reserved project metadata path" in reason
                    for _, reason in result.rejected
                )
            )

    def test_single_star_does_not_cross_directories(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = validate_paths(
                Path(tmp),
                ["src/a.py", "src/nested/b.py"],
                ["src/*.py"],
            )
            self.assertEqual(result.allowed, ("src/a.py",))
            self.assertEqual(
                result.rejected,
                (("src/nested/b.py", "path is outside allowed_paths"),),
            )

    def test_double_star_can_cross_directories(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = validate_paths(
                Path(tmp),
                ["src/a.py", "src/nested/b.py"],
                ["src/**/*.py"],
            )
            self.assertEqual(result.allowed, ("src/a.py", "src/nested/b.py"))


class MockRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_mock_logs_state_and_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            adapter = MockAdapter()
            manager = SessionManager(broker=LogBroker())
            task = make_task()
            info = await manager.start_session("p1", task, workspace, adapter)
            self.assertEqual(info.status, AgentStatus.PENDING)

            events = manager.broker.subscribe("p1")
            status = await manager.send_task(
                info.session_id,
                "prompt",
                context={"write_files": {"src/app.py": "def get_user():\n    return 1\n"}},
            )
            self.assertEqual(status, AgentStatus.SUCCEEDED)
            changes = await manager.get_changes(info.session_id)
            self.assertEqual(changes.files, ["src/app.py"])
            self.assertTrue((workspace / "src/app.py").exists())

            seen = []
            while not events.empty():
                seen.append(events.get_nowait())
            self.assertTrue(seen)
            self.assertTrue(all(event["type"] == "agent.log" for event in seen))
            self.assertTrue(manager.list_logs(info.session_id))
            self.assertIsNotNone(manager.get_session(info.session_id).ended_at)

    async def test_mock_rejects_parent_traversal(self):
        with tempfile.TemporaryDirectory() as tmp:
            adapter = MockAdapter()
            manager = SessionManager()
            info = await manager.start_session("p1", make_task(), Path(tmp), adapter)
            status = await manager.send_task(
                info.session_id,
                "prompt",
                context={"write_files": {"../outside.py": "bad"}},
            )
            self.assertEqual(status, AgentStatus.FAILED)
            self.assertFalse((Path(tmp).parent / "outside.py").exists())

    async def test_invalid_transition_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            adapter = MockAdapter()
            manager = SessionManager()
            info = await manager.start_session("p1", make_task(), Path(tmp), adapter)
            await manager.send_task(info.session_id, "prompt")
            with self.assertRaises(InvalidStateTransitionError):
                await manager.pause(info.session_id)


class ExecutionServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_end_to_end_and_permission(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_repo(Path(tmp) / "repo")
            manager = SessionManager()
            service = ExecutionService(repo_root=repo, sessions=manager, leader_id="lead")
            task = make_task()
            result = await service.run(
                "p1",
                task,
                actor_id="u1",
                adapter=MockAdapter(),
                context={"write_files": {"src/app.py": "def get_user():\n    return 1\n"}},
            )
            self.assertTrue(result.ok)
            self.assertEqual(result.status, AgentStatus.SUCCEEDED)
            self.assertEqual(result.changes.files, ["src/app.py"])
            self.assertGreaterEqual(result.duration_ms, 0)
            self.assertGreater(result.log_count, 0)
            self.assertTrue(service.commit_task("t1", "u1", "implement user lookup"))

            with self.assertRaises(PermissionDeniedError):
                await service.run("p1", task, actor_id="someone-else", adapter=MockAdapter())

            bad_task = make_task(allowed=("src/**",))
            bad_result = await service.run(
                "p1",
                bad_task,
                actor_id="lead",
                adapter=MockAdapter(),
                context={"write_files": {"outside.py": "print('bad')\n"}},
            )
            self.assertFalse(bad_result.ok)
            self.assertEqual(bad_result.rejected_paths, ["outside.py"])

    async def test_adapter_registry_selects_adapter(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = ExecutionService(
                repo_root=make_repo(Path(tmp) / "repo"),
                sessions=SessionManager(),
                leader_id="lead",
                adapter_registry={"mock": MockAdapter},
            )
            result = await service.run(
                "p1",
                make_task(task_id="t-registry"),
                actor_id="u1",
                adapter_name="mock",
                context={"write_files": {"src/app.py": "x = 1\n"}},
            )
            self.assertTrue(result.ok)
            with self.assertRaises(ValueError):
                await service.run(
                    "p1",
                    make_task(task_id="t-registry-2"),
                    actor_id="u1",
                    adapter_name="missing",
                )

    async def test_service_rejects_same_task_id_across_projects(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = ExecutionService(
                repo_root=make_repo(Path(tmp) / "repo"),
                sessions=SessionManager(),
                leader_id="lead",
            )
            task = make_task(task_id="t-shared-service")
            await service.run("p1", task, actor_id="u1", adapter=MockAdapter())
            with self.assertRaises(InvalidTaskError):
                await service.run("p2", task, actor_id="u1", adapter=MockAdapter())

    async def test_same_task_cannot_run_twice_concurrently(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_repo(Path(tmp) / "repo")
            service = ExecutionService(
                repo_root=repo,
                sessions=SessionManager(),
                leader_id="lead",
            )
            task = make_task()

            async def run_one():
                return await service.run(
                    "p1",
                    task,
                    actor_id="u1",
                    adapter=MockAdapter(delay=0.05),
                    context={"write_files": {"src/app.py": "x = 1\n"}},
                )

            first, second = await asyncio.gather(
                run_one(),
                run_one(),
                return_exceptions=True,
            )
            self.assertTrue(
                any(isinstance(item, TaskAlreadyRunningError) for item in (first, second))
            )
            self.assertTrue(any(not isinstance(item, Exception) for item in (first, second)))

    async def test_commit_gate_rejects_unauthorized_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_repo(Path(tmp) / "repo")
            workspace = create_workspace("p1", "t-commit", repo)
            (workspace.worktree_path / "src").mkdir()
            (workspace.worktree_path / "src" / "ok.py").write_text("x = 1\n", encoding="utf-8")
            (workspace.worktree_path / "bad.py").write_text("y = 2\n", encoding="utf-8")
            with self.assertRaises(PermissionDeniedError):
                commit_changes(workspace, ("src/**",), "should fail")

            (workspace.worktree_path / "bad.py").unlink()
            commit_hash = commit_changes(workspace, ("src/**",), "add allowed file")
            self.assertTrue(commit_hash)
            with self.assertRaises(WorkspaceError):
                commit_changes(
                    workspace,
                    ("src/**",),
                    "invalid identity",
                    author_name="bad\nname",
                )


class ExecutionAPITests(unittest.IsolatedAsyncioTestCase):
    async def test_api_error_codes_are_structured(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = ExecutionService(
                repo_root=make_repo(Path(tmp) / "repo"),
                sessions=SessionManager(),
                leader_id="lead",
            )
            api = ExecutionAPI(service)
            response = await api.status("missing-session", actor_id="lead")
            self.assertFalse(response["ok"])
            self.assertEqual(response["error"]["code"], "session_not_found")

    async def test_task_conflict_maps_to_409_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = ExecutionService(
                repo_root=make_repo(Path(tmp) / "repo"),
                sessions=SessionManager(),
                leader_id="lead",
            )
            task = make_task(task_id="t-conflict")
            api = ExecutionAPI(service)
            first = await api.run({
                "project_id": "p1",
                "actor_id": "u1",
                "adapter": MockAdapter(),
                "task": {
                    "task_id": task.task_id,
                    "owner_id": task.owner_id,
                    "allowed_paths": list(task.allowed_paths),
                },
            })
            second = await api.run({
                "project_id": "p2",
                "actor_id": "u1",
                "adapter": MockAdapter(),
                "task": {
                    "task_id": task.task_id,
                    "owner_id": task.owner_id,
                    "allowed_paths": list(task.allowed_paths),
                },
            })
            self.assertTrue(first["ok"])
            self.assertFalse(second["ok"])
            self.assertEqual(second["error"]["code"], "task_conflict")

    async def test_non_owner_cannot_operate_task(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = ExecutionService(
                repo_root=make_repo(Path(tmp) / "repo"),
                sessions=SessionManager(),
                leader_id="lead",
            )
            await service.run(
                "p1",
                make_task(),
                actor_id="u1",
                adapter=MockAdapter(),
                context={"write_files": {"src/app.py": "x = 1\n"}},
            )
            response = await ExecutionAPI(service).status("t1", actor_id="intruder")
            self.assertFalse(response["ok"])
            self.assertEqual(response["error"]["code"], "permission_denied")

    async def test_empty_commit_message_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = ExecutionService(
                repo_root=make_repo(Path(tmp) / "repo"),
                sessions=SessionManager(),
                leader_id="lead",
            )
            task = make_task()
            await service.run(
                "p1",
                task,
                actor_id="u1",
                adapter=MockAdapter(),
                context={"write_files": {"src/app.py": "x = 1\n"}},
            )
            api = ExecutionAPI(service)
            response = await api.commit("t1", "u1", "   ")
            self.assertFalse(response["ok"])
            self.assertEqual(response["error"]["code"], "git_error")


class GitWorkspaceTests(unittest.IsolatedAsyncioTestCase):
    async def test_invalid_task_id_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_repo(Path(tmp) / "repo")
            for task_id in (".", "..", ".hidden", "task."):
                with self.assertRaises(WorkspaceError):
                    create_workspace("p1", task_id, repo)

    async def test_same_task_id_in_different_projects_uses_separate_worktrees(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_repo(Path(tmp) / "repo")
            first = create_workspace("p1", "t-shared", repo)
            second = create_workspace("p2", "t-shared", repo)
            self.assertNotEqual(first.worktree_path, second.worktree_path)
            self.assertNotEqual(first.branch_name, second.branch_name)

    async def test_invalid_base_branch_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_repo(Path(tmp) / "repo")
            with self.assertRaises(WorkspaceError):
                create_workspace("p1", "t-branch", repo, base_branch="--help")


class GitParsingTests(unittest.IsolatedAsyncioTestCase):
    async def test_unusual_filename_is_collected(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_repo(Path(tmp) / "repo")
            workspace = create_workspace("p1", "t-weird", repo)
            name = 'weird "name" with space.txt'
            (workspace.worktree_path / name).write_text("ok\n", encoding="utf-8")
            changes = collect_changes(workspace.worktree_path)
            self.assertIn(name, changes.files)
            commit_hash = commit_changes(workspace, (name,), "weird filename")
            self.assertTrue(commit_hash)


class CLIAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_cli_timeout_marks_failed(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            adapter = CLIAdapter(
                CLIAdapterConfig(
                    command=(sys.executable, "-c", "import time; time.sleep(1)"),
                    prompt_mode="stdin",
                    timeout=0.05,
                )
            )
            info = await adapter.start_session(make_task(), workspace, {})
            with self.assertRaises(AdapterError):
                await adapter.send_task(info.session_id, "prompt")
            self.assertEqual(await adapter.get_status(info.session_id), AgentStatus.FAILED)

    async def test_cli_adapter_runs_without_shell(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_repo(Path(tmp) / "repo")
            script = (
                "import pathlib, sys; "
                "pathlib.Path('output.txt').write_text(pathlib.Path(sys.argv[1]).read_text())"
            )
            adapter = CLIAdapter(
                CLIAdapterConfig(
                    command=(sys.executable, "-c", script, "{prompt_file}"),
                    prompt_mode="file",
                    timeout=5,
                )
            )
            task = make_task()
            info = await adapter.start_session(task, repo, {})
            await adapter.send_task(info.session_id, "hello from prompt")
            self.assertEqual(await adapter.get_status(info.session_id), AgentStatus.SUCCEEDED)
            self.assertEqual((repo / "output.txt").read_text(encoding="utf-8"), "hello from prompt")
            changes = await adapter.get_changes(info.session_id)
            self.assertIn("output.txt", changes.files)
            logs = [log async for log in adapter.stream_logs(info.session_id)]
            self.assertTrue(logs)


if __name__ == "__main__":
    unittest.main()
