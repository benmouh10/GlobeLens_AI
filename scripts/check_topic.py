from app.services.article_classifier import classify_topic, topic_is_contradicted

CASES = [
    (
        "Christa Pike seeks firing squad, not lethal injection",
        "Christa Pike seeks firing squad, not lethal injection. The US Supreme Court "
        "denied her bid to halt the execution. Tennessee had set to execute the first "
        "woman on death row in over 200 years. A federal appeals court intervened at "
        "the last minute in a case that drew national attention to capital punishment "
        "policy and the criminal justice system.",
        "TECHNOLOGY",
    ),
    (
        "Photos: Kashmir's 600-year-old Wazwan wedding feast adapts to modern life",
        "Autumn approaches in the valley of Kashmir, where cooks prepare a lavish "
        "multi-course mutton feast central to traditional wedding celebrations. Wazwan "
        "arrived from Central Asia in the 14th century when rulers brought skilled "
        "chefs along with carpet and shawl weavers describing its heritage and craft.",
        "TECHNOLOGY",
    ),
    (
        "Botswana condemned for slaughtering 23 elephants for independence celebrations",
        "Botswana is home to the world's largest elephant population. Animal rights "
        "activists criticised the decision to authorise the killing of 23 elephants to "
        "provide meat for independence festivities marking 60 years since independence.",
        "POLITICS",
    ),
    (
        "Russia ramps up disinformation attacks on French media",
        "The Russian government intensified its disinformation campaign ahead of the "
        "2027 French presidential election, targeting French media outlets. A report "
        "found an 850% increase in fake news stories mimicking real media brands.",
        "POLITICS",
    ),
    (
        "Denmark vs Portugal: UEFA Nations League",
        "The UEFA Nations League match between Denmark and Portugal is a crucial Group "
        "A4 encounter. Ronaldo's involvement remains a topic of debate while the two "
        "teams chase goals in a football tournament fixture.",
        "POLITICS",
    ),
    (
        "Tesla robotaxi expansion",
        "The electric vehicle maker expanded its autonomous robotaxi fleet, with new "
        "software and self-driving technology deployed on city streets.",
        "SPORTS",
    ),
]

for title, body, claimed in CASES:
    keyword = classify_topic(title, body)
    contradicted = topic_is_contradicted(title, body, claimed)
    if contradicted and keyword:
        verdict = f"OVERRIDE {claimed} -> {keyword}"
    elif keyword:
        verdict = f"agrees ({keyword})"
    else:
        verdict = "no evidence, keep LLM"
    print(f"  {title[:44]:46s} claimed={claimed:11s} -> {verdict}")