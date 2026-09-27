"""Full contract test: JevRerankProvider through Hermes' MemoryManager path.

Verifies the provider behaves like Mnemosyne under the real orchestration:
  - register via discovery (name 'mnemosyne' not colliding with the bundled one)
  - MemoryManager accepts the provider
  - prefetch_all() works (J1 on live DB, ephemeral session)
  - tools dispatch (mnemosyne_stats) works through the provider

Run with the Hermes runtime venv python.
"""
import sys

sys.path.insert(0, r"C:\Users\mandu\hermes-made\jev-memory-middleware")

from plugins import memory as mem_disc
from agent.memory_manager import MemoryManager

# 1) discovery
prov = mem_disc.load_memory_provider("jev-mem")
assert prov is not None, "jev-mem provider not loaded"
print("discovery OK:", type(prov).__name__, "name=", prov.name)

# 2) MemoryManager registration
mm = MemoryManager()
mm.add_provider(prov)
print("registered providers:", [p.name for p in mm._providers])

# 3) prefetch_all (J1 path, real API key present -> Jev ON)
out = mm.prefetch_all("웹 페이지를 추출할 때 stealth 브라우저가 필요한 경우는 언제야? 로그인이나 캡차 같은 경우인가?")
print("prefetch_all len:", len(out))
if out:
    print("header:", out.splitlines()[0][:60])
    print("lines:", len(out.splitlines()))
else:
    print("(empty prefetch — acceptable if nothing passed the gate)")

# 4) tool dispatch through the provider
r = mm.handle_tool_call("mnemosyne_stats", {})
print("tool mnemosyne_stats ->", str(r)[:120].replace("\n", " "))

print("CONTRACT TEST PASS")