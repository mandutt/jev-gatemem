"""Jev-reranked Mnemosyne memory provider — Hermes plugin wrapper.

Installed (by harnesses/install_plugin.py) into $HERMES_HOME/plugins/jev-mem/.
Discovery contract (Hermes plugins/memory):
  - module exposes `register_memory_provider(ctx)` (or a MemoryProvider
    subclass); the loader imports the package and calls register.
  - Bundled providers win over user dirs; this is user-dir so it only loads
    when no bundled provider named 'jev-mem' exists (it never does).

This wrapper keeps the middleware repo as the single source of truth: it
inserts the middleware repo path into sys.path and imports the harness.
If the middleware repo is missing or the import fails, the plugin fails to
load and Hermes keeps the plain Mnemosyne provider — memory never breaks.
"""
from __future__ import annotations

import sys
from pathlib import Path

_MIDDLEWARE_REPO = Path(r"C:\Users\mandu\hermes-made\jev-memory-middleware")
if str(_MIDDLEWARE_REPO) not in sys.path:
    sys.path.insert(0, str(_MIDDLEWARE_REPO))


def register_memory_provider(ctx):
    """Hermes memory-provider discovery entry (same contract as mnemosyne_hermes).

    P5: JEV_MEM_MODE에 따라 rpc(JevRpcProvider, 기본) / embedded(JevRerankProvider) 분기.
    """
    from harnesses.hermes_j1 import _make_provider

    provider = _make_provider()
    ctx.register_memory_provider(provider)


# The dir loader's fallback path (`_instantiate_subclass`) scans module attrs
# for a MemoryProvider subclass. Only JevRpcProvider is exposed here: dir() is
# alphabetical, so exporting both made the fallback silently pick JevRerank
# (embedded mode) whenever register() failed — a silent mode downgrade.
# Keep the embedded class importable from harnesses.hermes_j1 for manual
# rollback, but never as a module attribute of this plugin package.
from harnesses.hermes_j1 import JevRpcProvider as JevRpcProvider  # noqa: E402,F401