"""Shadowing-safe accessor for the middleware `gateway.write_gate` module.

Mirrors harnesses/j1_access.py: inside a real Hermes process the middleware
repo's `gateway` package is imported under the private alias `__j1mw_gateway`
(see j1_access.register_gateway_alias), so a bare
``from gateway.write_gate import ...`` would resolve against hermes-agent's own
top-level `gateway` package and raise ModuleNotFoundError. This accessor
returns the write_gate module through the same alias, falling back to the
middleware repo path for standalone runs. Never raises.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_REPO = Path(r"C:\Users\mandu\hermes-made\jev-memory-middleware")
_ALIAS = "__j1mw_gateway"


def write_gate():
    """Return the middleware's gateway.write_gate module. Never (intentionally) raises."""
    alias = sys.modules.get(_ALIAS)
    if alias is not None:
        full = f"{_ALIAS}.write_gate"
        cached = sys.modules.get(full)
        if cached is not None:
            return cached
        from importlib.machinery import PathFinder

        spec = PathFinder.find_spec("write_gate", list(alias.__path__))
        if spec is not None:
            from importlib.util import module_from_spec

            mod = module_from_spec(spec)
            sys.modules[full] = mod
            assert spec.loader is not None
            spec.loader.exec_module(mod)
            return mod
    # alias absent (standalone venv): load straight from the middleware repo.
    spec = importlib.util.spec_from_file_location(
        "jev_write_gate_direct", _REPO / "gateway" / "write_gate.py"
    )
    if spec and spec.loader:
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        sys.modules["jev_write_gate_direct"] = m
        return m
    # final fallback: bare import (standalone venv without any shadow).
    try:
        import gateway.write_gate as m

        return m
    except Exception:
        return None