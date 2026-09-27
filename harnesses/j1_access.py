"""Safe accessor for gateway.j1_pipeline that survives module shadowing.

Why this exists
---------------
In a real Hermes process, `sys.path` begins with the hermes-agent root, which
contains its OWN top-level `gateway/` package (core gateway).  The J1 middleware
repo (C:\\Users\\mandu\\hermes-made\\jev-memory-middleware) is inserted LATER
in sys.path, so `import gateway` resolves to hermes-agent/gateway — which has
no `j1_pipeline` module.  An unconditional `from gateway.j1_pipeline import ...`
then raises ModuleNotFoundError and kills the J1 prefetch.

Hermes core is OFF-LIMITS (no vendoring, no sitecustomize, no .pth tricks).
Instead, this module makes the middleware's OWN gateway package importable
under a private alias and re-exports the J1 symbols through it:

    j1_pipeline() -> module   (idempotent; loads once)

Anything in the middleware repo (harness, plugin wrapper, probes/tests) that
needs the live J1 pipeline MUST go through this accessor — never via bare
`from gateway.j1_pipeline import ...`.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent  # .../jev-memory-middleware
_ALIAS = "__j1mw_gateway"  # private alias so the real gateway stays untouched


def _load_middleware_gateway():
    """Return the middleware repo's gateway package, whatever shadows it.

    The middleware gateway package is the ONLY one that has j1_pipeline;
    a pre-existing `gateway` entry in sys.modules is always the shadow
    (hermes-agent core) because the middleware repo never imports 'gateway'
    at module load time — it is only ever reached through this accessor.
    """
    cached = sys.modules.get("gateway")
    if cached is not None:
        # Shadow is already loaded somewhere (e.g. by the core).  Back it up,
        # remove it, load the middleware package, then restore the original.
        sys.modules.pop("gateway", None)
        try:
            repo = str(_REPO)
            # Ensure the middleware repo is ahead of everything while loading.
            for p in list(sys.path):
                if p == repo:
                    sys.path.remove(p)
            sys.path.insert(0, repo)
            gw = importlib.import_module("gateway")
            sys.modules[_ALIAS] = gw
            return gw
        finally:
            sys.modules["gateway"] = cached  # restore the shadow
    # No cached gateway: load the middleware package straight from its repo.
    repo = str(_REPO)
    for p in list(sys.path):
        if p == repo:
            sys.path.remove(p)
    sys.path.insert(0, repo)
    try:
        gw = importlib.import_module("gateway")
        sys.modules[_ALIAS] = gw
        return gw
    except BaseException:
        sys.modules.pop(_ALIAS, None)
        raise
    finally:
        sys.path.remove(repo)


def j1_pipeline():
    """Return the middleware's gateway.j1_pipeline module (cached in sys.modules)."""
    alias = sys.modules.get(_ALIAS)
    if alias is None:
        alias = _load_middleware_gateway()
    full = f"{_ALIAS}.j1_pipeline"
    cached = sys.modules.get(full)
    if cached is not None:
        return cached
    from importlib.machinery import PathFinder

    spec = PathFinder.find_spec("j1_pipeline", list(alias.__path__))
    if spec is None:
        raise ModuleNotFoundError(
            f"{full} not found under alias {_ALIAS} (path={list(alias.__path__)})"
        )
    from importlib.util import module_from_spec

    mod = module_from_spec(spec)
    sys.modules[full] = mod
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod