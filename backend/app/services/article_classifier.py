"""
GlobeLens AI — Article Classification Utilities
Deterministic helpers that decide how an article is embedded and clustered.

These run before/around the LLM rather than asking the model, because the model
has proven unreliable on exactly these two questions:

1. bge-m3 embeds whole bodies, so syndicated roundups with an identical template
   ("Latest news bulletin | September 30th") cluster together on structure
   instead of subject matter.
2. qwen2.5-coder:7b was tagging a death-penalty story and a Kashmiri wedding
   feast as TECHNOLOGY, and geocoding four separate events to downtown
   Washington DC whenever it could not place a story confidently.

Keyword rules are cheap, explainable, and stable, so they handle these cases
and the LLM handles synthesis.
"""
import re
from typing import Optional

# Roundup / digest / aggregator markers. These articles cover many unrelated
# stories in one post, so their embedding is an average of several topics and
# drifts toward whatever else shares that average.
AGGREGATOR_TITLE_PATTERNS = (
    r"\bnews (?:bulletin|roundup|update|wrap)\b",
    r"\blatest news\b",
    r"\bin (?:brief|summary|pictures|photos)\b",
    r"\bwhat to know\b",
    r"\bmorning briefing\b",
    r"\bday in pictures\b",
    r"\bthis (?:week|weekend) in\b",
    r"\beditor'?s (?:note|pick|letter)\b",
    r"\brev(iew)?:.*\band\b",
    r"\bvideos?\b",
    # NB: "photos:"/"videos?" are deliberately NOT here. A photo essay or video
    # page is usually one story, and excluding them dropped a legitimate
    # 2-outlet merge (Al Jazeera + France 24 on the Ugandan coronation).
    r"\blive updates?\b",
    r"\bworld news (?:roundup|summary)\b",
    r"\bthe news (?:in|at) pictures\b",
    r"\b(?:news|world) (?:briefing|digest)\b",
)

AGGREGATOR_BODY_PATTERNS = (
    r"\bthis (?:news )?(?:bulletin|program|roundup) (?:covers|brings you|features)\b",
    r"\b(?:stay|keep) (?:up to date|tuned|updated) with\b",
    r"\bsubscribe to (?:our|the) (?:newsletter|channel)\b",
    r"\bfor more (?:news|coverage|updates)\b",
    r"\bthis (?:article|story) (?:was|is) (?:updated|corrected)\b.*\bcoverage (?:of|across)\b",
    r"\bsign up (?:for|to) (?:our|the) newsletter\b",
)

# Roundups are cheap to detect from the title alone.
_AGG_TITLE_RE = re.compile("|".join(AGGREGATOR_TITLE_PATTERNS), re.IGNORECASE)
_AGG_BODY_RE = re.compile("|".join(AGGREGATOR_BODY_PATTERNS), re.IGNORECASE)

# Topic keyword evidence. The first matching group wins, so order matters:
# narrow/specific topics before broad ones, and SPORTS/HEALTH before the
# catch-all WORLD. Words are matched on word boundaries to avoid
# "ai" matching inside "said" and "eu" inside "europe".
TOPIC_KEYWORDS: dict[str, tuple[str, ...]] = {
    "SPORTS": (
        "football", "soccer", "premier league", "la liga", "champions league",
        "nations league", "world cup", "olympic", "asian games", "match",
        "player", "striker", "midfielder", "goal", "goals", "manager",
        "coach", "club", "league", "tournament", "knockout", "fixture",
        "athletics", "cricket", "rugby", "tennis", "basketball", "f1",
        "formula one", "nba", "nfl", "mlb", "ufc", "motogp",
    ),
    "HEALTH": (
        "hospital", "health", "healthcare", "disease", "cancer", "virus",
        "vaccine", "outbreak", "epidemic", "pandemic", "patient", "clinic",
        "doctor", "nurse", "medicine", "medical", "mental health", "therapy",
        "obesity", "diet", "nutrition", "disease", "infection", "drug",
        "who warns", "disease control", "ambulance", "surgeon", "drugmaker",
        "longevity", "wellbeing", "wellness",
    ),
    "TECHNOLOGY": (
        "artificial intelligence", " ai ", "machine learning", "chatbot",
        "algorithm", "semiconductor", "chipmaker", "cybersecurity", "cyberattack",
        "data breach", "software", "startup", "smartphone", "internet",
        "social media", "tiktok", "cryptocurrency", "bitcoin", "quantum",
        "robot", "automation", "app ", "platform", "privacy", "surveillance",
        "deepfake", "voice clone", "cloned voice", "algorithm", "gpu",
        "nvidia", "openai", "anthropic",
    ),
    "ECONOMY": (
        "inflation", "gdp", "recession", "unemployment", "interest rate",
        "central bank", "federal reserve", "ecb", "imf", "world bank",
        "tariff", "trade deal", "trade war", "currency", "bond", "stock market",
        "equities", "nasdaq", "s&p", "budget deficit", "debt", "tax",
        "austerity", "investment", "merger", "ipo", "bankrupt", "commodit",
        "oil price", "gas price", "supply chain", "sanction", "export",
        "economy", "economic", "billion in losses", "strike action",
    ),
    "POLITICS": (
        "election", "parliament", "congress", "senate", "legislation", "bill",
        "voters", "campaign", "prime minister", "president", "opposition",
        "coalition", "referendum", "demonstration",
        # "protest", "strike", "government" and "minister" were removed: they
        # occur in nearly every world story, which made POLITICS win on raw
        # hit count for 74 of 95 classified articles. The more specific
        # political terms below carry the signal instead.
        "senator", "congressman", "impeach",
        "supreme court", "ruling", "verdict", "lawsuit", "sanctions",
        "diplomat", "summit", "treaty", "military", "troops", "army", "navy",
        "airstrike", "ceasefire", "war", "ukraine", "gaza", "israel",
        "execution", "death penalty", "sentenced", "conviction", "criminal",
        "appeal", "attorney", "prosecutor", "indictment", "trial", "murder",
        "assault", "police", "prison", "court", "judge", "legal",
    ),
}

_TOPIC_RE: dict[str, re.Pattern] = {
    topic: re.compile("|".join(rf"\b{re.escape(word.strip())}\b" for word in words), re.IGNORECASE)
    for topic, words in TOPIC_KEYWORDS.items()
}


def prepare_embedding_text(title: str, content: str, max_chars: int) -> str:
    """
    Build the text handed to the embedding model.

    The title is repeated at the front because bge-m3 has no notion of a
    headline being more important than the body, so a headline buried in
    thousands of words of article carries little weight in the resulting
    vector. Body text is then capped: the lead paragraph carries the news, and
    the tail is disproportionately boilerplate.
    """
    body = (content or "").strip()
    if max_chars and len(body) > max_chars:
        body = body[:max_chars].rsplit(" ", 1)[0]
    return f"{title.strip()}\n\n{title.strip()}\n\n{body}".strip()


def is_aggregator_article(title: str, content: str) -> bool:
    """
    True for roundups/digests/bulletins that summarise many stories at once.

    These are excluded from clustering because their embedding averages several
    unrelated topics, which produced false-positive merges such as a Euronews
    bulletin absorbing four separate news stories.
    """
    title = title or ""
    if _AGG_TITLE_RE.search(title):
        return True

    body = (content or "")[:1200]
    return bool(_AGG_BODY_RE.search(body))


def classify_topic(title: str, content: str, default: str = "WORLD") -> Optional[str]:
    """
    Infer a topic from keyword evidence, or None when nothing matches.

    Returns None rather than guessing so callers can keep the LLM's answer when
    there is no evidence to contradict it.
    """
    haystack = f" {title} \n {(content or '')[:2000]} "
    best_topic = None
    best_hits = 0
    for topic, pattern in _TOPIC_RE.items():
        hits = len(pattern.findall(haystack))
        if hits > best_hits:
            best_topic, best_hits = topic, hits
    return best_topic if best_hits >= 2 else None


def topic_is_contradicted(title: str, content: str, claimed_topic: str) -> bool:
    """
    True when an article has clear evidence for some topic *other* than claimed.

    This is the check that catches "Christa Pike execution" tagged TECHNOLOGY:
    there is no keyword evidence for technology, and strong evidence for
    politics, so the claim is contradicted. It deliberately requires positive
    evidence elsewhere, so it stays silent on stories where the keywords are
    simply too thin to judge.
    """
    if claimed_topic not in _TOPIC_RE:
        return False

    haystack = f" {title} \n {(content or '')[:2000]} "
    claimed_hits = len(_TOPIC_RE[claimed_topic].findall(haystack))

    best_topic = None
    best_hits = 0
    for topic, pattern in _TOPIC_RE.items():
        if topic == claimed_topic:
            continue
        hits = len(pattern.findall(haystack))
        if hits > best_hits:
            best_topic, best_hits = topic, hits

    return best_hits >= 2 and best_hits > claimed_hits