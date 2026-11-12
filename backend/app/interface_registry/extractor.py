"""C-1：Python AST 接口提取器。

职责边界（解耦要点）：
- 本模块只做「静态代码 -> InterfaceInfo」的客观提取，不访问数据库、
  不依赖 FastAPI、不调用 LLM；
- 增量缓存通过 ``HashCache`` 注入，提取器本身不关心缓存放哪里；
- 输出顺序固定为 (module, lineno, name)，保证 Markdown 可比对。

支持范围：
- 普通函数 / async 函数 / 类 / 方法 / 嵌套函数
- 位置参数、仅位置参数、仅关键字参数、*args、**kwargs、默认值
- 字符串注解、``from __future__ import annotations``
- 装饰器、docstring、语法错误文件跳过并记录 warning
"""

from __future__ import annotations

import ast
import hashlib
import os
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

from app.interface_registry.cache import HashCache
from app.interface_registry.ids import make_interface_id
from app.interface_registry.schemas import InterfaceInfo, ParamInfo

# 默认跳过的目录：虚拟环境、依赖、运行时数据、缓存
EXCLUDED_DIRS: frozenset[str] = frozenset(
    {
        ".venv",
        "venv",
        ".git",
        "node_modules",
        "dist",
        "build",
        "__pycache__",
        ".teamcode",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".idea",
        ".vscode",
    }
)


class ExtractionError(Exception):
    """单个文件无法解析时抛出。"""


@dataclass(slots=True)
class ExtractedInterface:
    """提取器的内部结果，比对外契约多出展示字段。"""

    name: str
    kind: str
    module: str
    file_path: str
    params: list[ParamInfo]
    returns: str | None
    docstring: str | None
    lineno: int
    decorators: list[str] = field(default_factory=list)
    is_async: bool = False
    dependencies: list[str] = field(default_factory=list)

    def to_interface_info(
        self,
        project_id: str,
        *,
        version: int = 0,
        commit_hash: str | None = None,
        dependencies: list[str] | None = None,
    ) -> InterfaceInfo:
        """转换为对外契约模型。"""
        return InterfaceInfo(
            interface_id=make_interface_id(project_id, self.file_path, self.name, self.kind),
            project_id=project_id,
            module=self.module,
            file_path=self.file_path,
            name=self.name,
            kind=self.kind,  # type: ignore[arg-type]
            params=self.params,
            returns=self.returns,
            docstring=self.docstring,
            version=version,
            commit_hash=commit_hash,
            dependencies=self.dependencies if dependencies is None else dependencies,
            lineno=self.lineno,
            decorators=self.decorators,
            is_async=self.is_async,
        )


@dataclass(slots=True)
class ExtractionResult:
    """一次扫描的完整结果。"""

    interfaces: list[InterfaceInfo]
    warnings: list[dict]
    file_hashes: dict[str, str]
    scanned_files: list[str]
    skipped_files: list[str]
    removed_files: list[str]


# ---------------------------------------------------------------------------
# 文件遍历与哈希
# ---------------------------------------------------------------------------


def iter_python_files(
    root: str | Path,
    *,
    include_tests: bool = False,
    extra_excludes: set[str] | frozenset[str] | None = None,
) -> Iterator[Path]:
    """稳定顺序遍历项目内的 .py 文件。"""
    root = Path(root).resolve()
    excluded = set(EXCLUDED_DIRS)
    if extra_excludes:
        excluded |= set(extra_excludes)

    for dirpath, dirnames, filenames in os.walk(root):
        # 原地排序 + 过滤，保证遍历顺序稳定
        dirnames[:] = sorted(d for d in dirnames if d not in excluded)
        if not include_tests and "tests" in dirnames:
            dirnames.remove("tests")

        for filename in sorted(filenames):
            if not filename.endswith(".py"):
                continue
            if not include_tests and (filename.startswith("test_") or filename == "conftest.py"):
                continue
            yield Path(dirpath) / filename


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def module_name_for(rel_path: Path) -> str:
    """把相对路径转换为点号模块名，例如 app/models/user.py -> app.models.user。"""
    parts = list(rel_path.with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


# ---------------------------------------------------------------------------
# AST 提取
# ---------------------------------------------------------------------------


def _annotation_to_str(node: ast.expr | None) -> str | None:
    if node is None:
        return None
    # 显式字符串注解：x: "int" -> int（去掉引号，保留内容）
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    try:
        return ast.unparse(node)
    except Exception:  # pragma: no cover - ast.unparse 极少失败
        return None


def _default_to_str(node: ast.expr | None) -> str | None:
    if node is None:
        return None
    try:
        return ast.unparse(node)
    except Exception:  # pragma: no cover
        return None


def _build_params(node: ast.arguments, *, skip_receiver: bool = False) -> list[ParamInfo]:
    """把 ast.arguments 转换为参数列表。

    ``skip_receiver`` 只跳过名为 self/cls 的第一个参数，避免误伤 staticmethod。
    注意：``node.defaults`` 对齐的是 posonlyargs + args 合并后的末尾 N 个参数。
    """
    params: list[ParamInfo] = []

    positional = list(node.posonlyargs) + list(node.args)
    defaults = list(node.defaults)
    offset = len(positional) - len(defaults)

    for index, arg in enumerate(positional):
        if skip_receiver and index == 0 and arg.arg in {"self", "cls"}:
            continue
        default = defaults[index - offset] if index >= offset else None
        params.append(
            ParamInfo(
                name=arg.arg,
                annotation=_annotation_to_str(arg.annotation),
                default=_default_to_str(default),
                kind="positional_only"
                if index < len(node.posonlyargs)
                else "positional_or_keyword",
            )
        )

    if node.vararg is not None:
        params.append(
            ParamInfo(
                name=f"*{node.vararg.arg}",
                annotation=_annotation_to_str(node.vararg.annotation),
                kind="var_positional",
            )
        )

    for arg, default in zip(node.kwonlyargs, node.kw_defaults, strict=False):
        params.append(
            ParamInfo(
                name=arg.arg,
                annotation=_annotation_to_str(arg.annotation),
                default=_default_to_str(default),
                kind="keyword_only",
            )
        )

    if node.kwarg is not None:
        params.append(
            ParamInfo(
                name=f"**{node.kwarg.arg}",
                annotation=_annotation_to_str(node.kwarg.annotation),
                kind="var_keyword",
            )
        )

    return params


def _class_init_params(node: ast.ClassDef) -> list[ParamInfo]:
    """类接口用 __init__ 的签名表达，方便其他成员按契约构造对象。"""
    for item in node.body:
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == "__init__":
            return _build_params(item.args, skip_receiver=True)
    return []


class _InterfaceVisitor(ast.NodeVisitor):
    """按作用域栈记录限定名与类型（function / method / class）。"""

    def __init__(self, module: str, rel_path: str, imports: dict[str, str] | None = None):
        self.module = module
        self.rel_path = rel_path
        # 栈元素：(名称, 作用域种类)
        self._stack: list[tuple[str, str]] = []
        self.items: list[ExtractedInterface] = []
        self.imports = imports or {}

    def _dependencies(self, node: ast.AST) -> list[str]:
        dependencies = set()
        for call in ast.walk(node):
            if not isinstance(call, ast.Call):
                continue
            name = ast.unparse(call.func)
            root, _, suffix = name.partition(".")
            if root in self.imports:
                dependencies.add(self.imports[root] + ("." + suffix if suffix else ""))
        return sorted(dependencies)

    def _qualified_name(self, name: str) -> str:
        return ".".join([entry[0] for entry in self._stack] + [name])

    def _kind_for(self, scope_kind: str | None) -> str:
        return "method" if scope_kind == "class" else "function"

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.items.append(
            ExtractedInterface(
                name=self._qualified_name(node.name),
                kind="class",
                module=self.module,
                file_path=self.rel_path,
                params=_class_init_params(node),
                returns=None,
                docstring=ast.get_docstring(node, clean=True),
                lineno=node.lineno,
                decorators=[_default_to_str(d) or "" for d in node.decorator_list],
                is_async=False,
                dependencies=self._dependencies(node),
            )
        )
        self._stack.append((node.name, "class"))
        self.generic_visit(node)
        self._stack.pop()

    def _visit_function(
        self, node: ast.FunctionDef | ast.AsyncFunctionDef, *, is_async: bool
    ) -> None:
        scope_kind = self._stack[-1][1] if self._stack else None

        # 类条目已经用 __init__ 的签名表达构造参数，不再重复注册该方法
        if node.name == "__init__" and scope_kind == "class":
            return

        self.items.append(
            ExtractedInterface(
                name=self._qualified_name(node.name),
                kind=self._kind_for(scope_kind),
                module=self.module,
                file_path=self.rel_path,
                params=_build_params(
                    node.args,
                    skip_receiver=(
                        scope_kind == "class"
                        and not any(
                            isinstance(d, ast.Name) and d.id == "staticmethod"
                            for d in node.decorator_list
                        )
                    ),
                ),
                returns=_annotation_to_str(node.returns),
                docstring=ast.get_docstring(node, clean=True),
                lineno=node.lineno,
                decorators=[_default_to_str(d) or "" for d in node.decorator_list],
                is_async=is_async,
                dependencies=self._dependencies(node),
            )
        )
        self._stack.append((node.name, "function"))
        self.generic_visit(node)
        self._stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node, is_async=False)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node, is_async=True)


def extract_file(path: str | Path, project_root: str | Path) -> list[ExtractedInterface]:
    """提取单个文件。解析失败时抛出 ExtractionError。"""
    path = Path(path)
    root = Path(project_root).resolve()

    try:
        rel_path = path.resolve().relative_to(root)
    except ValueError as exc:
        raise ExtractionError(f"文件不在项目根目录内: {path}") from exc

    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
    except (SyntaxError, UnicodeDecodeError, ValueError) as exc:
        raise ExtractionError(f"{rel_path.as_posix()}: {exc}") from exc

    imports = {}
    package = module_name_for(rel_path.parent / "__init__.py")
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports[alias.asname or alias.name.split(".")[0]] = (
                    alias.name if alias.asname else alias.name.split(".")[0]
                )
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                prefix = package.split(".")[: len(package.split(".")) - node.level + 1]
                base = ".".join([*prefix, base]).strip(".")
            for alias in node.names:
                if alias.name != "*":
                    imports[alias.asname or alias.name] = f"{base}.{alias.name}".strip(".")
    visitor = _InterfaceVisitor(
        module=module_name_for(rel_path),
        rel_path=rel_path.as_posix(),
        imports=imports,
    )
    visitor.visit(tree)
    # 类内部会重复访问方法：visitor 已经按栈去重，无需额外处理
    return visitor.items


# ---------------------------------------------------------------------------
# 项目级扫描
# ---------------------------------------------------------------------------


def extract_project(
    project_root: str | Path,
    project_id: str,
    *,
    include_tests: bool = False,
    extra_excludes: set[str] | frozenset[str] | None = None,
    hash_cache: HashCache | None = None,
) -> ExtractionResult:
    """扫描整个项目。

    传入 ``hash_cache`` 时启用增量扫描：文件 sha256 未变则跳过解析，
    但文件仍然会出现在 ``file_hashes`` 中，用于检测被删除的文件。
    """
    root = Path(project_root).resolve()
    if not root.exists():
        raise ExtractionError(f"项目根目录不存在: {root}")

    cache_keys_before = set(hash_cache.keys()) if hash_cache is not None else set()

    interfaces: list[InterfaceInfo] = []
    warnings: list[dict] = []
    file_hashes: dict[str, str] = {}
    scanned_files: list[str] = []
    skipped_files: list[str] = []

    for path in iter_python_files(root, include_tests=include_tests, extra_excludes=extra_excludes):
        rel = path.resolve().relative_to(root).as_posix()
        # 提取格式升级后重新解析旧缓存，避免旧记录永久缺少参数 kind。
        digest = f"signature-v3:{sha256_file(path)}"
        file_hashes[rel] = digest

        if hash_cache is not None and hash_cache.get(rel) == digest:
            skipped_files.append(rel)
            continue

        try:
            items = extract_file(path, root)
        except ExtractionError as exc:
            # 语法错误不中断整体扫描；同时缓存该文件哈希，避免每次重复报错
            warnings.append({"file": rel, "error": str(exc)})
            if hash_cache is not None:
                hash_cache.set(rel, digest)
            continue

        interfaces.extend(item.to_interface_info(project_id) for item in items)
        scanned_files.append(rel)
        if hash_cache is not None:
            hash_cache.set(rel, digest)

    removed_files: list[str] = []
    if hash_cache is not None:
        removed_files = sorted(cache_keys_before - set(file_hashes))
        for rel in removed_files:
            hash_cache.remove(rel)

    # 稳定的输出顺序，保证 Markdown 可比对
    interfaces.sort(key=lambda i: (i.module, i.lineno or 0, i.name, i.kind))

    return ExtractionResult(
        interfaces=interfaces,
        warnings=warnings,
        file_hashes=file_hashes,
        scanned_files=sorted(scanned_files),
        skipped_files=sorted(skipped_files),
        removed_files=removed_files,
    )
