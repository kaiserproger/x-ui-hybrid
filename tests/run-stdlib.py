#!/usr/bin/env python3
"""Stdlib-only test runner.

Runs the subset of the test suite that does not depend on aiogram/aiohttp/pytest.
Useful in sandboxed environments where you can't `pip install` anything but you
still want a fast `assert all the pure-python stuff works` pass.

For the full suite (panel mock, bot wiring, asyncio):

    python3 -m venv .venv && source .venv/bin/activate
    pip install -r tests/requirements.txt
    python -m pytest tests -ra
"""

from __future__ import annotations

import importlib
import inspect
import os
import sys
import tempfile
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _install_pytest_stub() -> None:
    """If pytest isn't available, install a minimal stub so test modules import.

    The stub is just enough to keep `import pytest`, `@pytest.fixture`, and
    `pytest.raises` from blowing up at import time. The actual fixtures get
    handed to test functions by name in `_run_one` below.
    """
    try:
        import pytest  # noqa: F401
        return
    except ImportError:
        pass
    import types
    stub = types.ModuleType("pytest")

    def fixture(*args, **kwargs):
        # Either @pytest.fixture or @pytest.fixture()
        if len(args) == 1 and callable(args[0]):
            return args[0]
        def deco(fn):
            return fn
        return deco

    class _Raises:
        def __init__(self, exc): self.exc = exc
        def __enter__(self): return self
        def __exit__(self, et, ev, tb):
            if et is None or not issubclass(et, self.exc):
                raise AssertionError(f"expected {self.exc}, got {et}")
            return True

    def raises(exc): return _Raises(exc)

    class _Mark:
        def __getattr__(self, name):
            def deco(fn): return fn
            return deco

    stub.fixture = fixture
    stub.raises = raises
    stub.mark = _Mark()
    sys.modules["pytest"] = stub


_install_pytest_stub()


def _make_tmp() -> Path:
    return Path(tempfile.mkdtemp(prefix="x-ui-hybrid-test-"))


def _run_one(modname: str, testname: str, fn) -> tuple[str, str]:
    """Run one test function. Returns ('ok'|'fail', message)."""
    try:
        sig = inspect.signature(fn)
        kwargs = {}
        if "tmp_path" in sig.parameters:
            kwargs["tmp_path"] = _make_tmp()
        if "store" in sig.parameters:
            from bot.db import Store  # noqa: WPS433
            kwargs["store"] = Store(_make_tmp() / "bot.db")
        fn(**kwargs)
        return "ok", ""
    except Exception:
        return "fail", traceback.format_exc()


def collect(modname: str):
    mod = importlib.import_module(modname)
    return [(n, getattr(mod, n))
            for n in dir(mod)
            if n.startswith("test_") and callable(getattr(mod, n))]


def main() -> int:
    # Pure-stdlib modules from the test suite. test_panel needs aiohttp's
    # test server; skip it here (the full pytest run covers it).
    modules = [
        "tests.test_db",
        "tests.test_landing",
        "tests.test_bot_helpers",
    ]

    ok = fail = 0
    failures: list[tuple[str, str]] = []

    # Make `tests` importable.
    (ROOT / "tests" / "__init__.py").write_text("")

    for modname in modules:
        try:
            tests = collect(modname)
        except Exception as e:
            print(f"  SKIP {modname} (import error): {e}")
            continue
        for name, fn in tests:
            status, msg = _run_one(modname, name, fn)
            print(f"  {status:4} {modname}::{name}")
            if status == "ok":
                ok += 1
            else:
                fail += 1
                failures.append((f"{modname}::{name}", msg))

    print(f"\n{ok} passed, {fail} failed")
    if fail:
        print("\n--- failures ---")
        for n, tb in failures:
            print(f"\n{n}\n{tb}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
