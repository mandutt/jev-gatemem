"""X2-extended multilingual probe — 40 items (5 langs x 8 queries), 10-way ranking.
Query = same-language question (no lexical overlap with docs), gold + 9 distractors.
Purpose: detect script-family collapse (koen-style) & general multilingual robustness.
Usage: python x2_extended.py
"""
import os, sys, json
import numpy as np

B = os.path.expandvars(r"%LOCALAPPDATA%\jev-mem\bench\run-20261006-embedgemma2")
B93 = os.path.expandvars(r"%LOCALAPPDATA%\jev-mem\bench\run-20260930")

# (lang, query, gold)[8 per lang]
DATA = {
    "ja": [
        ("仕事中に集中力を高めるには？", "集中力を高めるには、タスクを細かく分けて休憩を挟むと効果的です。"),
        ("パソコンを速くする方法は？", "パソコンの動作を速く保つには、不要なファイルを削除し、ストレージの空きを確保するのが効果的です。"),
        ("健康的な朝食には何を食べればいい？", "健康的な朝食には、卵、ヨーグルト、果物などバランスの良い食品がおすすめです。"),
        ("おすすめの本を教えて？", "歴史小説が好きなら、司馬遼太郎の作品がおすすめです。"),
        ("日本旅行のベストシーズンは？", "日本旅行は春の桜シーズンか秋の紅葉シーズンが最も美しいです。"),
        ("スマホの電池の持ちを良くするには？", "スマホの電池を長持ちさせるには、画面の明るさを下げ、不要なアプリを閉じると効果的です。"),
        ("外国語を早く覚えるコツは？", "外国語を早く習得するには、毎日少しずつ聞くことと話す練習を続けることが重要です。"),
        ("運動に最適な時間帯は？", "運動に最適な時間帯は、体が温まっている午後から夕方にかけてと言われています。"),
    ],
    "zh": [
        ("如何提高工作时的专注力？", "长期专注工作的方法是把任务分解为小块，并适当安排休息时间。"),
        ("如何加快电脑速度？", "清理系统垃圾文件、关闭不必要的启动项，可以明显提升电脑速度。"),
        ("健康的早餐应该吃什么？", "健康的早餐建议吃鸡蛋、酸奶和水果，营养均衡。"),
        ("有什么好书推荐吗？", "喜欢历史小说的话，我推荐你读《明朝那些事儿》。"),
        ("去日本旅游的最佳季节是什么时候？", "去日本旅游的最佳季节是春天的樱花季或秋天的红叶季。"),
        ("如何让手机电池更耐用？", "让手机电池更耐用的方法是降低屏幕亮度，并关闭不使用的后台应用。"),
        ("快速学习外语的诀窍是什么？", "快速学习外语的关键是每天坚持听说练习，哪怕时间不长。"),
        ("一天中什么时间运动最好？", "一天中最好的运动时间是体温升高的下午到傍晚时段。"),
    ],
    "es": [
        ("¿Cómo mejorar la concentración en el trabajo?", "Para mejorar la concentración en el trabajo, divide las tareas en pasos pequeños y toma descansos regulares."),
        ("¿Cómo acelerar mi computadora?", "Para acelerar tu computadora, elimina archivos innecesarios y libera espacio en disco."),
        ("¿Qué desayuno saludable puedo comer?", "Un desayuno saludable incluye huevos, yogur y frutas para una nutrición equilibrada."),
        ("¿Qué libro me recomiendas?", "Si te gustan las novelas históricas, te recomiendo los libros de Arturo Pérez-Reverte."),
        ("¿Cuál es la mejor época para viajar a Japón?", "La mejor época para viajar a Japón es la temporada de los cerezos en primavera o el otoño."),
        ("¿Cómo hago durar más la batería del móvil?", "Para que la batería dure más, baja el brillo de la pantalla y cierra las aplicaciones en segundo plano."),
        ("¿Cuál es el truco para aprender idiomas rápido?", "Para aprender un idioma rápido, practica escuchar y hablar un poco cada día."),
        ("¿Cuál es el mejor momento del día para hacer ejercicio?", "El mejor momento para hacer ejercicio es por la tarde, cuando el cuerpo ya está caliente."),
    ],
    "fr": [
        ("Comment améliorer la concentration au travail ?", "Pour améliorer la concentration au travail, divisez les tâches en petites étapes et faites des pauses régulières."),
        ("Comment accélérer mon ordinateur ?", "Pour accélérer votre ordinateur, supprimez les fichiers inutiles et libérez de l'espace disque."),
        ("Que manger pour un petit-déjeuner sain ?", "Un petit-déjeuner sain comprend des œufs, du yaourt et des fruits pour un équilibre nutritionnel."),
        ("Quel livre me recommandez-vous ?", "Si vous aimez les romans historiques, je vous recommande les œuvres d'Alexandre Dumas."),
        ("Quelle est la meilleure période pour voyager au Japon ?", "La meilleure période pour voyager au Japon est la saison des cerisiers au printemps ou l'automne."),
        ("Comment faire durer la batterie de mon téléphone ?", "Pour économiser la batterie, baissez la luminosité de l'écran et fermez les applications en arrière-plan."),
        ("Quel est le secret pour apprendre une langue rapidement ?", "Pour apprendre rapidement une langue, pratiquez l'écoute et la parole un peu chaque jour."),
        ("Quel est le meilleur moment pour faire du sport ?", "Le meilleur moment pour faire du sport est l'après-midi, quand le corps est déjà chaud."),
    ],
    "de": [
        ("Wie verbessere ich die Konzentration bei der Arbeit?", "Um die Konzentration bei der Arbeit zu verbessern, teilen Sie Aufgaben in kleine Schritte und machen Sie regelmäßig Pausen."),
        ("Wie beschleunige ich meinen Computer?", "Um Ihren Computer zu beschleunigen, löschen Sie unnötige Dateien und geben Sie Speicherplatz frei."),
        ("Was soll ich zum gesunden Frühstück essen?", "Ein gesundes Frühstück enthält Eier, Joghurt und Obst für eine ausgewogene Ernährung."),
        ("Welches Buch kannst du empfehlen?", "Wenn Sie historische Romane mögen, empfehle ich Ihnen die Werke von Umberto Eco."),
        ("Wann ist die beste Reisezeit für Japan?", "Die beste Reisezeit für Japan ist die Kirschblütenzeit im Frühling oder der Herbst."),
        ("Wie kann ich den Akku meines Handys schonen?", "Um den Akku zu schonen, senken Sie die Bildschirmhelligkeit und schließen Sie Hintergrund-Apps."),
        ("Wie lernt man schnell eine Fremdsprache?", "Um schnell eine Sprache zu lernen, üben Sie täglich ein wenig Hören und Sprechen."),
        ("Wann ist die beste Zeit für Sport?", "Die beste Zeit für Sport ist der Nachmittag, wenn der Körper bereits aufgewärmt ist."),
    ],
}
DISTRACT = {
    "ja": ["今日の天気はどうですか。", "おすすめの本を教えてください。", "日本の歴史の重要人物は？", "美味しい料理の作り方は？", "電車の乗り方は？", "猫の飼い方のコツは？", "新しいスマホの機種は？", "旅行のおすすめは？", "健康診断の予約は？"],
    "zh": ["今天的天气怎么样？", "有什么好吃的菜谱推荐？", "中国有哪些著名景点？", "怎么办理护照？", "如何学英语？", "最新的手机是什么？", "养狗要注意什么？", "怎么提高睡眠质量？", "推荐一部好看的电影。"],
    "es": ["¿Cómo está el clima hoy?", "¿Cuál es la capital de España?", "¿Cómo aprender guitarra?", "Mejores películas de 2024.", "¿Cómo funciona un coche?", "Consejos para viajar barato.", "¿Qué es la inteligencia artificial?", "¿Cómo mejorar mi inglés?", "Recetas de paella."],
    "fr": ["Quel temps fait-il aujourd'hui ?", "Quels sont les meilleurs livres ?", "Comment apprendre le piano ?", "Quel est le meilleur film de 2024 ?", "Comment fonctionne une voiture ?", "Conseils pour voyager pas cher.", "Qu'est-ce que l'intelligence artificielle ?", "Comment améliorer mon anglais ?", "Recette de crêpes."],
    "de": ["Wie ist das Wetter heute?", "Welche Bücher sind empfehlenswert?", "Wie lernt man Klavier?", "Was sind die besten Filme 2024?", "Wie funktioniert ein Auto?", "Tipps für günstiges Reisen.", "Was ist künstliche Intelligenz?", "Wie verbessere ich mein Englisch?", "Rezept für Pfannkuchen."],
}

items = []
for lang, arr in DATA.items():
    for q, gold in arr:
        docs = [gold] + DISTRACT[lang][:9]
        items.append((lang, q, docs, 0))
print("items:", len(items), flush=True)


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

with open(os.path.join(B, "x2_extended_result.json"), "w", encoding="utf-8") as f:
    json.dump(results, f, indent=2, ensure_ascii=False)
print("X2E DONE")