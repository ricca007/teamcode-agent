"""Workspace path validation for allowed-paths enforcement."""

from __future__ import annotations

import fnmatch
import os
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath


@dataclass(frozen=True)
class PathValidationResult:
    allowed: tuple[str, ...]
    rejected: tuple[tuple[str, str], ...]

    @property
    def ok(self) -> bool:
        return not self.rejected


def _safe_relative(raw: str) -> tuple[str | None, str | None]:
    if not isinstance(raw, str) or not raw:
        return None, "path is empty"
    if "\x00" in raw:
        return None, "path contains NUL"
    windows_style = PureWindowsPath(raw)
    if (
        windows_style.is_absolute()
        or bool(windows_style.drive)
        or os.path.isabs(raw)
        or raw.startswith("/")
    ):
        return None, "absolute paths are not allowed"
    normalized = unicodedata.normalize("NFC", raw).replace("\\", "/")
    pure = PurePosixPath(normalized)
    if any(part == ".." for part in pure.parts):
        return None, "parent traversal is not allowed"
    if pure.is_absolute():
        return None, "absolute paths are not allowed"
    if any(part in {".git", ".teamcode"} for part in pure.parts):
        return None, "reserved project metadata path"
    return pure.as_posix(), None


def _matches(rel_path: str, pattern: str) -> bool:
    """Match a path pattern without letting ``*`` cross directory boundaries."""

    rel = rel_path.casefold().rstrip("/")
    candidate = pattern.casefold().rstrip("/")
    if "*" not in candidate and "?" not in candidate and "[" not in candidate:
        return rel == candidate or rel.startswith(candidate + "/")

    rel_parts = tuple(part for part in rel.split("/") if part)
    pattern_parts = tuple(part for part in candidate.split("/") if part)

    def match(rel_index: int, pattern_index: int) -> bool:
        if pattern_index == len(pattern_parts):
            return rel_index == len(rel_parts)
        pattern_part = pattern_parts[pattern_index]
        if pattern_part == "**":
            return match(rel_index, pattern_index + 1) or (
                rel_index < len(rel_parts) and match(rel_index + 1, pattern_index)
            )
        return (
            rel_index < len(rel_parts)
            and fnmatch.fnmatchcase(rel_parts[rel_index], pattern_part)
            and match(rel_index + 1, pattern_index + 1)
        )

    return match(0, 0)


def validate_allowed_paths(project_root: Path, allowed_paths: Iterable[str]) -> tuple[str, ...]:  # noqa: ARG001
    """Validate and normalize configured path patterns."""

    if isinstance(allowed_paths, str):
        allowed_paths = (allowed_paths,)
    elif allowed_paths is None:
        raise ValueError("allowed_paths must not be None")
    normalized: list[str] = []
    for raw in allowed_paths:
        value, error = _safe_relative(str(raw))
        if error or value is None:
            raise ValueError(f"invalid allowed path {raw!r}: {error}")
        normalized.append(value)
    if not normalized:
        raise ValueError("allowed_paths must not be empty")
    return tuple(sorted(set(normalized)))


def validate_paths(
    project_root: Path,
    files: Iterable[str],
    allowed_paths: Sequence[str],
) -> PathValidationResult:
    root = Path(project_root).resolve()
    if isinstance(files, str):
        files = (files,)
    patterns = validate_allowed_paths(root, allowed_paths)
    allowed: list[str] = []
    rejected: list[tuple[str, str]] = []

    for raw in files:
        value, error = _safe_relative(str(raw))
        if error or value is None:
            rejected.append((str(raw), error or "invalid path"))
            continue

        # Resolve the final path so symlink escapes are rejected even when the
        # symlink's textual path remains inside the project.
        candidate = root.joinpath(*PurePosixPath(value).parts)
        try:
            resolved = candidate.resolve(strict=False)
            resolved.relative_to(root)
        except (OSError, ValueError):
            rejected.append((value, "path escapes project root"))
            continue

        if not any(_matches(value, pattern) for pattern in patterns):
            rejected.append((value, "path is outside allowed_paths"))
            continue

        allowed.append(value)

    return PathValidationResult(
        allowed=tuple(sorted(set(allowed))),
        rejected=tuple(rejected),
    )
