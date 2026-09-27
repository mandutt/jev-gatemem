"""Install the Jev-rerank Hermes memory plugin into $HERMES_HOME/plugins/jev-mem/.

The plugin wrapper (harnesses/jev_mem_plugin/__init__.py) imports the
middleware repo at runtime; this script only copies the wrapper + manifest.

Usage:
  python harnesses/install_plugin.py [--hermes-home PATH] [--force]

It does NOT change memory.provider in config.yaml — the user keeps
provider: mnemosyne; the plugin enhances the same 'mnemosyne' provider name.
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
WRAPPER_SRC = REPO / "harnesses" / "jev_mem_plugin"
MANIFEST = """\
name: jev-mem
version: 0.1.0
description: "Jev (TypeSafe System One) reranked Mnemosyne prefetch — lane pool + J1 lift. Enhances the mnemosyne provider; falls back to plain Mnemosyne on any failure."
author: Hermes Agent
provides_tools: []
provides_hooks: []
dependencies: []
"""


def default_hermes_home() -> Path:
    env = os.environ.get("HERMES_HOME")
    if env:
        return Path(env)
    return Path.home() / "AppData" / "Local" / "hermes"  # Windows default


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hermes-home", default=None)
    ap.add_argument("--force", action="store_true", help="overwrite existing wrapper")
    args = ap.parse_args()

    home = Path(args.hermes_home) if args.hermes_home else default_hermes_home()
    dest = home / "plugins" / "jev-mem"
    if dest.exists() and not args.force:
        print(f"[install] {dest} already exists (use --force to overwrite)")
        return 1
    dest.mkdir(parents=True, exist_ok=True)

    # Copy the wrapper __init__.py
    src_init = WRAPPER_SRC / "__init__.py"
    if not src_init.exists():
        print(f"[install] wrapper not found: {src_init}")
        return 1
    shutil.copy2(src_init, dest / "__init__.py")

    # Write the manifest
    (dest / "plugin.yaml").write_text(MANIFEST, encoding="utf-8")

    print(f"[install] wrote plugin to {dest}")
    print("[install] memory.provider stays 'mnemosyne'; the plugin enhances it.")
    print("[install] NOTE: a NEW Hermes session must start for the plugin to load.")
    return 0


if __name__ == "__main__":
    sys.exit(main())