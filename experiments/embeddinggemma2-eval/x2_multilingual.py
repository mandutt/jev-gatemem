"""X2-style multilingual probe — gemma2-q4f16 vs bekko-a8m.
10-way ranking per 5 languages (ja/zh/es/fr/de): query vs [gold + 9 distractors].
Semantic/paraphrase queries with NO lexical overlap -> hard regime (no lexical rescue).
Usage: python x2_multilingual.py
"""
import os, sys, json
import numpy as np

B = os.path.expandvars(r"%LOCALAPPDATA%\jev-mem\bench\run-20261006-embedgemma2")
B93 = os.path.expandvars(r"%LOCALAPPDATA%\jev-mem\bench\run-20260930")

LANGS = ["ja", "zh", "es", "fr", "de"]
Q = {
    "ja": ["仕事中に集中力を高めるには？", "パソコンを速くする方法は？"],
    "zh": ["如何提高工作时的专注力？", "如何加快电脑速度？"],
    "es": ["¿Cómo mejorar la concentración en el trabajo?", "¿Cómo acelerar mi computadora?"],
    "fr": ["Comment améliorer la concentration au travail ?", "Comment accélérer mon ordinateur ?"],
    "de": ["Wie verbessere ich die Konzentration bei der Arbeit?", "Wie beschleunige ich meinen Computer?"],
}
GOLD = {
    "ja": ["集中力を高めるには、タスクを細かく分けて休憩を挟むと効果的です。", "パソコンの動作を速く保つには、不要なファイルを削除し、ストレージの空きを確保するのが効果的です。"],
    "zh": ["长期专注工作的方法是把任务分解为小块，并适当安排休息时间。", "清理系统垃圾文件、关闭不必要的启动项，可以明显提升电脑速度。"],
    "es": ["Para mejorar la concentración en el trabajo, divide las tareas en pasos pequeños y toma descansos regulares.", "Para acelerar tu computadora, elimina archivos innecesarios y libera espacio en disco."],
    "fr": ["Pour améliorer la concentration au travail, divisez les tâches en petites étapes et faites des pauses régulières.", "Pour accélérer votre ordinateur, supprimez les fichiers inutiles et libérez de l'espace disque."],
    "de": ["Um die Konzentration bei der Arbeit zu verbessern, teilen Sie Aufgaben in kleine Schritte und machen Sie regelmäßig Pausen.", "Um Ihren Computer zu beschleunigen, löschen Sie unnötige Dateien und geben Sie Speicherplatz frei."],
}
DISTRACT = {
    "ja": ["今日の天気はどうですか。", "おすすめの本を教えてください。", "日本の歴史の重要人物は？", "美味しい料理の作り方は？", "電車の乗り方は？", "猫の飼い方のコツは？", "新しいスマホの機種は？", "旅行のおすすめは？", "健康診断の予約は？"],
    "zh": ["今天的天气怎么样？", "有什么好吃的菜谱推荐？", "中国有哪些著名景点？", "怎么办理护照？", "如何学英语？", "最新的手机是什么？", "养狗要注意什么？", "怎么提高睡眠质量？", "推荐一部好看的电影。"],
    "es": ["¿Cómo está el clima hoy?", "¿Cuál es la capital de España?", "¿Cómo aprender guitarra?", "Mejores películas de 2024.", "¿Cómo funciona un coche?", "Consejos para viajar barato.", "¿Qué es la inteligencia artificial?", "¿Cómo mejorar mi inglés?", "Recetas de paella."],
    "fr": ["Quel temps fait-il aujourd'hui ?", "Quels sont les meilleurs livres ?", "Comment apprendre le piano ?", "Quel est le meilleur film de 2024 ?", "Comment fonctionne une voiture ?", "Conseils pour voyager pas cher.", "Qu'est-ce que l'intelligence artificielle ?", "Comment améliorer mon anglais ?", "Recette de crêpes."],
    "de": ["Wie ist das Wetter heute?", "Welche Bücher sind empfehlenswert?", "Wie lernt man Klavier?", "Was sind die besten Filme 2024?", "Wie funktioniert ein Auto?", "Tipps für günstiges Reisen.", "Was ist künstliche Intelligenz?", "Wie verbessere ich mein Englisch?", "Rezept für Pfannkuchen."],
}

items = []
for lang in LANGS:
    for qi, gold in enumerate(GOLD[lang]):
        docs = [gold] + DISTRACT[lang][:9]
        items.append((lang, Q[lang][qi], docs, 0))
print("items:", len(items), "languages:", LANGS, flush=True)


def run_gemma2():
    sys.path.insert(0, B)
    from embgemma2_runner import EmbGemma2Runner
    m = EmbGemma2Runner(os.path.join(B, "model-src"))
    hits = 0
    for lang, q, docs, gi in items:
        qv = np.array(m.embed([q])[0])
        dv = np.array(m.embed(docs, doc=True))
        dn = dv / (np.linalg.norm(dv, axis=1, keepdims=True) + 1e-12)
        s = dn @ (qv / (np.linalg.norm(qv) + 1e-12))
        hits += int(np.argmax(s) == gi)
    return hits


def run_bekko():
    os.environ["HF_HOME"] = os.path.join(B93, "model-cache")
    os.environ["HF_HUB_OFFLINE"] = "1"
    sys.path.insert(0, B93)
    from fastembed import TextEmbedding
    from register_custom import register
    register("bench/bekko-a8m")
    m = TextEmbedding(model_name="bench/bekko-a8m", cache_dir=os.path.join(B93, "fe-cache"))
    _obj = getattr(m, "model", m)
    tok = getattr(_obj, "tokenizer", None)
    if tok is not None and hasattr(tok, "enable_truncation"):
        tok.enable_truncation(max_length=512)
    hits = 0
    for lang, q, docs, gi in items:
        qv = np.array(list(m.embed([q]))[0])
        dv = np.array(list(m.embed(docs)))
        dn = dv / (np.linalg.norm(dv, axis=1, keepdims=True) + 1e-12)
        s = dn @ (qv / (np.linalg.norm(qv) + 1e-12))
        hits += int(np.argmax(s) == gi)
    return hits


results = {}
for name, fn in [("gemma2-q4f16", run_gemma2), ("bench/bekko-a8m", run_bekko)]:
    h = fn()
    results[name] = {"acc@1": h / len(items), "hits": h, "total": len(items)}
    print(name, results[name], flush=True)

with open(os.path.join(B, "x2_multilingual_result.json"), "w", encoding="utf-8") as f:
    json.dump(results, f, indent=2, ensure_ascii=False)
print("X2 DONE")