"""GLiNER2.5-multi-Decide vs gold50 G-AS 오프라인 평가 (JEV 0회)
JEV verdict를 gold로 쓰지 않고, ab_assistant_gold50_as.jsonl의 인간 gold(STORE/NO_STORE)와 비교.
G-AS 규칙: store==STORE && type != context -> KEEP. GLiNER는 store 2라벨 + type choice로 근사.
"""
import json, time, sys
sys.stdout.reconfigure(encoding='utf-8')
from gliner2 import AutoExtractor

m = AutoExtractor.from_pretrained('fastino/GLiNER2.5-multi-Decide')
rows = [json.loads(l) for l in open(r"C:\Users\mandu\hermes-made\jev-memory-middleware\memory-classification-evaluation\data\ab_assistant_gold50_as.jsonl", encoding="utf-8") if l.strip()]

TYPES = ["fact","preference","procedure","context","observation","event","commitment",
         "insight","decision","question","error","summary","reference","conversation"]

def store_prompt(u):
    """STORE/NO_STORE를 GLiNER choice로 근사 — description 부착"""
    return m.classify_text(u[:1500], {"store": {
        "labels": {
            "STORE": "Contains durable, reusable information worth remembering: facts, preferences, decisions, completed results, procedures, or insights that would matter in a future session",
            "NO_STORE": "Transient conversation: in-progress narration, temporary status, intermediate analysis, questions being asked, or things about to be done",
        }}})["store"]

def type_prompt(u):
    return m.classify_text(u[:1500], {"memory_type": {
        "labels": {
            "fact": "An established fact or configuration about systems, tools, or environment",
            "preference": "A user preference or rule for how to behave",
            "procedure": "Steps or a method for doing something",
            "context": "In-progress narration or temporary conversational state",
            "observation": "What was just observed during work",
            "event": "Something that happened at a point in time",
            "commitment": "An intention to do something in the future",
            "insight": "A non-obvious conclusion or lesson learned",
            "decision": "A decision made with rationale",
            "error": "An error or failure encountered",
            "summary": "A summary of work done",
            "reference": "A pointer to a resource or location",
            "question": "A question awaiting an answer",
            "conversation": "Ordinary dialogue with no durable content",
        }}})["memory_type"]

out = []
t_start = time.time()
lat_s, lat_t = [], []
for i, r in enumerate(rows, 1):
    u = r['utterance']
    t0 = time.time(); store = store_prompt(u); lat_s.append(time.time()-t0)
    t1 = time.time(); typ = type_prompt(u); lat_t.append(time.time()-t1)
    keep = store == 'STORE' and typ != 'context'
    gold_keep = r['gold'] == 'STORE'
    out.append({'id': r['id'], 'gold': r['gold'], 'gliner_store': store, 'gliner_type': typ,
                'gliner_keep': keep, 'gold_keep': gold_keep})
    if i % 10 == 0:
        print(f"{i}/50 done", flush=True)

tp = sum(1 for o in out if o['gliner_keep'] and o['gold_keep'])
fp = sum(1 for o in out if o['gliner_keep'] and not o['gold_keep'])
fn = sum(1 for o in out if not o['gliner_keep'] and o['gold_keep'])
tn = sum(1 for o in out if not o['gliner_keep'] and not o['gold_keep'])
import statistics as st
print(json.dumps({
    'TP': tp, 'FP': fp, 'FN': fn, 'TN': tn,
    'precision': round(tp/(tp+fp), 3) if tp+fp else None,
    'recall': round(tp/(tp+fn), 3) if tp+fn else None,
    'f1': round(2*tp/(2*tp+fp+fn), 3),
    'accuracy': round((tp+tn)/len(out), 3),
    'latency_store_ms_p50': round(st.median(lat_s)*1000),
    'latency_type_ms_p50': round(st.median(lat_t)*1000),
    'latency_total_ms_p50': round(st.median([a+b for a,b in zip(lat_s,lat_t)])*1000),
}, indent=1))
json.dump(out, open('C:/Users/mandu/AppData/Local/hermes/cache/scratch/perfectrecall/gliner_gold50_result.json','w',encoding='utf-8'), ensure_ascii=False, indent=1)
