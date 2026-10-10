# -*- coding: utf-8 -*-
"""STEP 3 검증: 재백필 행의 임베딩(벡터) 커버리지 + prefetch 회수"""
import sqlite3, json, collections

HERMES_MEM = r"C:/Users/mandu/AppData/Local/hermes/mnemosyne/data/mnemosyne.db"
con = sqlite3.connect(HERMES_MEM)
con.row_factory = sqlite3.Row

rows = con.execute("""
    SELECT id, json_extract(metadata_json,'$.backfilled_at') bf
    FROM working_memory
    WHERE metadata_json LIKE '%backfill:%' AND bf LIKE '2026-10-11%'""").fetchall()
ids = [r["id"] for r in rows]
print("오늘 재백필 행:", len(rows))

ph = ",".join("?" * len(ids))
have = con.execute(f"SELECT COUNT(DISTINCT memory_id) FROM memory_embeddings WHERE memory_id IN ({ph})", ids).fetchone()[0]
print("memory_embeddings 벡터 보유:", have, "/", len(ids))

# 모델 태그 일관성
mods = con.execute(f"SELECT DISTINCT model FROM memory_embeddings WHERE memory_id IN ({ph})", ids).fetchall()
print("모델 태그:", [r[0] for r in mods])

# 백필 아닌 전체 중 memory_embeddings 보유 비율 (기준선)
tot = con.execute("SELECT COUNT(*) FROM working_memory").fetchone()[0]
totv = con.execute("SELECT COUNT(DISTINCT memory_id) FROM memory_embeddings").fetchone()[0]
print(f"전체 working_memory {tot} / 벡터 보유 {totv} ({totv*100//tot}%)")

# 세션별 재백필 수
by = collections.Counter()
for r in rows:
    meta = json.loads(con.execute("SELECT metadata_json FROM working_memory WHERE id=?", (r["id"],)).fetchone()[0])
    by[meta.get("session_key","?")] += 1
print("세션별:", dict(by))