"""② 저장 본문 == 판정 입력 검증 (JEV 호출 없음)

write-gate가 보낸 입력: (user_content or "")[:1500]  (redaction 적용 전 원문)
저장 본문: "[USER] " + redacted(user_content)

비교: 저장 본문에서 "[USER] "/"[ASSISTANT] " 프리픽스 제거 후
      (a) redaction 적용 여부 확인 (원문과 다르면 redact됨)
      (b) 원문이 1500자 초과이면 truncation 차이 기록
      (c) gate 입력에 이전 턴 문맥이 포함되는지 (write_gate는 발화 단독 전송 — 문맥 없음 확인)
"""
import json, os, sqlite3, re

MNEMO = os.path.expandvars(r"%LOCALAPPDATA%\hermes\mnemosyne\data\mnemosyne.db")
BACKUP = os.path.expandvars(r"%LOCALAPPDATA%\hermes\cache\scratch\failopen_tag_backup.json")

backup = json.load(open(BACKUP, encoding="utf-8"))
targets = backup["targets"]

m = sqlite3.connect(f"file:{MNEMO}?mode=ro", uri=True)
cur = m.cursor()

# redact 모듈 불러오기 (원본 변환 재현)
import sys
sys.path.insert(0, r"C:\Users\mandu\hermes-made\jev-memory-middleware")
from jev_mem_core.redact import redact_text_high_precision
# 참고: 실제 저장 경로는 store.py _store_kept_impl에서
#   user = redact_text_high_precision(user_content) 후 "[USER] " + user 저장
# gate 입력은 redaction 전 (write_gate.py evaluate는 raw utterance 수신)

stats = {"total": 0, "redacted_unchanged": 0, "redacted_changed": 0,
         "over_1500": 0, "exact_after_prefix": 0, "prefix_mismatch": 0}
samples = []
for t in targets:
    mid = t["memory_id"]
    row = cur.execute("SELECT content FROM working_memory WHERE id=?", (mid,)).fetchone()
    if not row:
        continue
    content = row[0]
    stats["total"] += 1
    if content.startswith("[USER] "):
        body = content[len("[USER] "):]
        role = "user"
    elif content.startswith("[ASSISTANT] "):
        body = content[len("[ASSISTANT] "):]
        role = "assistant"
    else:
        stats["prefix_mismatch"] += 1
        samples.append((mid, "prefix?", content[:60]))
        continue
    # (b) 길이 — 실제 gate 입력은 min(len(raw), 1500)
    if len(body) > 1500:
        stats["over_1500"] += 1
    # (a) redaction 비교: body가 원문(백업엔 없음) — 여기선 body가 이미 redact된 저장본이므로
    #     "저장본 == gate 입력 (redaction 전)" 확인은 raw가 없어 불가.
    #     대신 redact()가 body에 재적용 시 변화가 없으면 body는 이미 redacted 상태임을 확인
    #     (gate는 redaction 전 원문을 받았으므로 저장본이 redacted면 "다름"이 정상)
    redone = redact_text_high_precision(body)
    if redone == body:
        stats["redacted_unchanged"] += 1
    else:
        stats["redacted_changed"] += 1
        samples.append((mid, f"redact-diff({role})", body[:60]))

m.close()

print("=== ② 저장 본문 vs 판정 입력 ===")
print(f"대상 메모리: {stats['total']}")
print(f"  [USER]/[ASSISTANT] 프리픽스 정상: {stats['total']-stats['prefix_mismatch']}")
print(f"  본문 1500자 초과 (gate truncation 대상): {stats['over_1500']}")
print(f"  body가 이미 redacted (redact 재적용 무변화): {stats['redacted_unchanged']}")
print(f"  redact 재적용 시 변화 (이중 redaction 필요): {stats['redacted_changed']}")
print(f"  프리픽스 불일치: {stats['prefix_mismatch']}")
print("\n샘플 (관심 케이스):")
for s in samples[:10]:
    print("  ", s)