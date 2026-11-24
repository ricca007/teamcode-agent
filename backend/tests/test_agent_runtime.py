import asyncio
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from app.agent_runtime.cli_adapter import CLIAdapter, CLIAdapterConfig
from app.agent_runtime.mock_adapter import MockAdapter
from app.agent_runtime.session_manager import SessionManager
from app.errors import (
    AdapterError,
    InvalidStateTransitionError,
    PermissionDeniedError,
    WorkspaceError,
)
from app.git_ops.workspace import (
    cleanup_workspace,
    collect_changes,
    commit_changes,
    create_workspace,
)
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
            try:
                (root / "link").symlink_to(outside)
            except OSError as exc:
                self.skipTest(f"symlink creation unavailable on this platform: {exc}")

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

    def test_allowed_directory_and_glob_follow_filesystem_case(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = validate_paths(
                Path(tmp),
                ["SRC/app.py", "docs/api.md"],
                ["src", "docs/**"],
            )
            case_sensitive = os.path.normcase("A") != os.path.normcase("a")
            if case_sensitive:
                self.assertFalse(result.ok)
                self.assertEqual(
                    result.rejected,
                    (("SRC/app.py", "path is outside allowed_paths"),),
                )
            else:
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

    async def test_terminate_interrupts_running_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            adapter = MockAdapter(delay=0.3)
            manager = SessionManager()
            info = await manager.start_session("p1", make_task(), Path(tmp), adapter)
            running = asyncio.create_task(manager.send_task(info.session_id, "prompt"))
            await asyncio.sleep(0.05)
            status = await manager.terminate(info.session_id)
            self.assertEqual(status, AgentStatus.TERMINATED)
            await running
            self.assertEqual(
                manager.get_session(info.session_id).status,
                AgentStatus.TERMINATED,
            )

    async def test_pause_resume_reflects_adapter_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            adapter = MockAdapter()
            manager = SessionManager()
            info = await manager.start_session("p1", make_task(), Path(tmp), adapter)
            self.assertEqual(await manager.pause(info.session_id), AgentStatus.PAUSED)
            self.assertEqual(await manager.resume(info.session_id), AgentStatus.RUNNING)
class GitWorkspaceTests(unittest.IsolatedAsyncioTestCase):
    async def test_commit_gate_rejects_unauthorized_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_repo(Path(tmp) / "repo")
            workspace = create_workspace("p1", "t-commit", repo)
            (workspace.worktree_path / "src").mkdir()
            (workspace.worktree_path / "src" / "ok.py").write_text(
                "x = 1\n", encoding="utf-8"
            )
            (workspace.worktree_path / "bad.py").write_text(
                "y = 2\n", encoding="utf-8"
            )
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

    def test_validate_branch_name_is_public(self):
        from app.git_ops import validate_branch_name

        self.assertEqual(validate_branch_name("main", "base"), "main")
        self.assertEqual(validate_branch_name("feature/x-1", "base"), "feature/x-1")
        for invalid in ("", "--help", "a..b", "a.lock", "a@{b}", "a b"):
            with self.assertRaises(WorkspaceError):
                validate_branch_name(invalid, "base")

    async def test_cleanup_workspace_removes_path_and_branch(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_repo(Path(tmp) / "repo")
            workspace = create_workspace("p1", "t-cleanup", repo)
            self.assertTrue(workspace.worktree_path.exists())
            cleanup_workspace(workspace, delete_branch=True)
            self.assertFalse(workspace.worktree_path.exists())
            branch_check = subprocess.run(
                [
                    "git",
                    "show-ref",
                    "--verify",
                    "--quiet",
                    f"refs/heads/{workspace.branch_name}",
                ],
                cwd=str(repo),
                check=False,
            )
            self.assertNotEqual(branch_check.returncode, 0)

    async def test_commit_records_custom_author(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_repo(Path(tmp) / "repo")
            workspace = create_workspace("p1", "t-author", repo)
            (workspace.worktree_path / "src").mkdir()
            (workspace.worktree_path / "src" / "ok.py").write_text(
                "x = 1\n", encoding="utf-8"
            )
            commit_changes(
                workspace,
                ("src/**",),
                "custom author",
                author_name="Alice",
                author_email="alice@example.invalid",
            )
            author = run_git(
                workspace.worktree_path, "log", "-1", "--pretty=%an <%ae>"
            )
            self.assertEqual(author.strip(), "Alice <alice@example.invalid>")


class GitParsingTests(unittest.IsolatedAsyncioTestCase):
    async def test_unusual_filename_is_collected(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_repo(Path(tmp) / "repo")
            workspace = create_workspace("p1", "t-weird", repo)
            name = "weird (name) with space.txt"
            (workspace.worktree_path / name).write_text("ok\n", encoding="utf-8")
            changes = collect_changes(workspace.worktree_path)
            self.assertIn(name, changes.files)
            commit_hash = commit_changes(workspace, (name,), "weird filename")
            self.assertTrue(commit_hash)

    async def test_binary_untracked_file_body_is_omitted(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_repo(Path(tmp) / "repo")
            workspace = create_workspace("p1", "t-bin", repo)
            (workspace.worktree_path / "data.bin").write_bytes(b"\x00\x01\x02")
            changes = collect_changes(workspace.worktree_path)
            self.assertIn("data.bin", changes.files)
            self.assertIn("binary or large file omitted", changes.diff)


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

    async def test_cli_adapter_arg_mode_passes_prompt_as_argument(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_repo(Path(tmp) / "repo")
            script = (
                "import pathlib, sys; "
                "pathlib.Path('argv.txt').write_text(repr(sys.argv[1:]), encoding='utf-8')"
            )
            adapter = CLIAdapter(
                CLIAdapterConfig(
                    command=(sys.executable, "-c", script),
                    prompt_mode="arg",
                    timeout=5,
                )
            )
            info = await adapter.start_session(make_task(), repo, {})
            await adapter.send_task(info.session_id, "hello prompt")
            self.assertEqual(await adapter.get_status(info.session_id), AgentStatus.SUCCEEDED)
            self.assertEqual(
                (repo / "argv.txt").read_text(encoding="utf-8"),
                "['hello prompt']",
            )


if __name__ == "__main__":
    unittest.main()
