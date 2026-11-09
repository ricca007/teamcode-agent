"""Git branch/worktree isolation utilities.

All Git commands use argument arrays and ``shell=False`` semantics. The module
never pushes to a remote and never changes global Git configuration.
"""

from __future__ import annotations

import re
import subprocess
from collections.abc import Sequence
from pathlib import Path, PurePosixPath

from app.schemas.core import ChangeSet, GitWorkspace

from ..errors import PermissionDeniedError, WorkspaceError
from ..security.path_policy import validate_paths

_SAFE_ID = re.compile(r"^[A-Za-z0-9._-]+$")


def _run_git(repo: Path, *args: str, check: bool = True) -> str:
    command = ["git", *args]
    try:
        result = subprocess.run(
            command,
            cwd=str(repo),
            text=True,
            errors="replace",
            capture_output=True,
            check=False,
        )
    except OSError as exc:
        raise WorkspaceError(f"unable to execute git: {exc}") from exc
    if check and result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip() or "git command failed"
        raise WorkspaceError(message)
    return result.stdout


def _validate_id(value: str, label: str) -> str:
    if (
        not _SAFE_ID.fullmatch(value)
        or value in {".", ".."}
        or value.startswith(".")
        or value.endswith(".")
    ):
        raise WorkspaceError(
            f"{label} must match [A-Za-z0-9._-]+ and not start/end with ."
        )
    return value


def _validate_branch(value: str, label: str) -> str:
    value = str(value)
    if (
        not value
        or value.startswith("-")
        or value.startswith("/")
        or value.endswith("/")
        or value.endswith(".lock")
        or value.endswith(".")
        or value.startswith(".")
        or ".." in value
        or "@{" in value
        or any(ord(char) < 32 or char in " ~^:?*[\"" for char in value)
    ):
        raise WorkspaceError(f"invalid {label}: {value}")
    return value


def _git_root(repo: Path) -> Path:
    repo = Path(repo).resolve()
    output = _run_git(repo, "rev-parse", "--show-toplevel")
    root = Path(output.strip()).resolve()
    if not root.exists():
        raise WorkspaceError("git root does not exist")
    return root


def _registered_worktrees(root: Path) -> list[Path]:
    output = _run_git(root, "worktree", "list", "--porcelain")
    paths: list[Path] = []
    for line in output.splitlines():
        if line.startswith("worktree "):
            paths.append(Path(line[len("worktree "):]).resolve())
    return paths


def _branch_exists(root: Path, branch: str) -> bool:
    return (
        subprocess.run(
            ["git", "show-ref", "--verify", "--quiet", f"refs/heads/{branch}"],
            cwd=str(root),
            check=False,
        ).returncode
        == 0
    )


def create_workspace(
    project_id: str,
    task_id: str,
    repo_root: Path,
    base_branch: str = "main",
    worktrees_root: Path | None = None,
) -> GitWorkspace:
    """Create one task branch and one detached Git worktree."""

    project_id = _validate_id(str(project_id), "project_id")
    task_id = _validate_id(str(task_id), "task_id")
    base_branch = _validate_branch(base_branch, "base_branch")
    root = _git_root(Path(repo_root))
    if not _branch_exists(root, base_branch):
        raise WorkspaceError(f"base branch does not exist: {base_branch}")

    branch_name = f"teamcode/{project_id}/{task_id}"
    if not _branch_exists(root, branch_name):
        _run_git(root, "branch", branch_name, base_branch)

    parent = Path(worktrees_root).resolve() if worktrees_root else root / ".teamcode" / "worktrees"
    worktree_path = parent / project_id / task_id
    if worktree_path.exists():
        if worktree_path.resolve() not in _registered_worktrees(root):
            raise WorkspaceError("worktree path already exists but is not registered")
    else:
        try:
            worktree_path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise WorkspaceError(f"unable to create worktree parent: {exc}") from exc
        _run_git(root, "worktree", "add", str(worktree_path), branch_name)

    return GitWorkspace(
        project_id=project_id,
        task_id=task_id,
        root=root,
        worktree_path=worktree_path.resolve(),
        branch_name=branch_name,
        base_branch=base_branch,
    )


def _split_z(value: str) -> list[str]:
    return [item for item in value.split("\x00") if item]


def collect_changes(worktree_path: Path) -> ChangeSet:
    root = _git_root(Path(worktree_path))
    head = _run_git(root, "rev-parse", "--verify", "HEAD", check=False).strip()
    if head:
        changed = _split_z(_run_git(root, "diff", "--name-only", "HEAD", "-z"))
        diff = _run_git(root, "diff", "HEAD")
    else:
        # Support a newly initialized repository before the first commit.
        changed = _split_z(_run_git(root, "diff", "--cached", "--name-only", "-z"))
        diff = _run_git(root, "diff", "--cached")
    untracked = _split_z(
        _run_git(root, "ls-files", "--others", "--exclude-standard", "-z")
    )

    def keep(path: str) -> bool:
        normalized = path.replace("\\", "/").rstrip("/")
        parts = PurePosixPath(normalized).parts
        return not any(part in {".git", ".teamcode"} for part in parts)

    changed = [path for path in changed if keep(path)]
    untracked = [path for path in untracked if keep(path)]

    for path in untracked:
        target = root / path
        try:
            body = target.read_text(encoding="utf-8", errors="replace")
        except OSError:
            body = ""
        diff += "diff --git a/{0} b/{0}\n--- /dev/null\n+++ b/{0}\n{1}\n".format(
            path,
            "".join(f"+{line}\n" for line in body.splitlines()),
        )

    commit_hash = head or None
    return ChangeSet.from_values(files=changed + untracked, diff=diff, commit_hash=commit_hash)

def _validate_identity(value: str, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise WorkspaceError(f"{label} must be a non-empty string")
    if any(char in value for char in "\x00\r\n"):
        raise WorkspaceError(f"{label} contains control characters")
    return value


def commit_changes(
    workspace: GitWorkspace,
    allowed_paths: Sequence[str],
    message: str,
    author_name: str = "TeamCode Agent",
    author_email: str = "teamcode@localhost",
) -> str:
    """Stage and commit only files allowed by the task policy.

    This is the B-3 commit gate: an unauthorized change is rejected before any
    commit object is created.
    """

    if not isinstance(message, str) or not message.strip():
        raise WorkspaceError("commit message must not be empty")
    author_name = _validate_identity(author_name, "author_name")
    author_email = _validate_identity(author_email, "author_email")
    changes = collect_changes(workspace.worktree_path)
    validation = validate_paths(workspace.worktree_path, changes.files, allowed_paths)
    if validation.rejected:
        details = "; ".join(f"{path}: {reason}" for path, reason in validation.rejected)
        raise PermissionDeniedError(f"unauthorized changes: {details}")
    if not changes.files:
        raise WorkspaceError("no changes to commit")

    root = _git_root(workspace.worktree_path)
    # Stage only the paths reported by collect_changes. This avoids
    # accidentally committing unrelated pre-staged files or internal metadata.
    _run_git(root, "add", "-A", "--", *changes.files)
    staged = _split_z(_run_git(root, "diff", "--cached", "--name-only", "-z"))
    staged_validation = validate_paths(root, staged, allowed_paths)
    if staged_validation.rejected:
        _run_git(root, "reset", "--", *changes.files)
        details = "; ".join(f"{path}: {reason}" for path, reason in staged_validation.rejected)
        raise PermissionDeniedError(f"unauthorized staged changes: {details}")
    try:
        # Pass identity only for this command; never modify global Git config.
        _run_git(
            root,
            "-c",
            f"user.name={author_name}",
            "-c",
            f"user.email={author_email}",
            "commit",
            "-m",
            message,
        )
    except WorkspaceError:
        _run_git(root, "reset", "--", *changes.files)
        raise
    return _run_git(root, "rev-parse", "HEAD").strip()


def get_commits(worktree_path: Path, limit: int = 20) -> list[str]:
    root = _git_root(Path(worktree_path))
    output = _run_git(root, "log", "-n", str(limit), "--pretty=format:%H%x09%s")
    return [line for line in output.splitlines() if line]


def prepare_pr_metadata(
    workspace: GitWorkspace,
    title: str | None = None,
    body: str = "",
) -> dict:
    return {
        "title": title or f"TeamCode task {workspace.task_id}",
        "head": workspace.branch_name,
        "base": workspace.base_branch,
        "body": body,
        "task_id": workspace.task_id,
        "project_id": workspace.project_id,
    }


def cleanup_workspace(workspace: GitWorkspace, delete_branch: bool = False) -> None:
    root = workspace.root
    path = workspace.worktree_path
    if path.exists():
        _run_git(root, "worktree", "remove", "--force", str(path))
    _run_git(root, "worktree", "prune")
    if delete_branch:
        _run_git(root, "branch", "-D", workspace.branch_name)
    parent = path.parent
    try:
        if parent.exists() and not any(parent.iterdir()):
            parent.rmdir()
    except OSError:
        pass
