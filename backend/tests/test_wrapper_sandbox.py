"""Claude wrapper 跨平台沙箱决策的单元测试（P2-2）。

通过 importlib 直接加载 ``scripts/claude_stream_wrapper.py``，不启动 claude。
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
WRAPPER = REPO_ROOT / "scripts" / "claude_stream_wrapper.py"


def _load_wrapper():
    spec = importlib.util.spec_from_file_location("claude_stream_wrapper", WRAPPER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # dataclass 解析 ``from __future__ import annotations`` 时需要能查到模块。
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


wrapper = _load_wrapper()


def test_no_sandbox_flag_disables():
    decision = wrapper._sandbox_decision("darwin", True, None, True)
    assert decision.mode == "disabled"
    assert not decision.fatal


def test_env_zero_disables():
    decision = wrapper._sandbox_decision("darwin", False, "0", True)
    assert decision.mode == "disabled"
    assert not decision.fatal


def test_macos_default_enables_sandbox():
    decision = wrapper._sandbox_decision("darwin", False, None, True)
    assert decision.mode == "sandbox"
    assert decision.level == "info"


def test_macos_without_sandbox_exec_warns():
    decision = wrapper._sandbox_decision("darwin", False, None, False)
    assert decision.mode == "disabled"
    assert decision.level == "warn"


def test_linux_default_warns_and_continues():
    decision = wrapper._sandbox_decision("linux", False, None, False)
    assert decision.mode == "disabled"
    assert decision.level == "warn"
    assert not decision.fatal


def test_explicit_on_linux_fails_closed():
    decision = wrapper._sandbox_decision("linux", False, "1", False)
    assert decision.mode == "disabled"
    assert decision.fatal


def test_explicit_on_macos_without_exec_fails_closed():
    decision = wrapper._sandbox_decision("darwin", False, "1", False)
    assert decision.fatal


def test_explicit_on_macos_with_exec_enables():
    decision = wrapper._sandbox_decision("darwin", False, "1", True)
    assert decision.mode == "sandbox"
    assert not decision.fatal
