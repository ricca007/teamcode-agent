"""C-1 验收测试：AST 提取的字段准确性与增量扫描。"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.interface_registry.cache import HashCache
from app.interface_registry.extractor import (
    ExtractionError,
    extract_file,
    extract_project,
)


def _by_name(interfaces):
    return {item.name: item for item in interfaces}


def test_basic_function_fields(sample_project: Path):
    result = extract_project(sample_project, "p_test")
    names = _by_name(result.interfaces)

    fn = names["normalize_name"]
    assert fn.kind == "function"
    assert fn.module == "sample_pkg.user_service"
    assert fn.file_path == "sample_pkg/user_service.py"
    assert fn.returns == "str"
    assert fn.docstring == "规范化用户名。"
    assert fn.is_async is False

    params = {p.name: p for p in fn.params}
    assert params["value"].annotation == "str"
    assert params["value"].default is None
    # 关键字参数 + 默认值
    assert params["strip"].annotation == "bool"
    assert params["strip"].default == "True"


def test_varargs_and_kwargs(sample_project: Path):
    result = extract_project(sample_project, "p_test")
    fn = _by_name(result.interfaces)["collect_tags"]

    params = {p.name: p for p in fn.params}
    assert params["*tags"].annotation == "str"
    assert params["limit"].default == "10"
    assert params["**extra"].annotation == "str"


def test_class_method_async_nested_and_decorator(sample_project: Path):
    result = extract_project(sample_project, "p_test")
    names = _by_name(result.interfaces)

    service = names["UserService"]
    assert service.kind == "class"
    assert service.docstring == "用户服务。"
    init_params = {p.name: p for p in service.params}
    # 类接口用 __init__ 签名表达，且跳过 self
    assert set(init_params) == {"repo", "retries"}
    assert init_params["repo"].annotation == "UserRepository"
    assert init_params["retries"].default == "3"

    method = names["UserService.get_user"]
    assert method.kind == "method"
    assert method.decorators == ["cache"]
    assert method.returns == "dict | None"
    assert {p.name for p in method.params} == {"user_id", "include_deleted"}

    nested = names["UserService.get_user._inner"]
    assert nested.kind == "function"
    assert nested.name == "UserService.get_user._inner"
    assert nested.returns == "dict"

    async_method = names["UserService.fetch_remote"]
    assert async_method.is_async is True
    assert async_method.kind == "method"
    assert async_method.returns == "bytes"

    nested_class = names["UserService.Meta"]
    assert nested_class.kind == "class"


def test_syntax_error_is_skipped_with_warning(sample_project: Path):
    result = extract_project(sample_project, "p_test")

    assert any(w["file"] == "sample_pkg/broken.py" for w in result.warnings)
    # 其余文件照常提取，不因单个文件失败中断
    assert "normalize_name" in _by_name(result.interfaces)


def test_tests_dir_skipped_by_default(sample_project: Path):
    default_result = extract_project(sample_project, "p_test")
    assert "should_be_ignored" not in _by_name(default_result.interfaces)

    with_tests = extract_project(sample_project, "p_test", include_tests=True)
    assert "should_be_ignored" in _by_name(with_tests.interfaces)


def test_output_order_is_stable(sample_project: Path):
    first = extract_project(sample_project, "p_test")
    second = extract_project(sample_project, "p_test")
    assert [i.interface_id for i in first.interfaces] == [
        i.interface_id for i in second.interfaces
    ]
    keys = [(i.module, i.lineno or 0, i.name) for i in first.interfaces]
    assert keys == sorted(keys)


def test_incremental_scan_only_rescans_changed_files(sample_project: Path):
    cache = HashCache()

    first = extract_project(sample_project, "p_test", hash_cache=cache)
    assert "sample_pkg/user_service.py" in first.scanned_files
    assert len(cache) == len(first.file_hashes)

    second = extract_project(sample_project, "p_test", hash_cache=cache)
    assert second.scanned_files == []
    assert second.interfaces == []
    assert set(second.skipped_files) == set(first.file_hashes)

    target = sample_project / "sample_pkg" / "user_service.py"
    target.write_text(
        target.read_text(encoding="utf-8")
        + "\n\ndef added_by_test() -> None:\n    \"\"\"新增函数。\"\"\"\n    pass\n",
        encoding="utf-8",
    )

    third = extract_project(sample_project, "p_test", hash_cache=cache)
    assert third.scanned_files == ["sample_pkg/user_service.py"]
    assert "added_by_test" in _by_name(third.interfaces)


def test_removed_file_is_reported(sample_project: Path):
    cache = HashCache()
    extract_project(sample_project, "p_test", hash_cache=cache)

    (sample_project / "sample_pkg" / "broken.py").unlink()
    result = extract_project(sample_project, "p_test", hash_cache=cache)

    assert "sample_pkg/broken.py" in result.removed_files


def test_extract_file_outside_root_raises(sample_project: Path, tmp_path: Path):
    outside = tmp_path / "outside.py"
    outside.write_text("def f():\n    pass\n", encoding="utf-8")
    with pytest.raises(ExtractionError):
        extract_file(outside, sample_project)
