"""core — Hermes-independent engine layer of the JEV-Mnemosyne middleware.

This package must stay free of any Hermes-specific import (no
mnemosyne_hermes, no MemoryProvider, no plugin discovery). Adapters
(harnesses/, adapters/) inject agent-specific objects (beam, pipeline module)
into core's pure functions.
"""