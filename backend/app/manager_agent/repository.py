import ast
from pathlib import Path

from app.schemas.planning import RepositoryModuleSnapshot, RepositorySnapshot

IGNORED_DIRECTORIES = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
    "venv",
}


def analyze_repository(repo_path: str, max_files: int = 500) -> RepositorySnapshot:
    root = Path(repo_path).expanduser().resolve()
    if not root.exists():
        raise FileNotFoundError(f"repository path does not exist: {root}")
    if not root.is_dir():
        raise NotADirectoryError(f"repository path is not a directory: {root}")

    modules: list[RepositoryModuleSnapshot] = []
    parse_errors: list[str] = []
    paths = sorted(path for path in root.rglob("*.py") if _is_source_path(path, root))
    truncated = len(paths) > max_files

    for path in paths[:max_files]:
        relative = path.relative_to(root)
        module = ".".join(relative.with_suffix("").parts)
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(relative))
        except (OSError, SyntaxError, UnicodeDecodeError) as exc:
            parse_errors.append(f"{relative.as_posix()}: {exc}")
            continue

        modules.append(
            RepositoryModuleSnapshot(
                module=module,
                file_path=relative.as_posix(),
                classes=sorted(node.name for node in tree.body if isinstance(node, ast.ClassDef)),
                functions=sorted(
                    node.name
                    for node in tree.body
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                ),
            )
        )

    return RepositorySnapshot(
        root_path=str(root),
        modules=modules,
        parse_errors=parse_errors,
        truncated=truncated,
    )


def _is_source_path(path: Path, root: Path) -> bool:
    relative = path.relative_to(root)
    return not any(
        part in IGNORED_DIRECTORIES or part.startswith(".") for part in relative.parts[:-1]
    )
