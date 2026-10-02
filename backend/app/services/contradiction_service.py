"""
GlobeLens AI — Cross-Source Contradiction Detection
===================================================
Finds claims that different outlets of the same event disagree on.

Ported from ``globe/pipeline/compressor.py::detect_contradictions``, which
operates on deduplicated ``FactObject`` facts. That pipeline is not importable
here: it needs torch, transformers, spacy and FlagEmbedding, none of which are
installed in the backend image. The decision logic itself is dependency-free, so
it is reimplemented against the backend's own ``Article`` rows. Embeddings for
the paraphrase filter come from the existing ``EmbeddingService`` (Ollama
bge-m3), so no new dependency is introduced.

A contradiction here is always a *candidate* surfaced for a human to judge,
never an automatic verdict. The output is deliberately conservative: reporting
a conflict that isn't one erodes trust in every other conflict this flags.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Iterable, Sequence

logger = logging.getLogger(__name__)

# Negations that invert the polarity of the word they precede. Kept as prefixes
# so "rejected" is matched by "reject".
NEGATIONS = (
    "not", "no", "never", "without", "deny", "denied", "denies",
    "reject", "rejected", "rejects", "refuse", "refused", "refuses",
    "false", "untrue", "contrary", "dispute", "disputed", "contradicts",
)

# Words too common to carry meaning when computing overlap between two claims.
STOPWORDS = frozenset("""
a an the and or but if then than that this these those of in on at to for
from by with as is are was were be been being has have had do does did will
would could should may might must it its it's he she they them their his her
we you i not no also more most other some such only own same so too very can
just about into over after before between during under above below up down
out off again further once here there when where why how all any both each
one two three four five six seven eight nine ten nobody someone anyone
""".split())

# Two claims must share at least this many meaningful words, and at least this
# fraction of the shorter claim's content words, before a difference is treated
# as a disagreement. Both are required: the ratio catches two sentences about
# different events that share vocabulary, and the absolute floor keeps a pair
# of short sentences from qualifying on ratio alone.
#
# The ratio does the real work. The absolute count was set from corpus data
# where short wire sentences ("the storm left 400 people homeless") legitimately
# overlap on only four or five content words while clearly reporting the same
# figure.
MIN_SHARED_CONTENT_WORDS = 4
MIN_OVERLAP_RATIO = 0.34

# Numbers differing by less than this ratio are treated as the same figure
# written differently (38.0 vs 38, 1,200 vs 1200).
NUMERIC_DIVERGENCE_RATIO = 1.15

# Two claims this similar in meaning are paraphrases even if their numbers
# differ. Raising it back toward 0.92 reintroduces false conflicts on details
# like casualty counts quoted at different times.
PARAPHRASE_SIMILARITY = 0.88

# Near-identical claims that nonetheless state different figures. Only applied
# to numeric conflicts: at this similarity the disagreement is in a detail, not
# in the substance of the report.
NEAR_DUPLICATE_SIMILARITY = 0.94

# Sentences shorter than this are navigation chrome, quotes fragments or legal
# boilerplate, not checkable claims.
MIN_CLAIM_CHARS = 40

# Hard ceiling per event so a pathological article cannot stall enrichment.
MAX_CLAIMS_PER_EVENT = 120

# A sentence boundary is a period, bang or question mark followed by
# whitespace and a capital or an opening quote or bracket. The negative
# lookbehind matters: without it a decimal like "1.5" or an initial such as
# "Pike's" would split mid-word, and requiring a capital after the space keeps
# ordinary abbreviations from tearing a sentence in half.
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z\"'(])")
_NUMBER = re.compile(r"\d+(?:,\d{3})*(?:\.\d+)?%?")
# Hyphenated and apostrophised words stay one token, but a trailing possessive
# is stripped in _content_words so "Pike's" and "Pike" are the same word.
_WORD = re.compile(r"[a-z0-9][a-z0-9'\-]*")
# The countable noun a number applies to, captured straight after the figure.
# Exactly one word: "400 people" binds "people", not "people were".
_UNIT_WORD = re.compile(r"([a-z][a-z\-]{2,})")
_NEGATION_RE = re.compile(r"\b(?:" + "|".join(NEGATIONS) + r")\b(?:\s+not)?", re.I)
# A curly or straight double quote marks speech rather than the outlet's own
# wording. Squared brackets cover wire copy like [said ...].
_QUOTE_RE = re.compile(r"[\"\u201c\u201d\u00ab]|\[\s*(?:said|added|wrote)\b", re.I)

# Common units and scale words stripped before comparing magnitudes, so
# "1,200 people" and "1.2 thousand people" compare equal.
_UNIT_MULTIPLIER = {
    "thousand": 1_000, "k": 1_000,
    "million": 1_000_000, "m": 1_000_000, "mn": 1_000_000,
    "billion": 1_000_000_000, "bn": 1_000_000_000,
}


@dataclass(frozen=True)
class Claim:
    """A single checkable assertion attributed to one outlet."""

    text: str
    source: str
    article_id: str

    @property
    def content_words(self) -> frozenset[str]:
        return _content_words(self.text)

    @property
    def numbers(self) -> tuple[float, ...]:
        return tuple(sorted(v for v, _ in self.quantities))

    @property
    def quantities(self) -> tuple[tuple[float, str], ...]:
        """(value, unit) pairs. See _quantities for why the unit matters."""
        return tuple(_quantities(self.text))


@dataclass(frozen=True)
class Contradiction:
    """A disagreement between two outlets about the same event."""

    claim_a: Claim
    claim_b: Claim
    nature: str  # numeric_conflict | polarity_conflict
    detail: str

    def to_dict(self) -> dict:
        return {
            "type": "contradiction",
            "nature": self.nature,
            "detail": self.detail,
            "claim_a": {"text": self.claim_a.text, "source": self.claim_a.source},
            "claim_b": {"text": self.claim_b.text, "source": self.claim_b.source},
        }


def _content_words(text: str) -> frozenset[str]:
    """
    Meaningful words for overlap comparison.

    Strips the trailing possessive: "Pike's sentence" and "Pike was sentenced"
    are about the same person, and treating "pike's" as its own token drops
    their overlap far enough to hide a real conflict.
    """
    out: set[str] = set()
    for raw in _WORD.findall(text.lower()):
        w = raw
        if w.endswith("'s"):
            w = w[:-2]
        if len(w) > 2 and w not in STOPWORDS:
            out.add(w)
    return frozenset(out)


def _numbers(text: str) -> list[float]:
    """Extract comparable magnitudes, applying thousand/million scale words."""
    out: list[float] = []
    for match in _NUMBER.finditer(text):
        raw = match.group(0)
        try:
            value = float(raw.replace(",", "").rstrip("%"))
        except ValueError:
            continue
        # Look two tokens ahead for a scale word: "1.2 million", "1,200 k".
        tail = text[match.end(): match.end() + 16].lower().strip().lstrip(",")
        scale = 1.0
        for unit, multiplier in _UNIT_MULTIPLIER.items():
            if tail.startswith(unit):
                scale = multiplier
                break
        out.append(value * scale)
    return out


def _stem(word: str) -> str:
    """
    Reduce an inflected word to a comparable root.

    Necessary because outlets write the same denial with different verbs:
    "did not confirm" and "has not confirmed" are one claim, and treating them
    as two different negated tokens makes a paraphrase look like a polarity
    conflict. Light suffix stripping, not a linguistics project — it only needs
    to make morphological variants of one verb compare equal.
    """
    w = word.lower()
    # -es before bare -s: "casualties" is casualt+ies, so stripping only "s"
    # leaves a trailing "i" and fails to match "casualty".
    if w.endswith("ies") and len(w) > 5:
        return w[:-3] + "y"
    for suffix in ("ing", "ed", "es", "s"):
        if w.endswith(suffix) and len(w) - len(suffix) >= 4:
            return w[: -len(suffix)]
    return w


# Filler that can sit between a negation and the thing it denies. "turned out
# not to exist" denies "exist" just as "did not exist" does, so stopping at the
# first word after the negation would miss it and make two outlets that agree
# something never existed look like they disagree.
_NEGATION_PARTICLES = frozenset({
    "to", "be", "been", "being", "ever", "really", "actually", "yet",
    "at", "all", "yet", "in", "any", "always", "necessarily", "even",
})


def _first_content_word(window: str) -> str | None:
    """
    The word a negation actually attaches to, or None if it attaches to nothing.

    Only the explicit particle list is walked past, never ordinary stopwords:
    "not to exist" denies "exist", but "without a doubt" and "no one has said"
    must stay empty. Skipping every stopword to find a target would invent
    nonsense denials like 'one source negates "doubt"'.
    """
    for raw in _WORD.findall(window[:40]):
        word = raw
        if word.endswith("'s"):
            word = word[:-2]
        if word in _NEGATION_PARTICLES:
            continue
        if len(word) <= 2 or word in STOPWORDS:
            return None
        return word
    return None


def _negated_tokens(text: str) -> frozenset[str]:
    """
    Tokens that carry a negation directly attached to them.

    "did not confirm" negates "confirm"; an unrelated "no" elsewhere in the
    sentence does not. This is stricter than intersecting two negation word
    sets, which would fire on any sentence that merely mentions denial.
    """
    negated: set[str] = set()
    lowered = text.lower()
    for match in _NEGATION_RE.finditer(lowered):
        window = lowered[match.end(): match.end() + 40]
        word = _first_content_word(window)
        if word is None:
            continue
        negated.add(_stem(word))
    return frozenset(negated)


def split_claims(text: str) -> list[str]:
    """
    Split article text into candidate claims.

    A regex splitter rather than spacy: the backend image has no spaCy model,
    and the contradiction logic needs only approximate sentence boundaries.
    """
    flat = re.sub(r"\s+", " ", text or "").strip()
    if not flat:
        return []
    out: list[str] = []
    for piece in _SENTENCE_SPLIT.split(flat):
        candidate = piece.strip()
        if len(candidate) >= MIN_CLAIM_CHARS:
            out.append(candidate)
    return out


def collect_claims(
    articles: Iterable[tuple[str, str, str]],
    max_claims: int = MAX_CLAIMS_PER_EVENT,
) -> list[Claim]:
    """
    Build the claim pool from ``(source_name, article_id, content)`` triples.
    """
    claims: list[Claim] = []
    for source, article_id, content in articles:
        for text in split_claims(content):
            claims.append(Claim(text=text, source=source, article_id=article_id))
            if len(claims) >= max_claims:
                logger.info("claim pool capped at %d claims", max_claims)
                return claims
    return claims


def _quantities(text: str) -> list[tuple[float, str]]:
    """
    Extract numbers bound to the noun they count.

    Returns ``(value, unit)`` pairs, where ``unit`` is the normalised head noun
    following the number ("400 people" -> ``(400, "people")``). A bare number
    with no countable noun gets unit ``""``.

    The unit binding is what makes conflict detection honest. Comparing every
    number in two sentences treats "400 detained" and "76 injured" as competing
    versions of one figure, which is the single largest source of false
    positives in a report that claims to find contradictions.
    """
    out: list[tuple[float, str]] = []
    lowered = text.lower()

    for match in _NUMBER.finditer(lowered):
        raw = match.group(0)
        try:
            value = float(raw.replace(",", "").rstrip("%"))
        except ValueError:
            continue

        tail = lowered[match.end(): match.end() + 24].strip().lstrip(",")
        scale = 1.0
        for unit_word, multiplier in _UNIT_MULTIPLIER.items():
            if tail.startswith(unit_word):
                scale = multiplier
                tail = tail[len(unit_word):].strip()
                break

        # Skip a date or an ordinal: "on Tuesday the 5th" is not a quantity.
        preceding = lowered[max(0, match.start() - 12): match.start()].strip()
        if preceding.endswith("on") or preceding.endswith("january") or re.search(
            r"\b(january|february|march|april|may|june|july|august|september|october|november|december)$",
            preceding,
        ):
            continue

        head = _UNIT_WORD.match(tail)
        if head:
            unit = _stem(head.group(0))
            # Percentages are their own unit class.
            if raw.endswith("%"):
                unit = "percent"
        else:
            unit = ""

        out.append((value * scale, unit))
    return out


# Units whose bare form is too ambiguous to compare across sentences. "200
# years" (a historical interval) and "18 years" (an age) share the token "year"
# but measure unrelated things, so a unit match alone would report a conflict
# between them.
AMBIGUOUS_UNITS = frozenset({"year", "day", "month", "week", "hour", "time"})


# Language marking two figures as sequential steps in one narrative rather than
# competing claims: "from X to Y", "rose to", "fell to". Deliberately narrow.
# "to", "after" and "before" appear in ordinary claims too, and admitting them
# here would suppress genuine conflicts between two flat statements.
_SEQUENCE_RE = re.compile(
    r"\bfrom\b[^.;]{0,40}?\bto\b"
    r"|\b(?:rose|risen|fell|fallen|lowered|lowering|raised|raising"
    r"|jumped|climbing|climbed|dropped|dropping|soared|plunged|plunging"
    r"|surged|increased|increasing|decreased|decreasing"
    r"|doubled|tripled|halved)\b",
    re.I,
)


def _has_sequence(text: str) -> bool:
    """Whether a claim narrates a change over time rather than a single state."""
    return bool(_SEQUENCE_RE.search(text))


def _numeric_conflict(a: Claim, b: Claim) -> str | None:
    """
    Describe the numeric disagreement, or None if the figures agree.

    Only compares numbers that count the same thing: same unit, same order of
    magnitude, unambiguous unit. "3 sources" against "45 percent" are different
    quantities, and treating them as competing versions of one figure is how
    naive implementations manufacture conflicts out of unrelated sentences.
    """
    for va, ua in a.quantities:
        for vb, ub in b.quantities:
            # Both must name a unit, and it must be the same one. An unnamed
            # number ("in 2019", "aged 30") carries no comparable quantity.
            if not ua or not ub or ua != ub:
                continue
            if ua in AMBIGUOUS_UNITS:
                continue
            # "lowered the rent to 1,650" and "raised her rent from 500 to
            # 2,650" report two stages of one story, not rival figures for the
            # same measure. Comparing the middle and start values reports a
            # disagreement where there is a timeline.
            if _has_sequence(a.text) and _has_sequence(b.text):
                continue
            hi, lo = max(va, vb), min(va, vb)
            if lo <= 0:
                continue
            # Same order of magnitude: a restatement of one figure.
            if hi / lo > 100:
                continue
            if hi / lo >= NUMERIC_DIVERGENCE_RATIO:
                return f"one reports {va:g} {ua}, the other {vb:g} {ua}"
    return None


def _is_quoted(text: str) -> bool:
    """
    True when a claim carries an attributed quote.

    A quoted denial is the speaker's position, not the outlet's. Comparing two
    reports of the same quote must not be reported as a disagreement between
    the outlets, since reproducing identical wording means they agree.
    """
    return bool(_QUOTE_RE.search(text))


def _polarity_conflict(a: Claim, b: Claim) -> str | None:
    """
    Describe an assertion/denial split, or None.

    The negated token must be a word *both* claims are about, with exactly one
    side negating it. Two requirements, and both are load-bearing:

    - Sharing the topic word is what makes this a disagreement about the same
      thing. Without it, any pair where one sentence happens to contain "no"
      or "not" matches any other, which is how a report ends up claiming two
      unrelated sentences contradict each other.
    - Exactly one side must negate it. That is the actual dispute: one outlet
      says "life without parole", another says "possibility of parole". If both
      sides deny the same thing they agree, and that is not a conflict.
    """
    neg_a, neg_b = _negated_tokens(a.text), _negated_tokens(b.text)
    if not neg_a and not neg_b:
        return None

    # Words both claims are about, stemming so "involvement" matches
    # "involved".
    stemmed_b = {_stem(w) for w in b.content_words}
    stemmed_a = {_stem(w) for w in a.content_words}

    contested = (neg_a & stemmed_b) | (neg_b & stemmed_a)
    if not contested:
        return None

    denied_by_a = neg_a & stemmed_b
    denied_by_b = neg_b & stemmed_a
    if denied_by_a and denied_by_b:
        # Both deny the same thing: agreement, not conflict.
        return None

    # A quoted denial is not the outlet's own claim. Two papers quoting the
    # same official's "our soldiers have never crossed the border" agree
    # completely, and reporting that as a contradiction is the most damaging
    # kind of error this feature can make.
    if _is_quoted(a.text) or _is_quoted(b.text):
        return None

    term = sorted(denied_by_a or denied_by_b)[0]
    return f"one source negates \"{term}\" where the other asserts it"


class ContradictionDetector:
    """Compares claims across outlets, with an embedding-based paraphrase guard."""

    def __init__(self, embedder=None) -> None:
        # Injected rather than constructed here: this service is sync, and
        # EmbeddingService.generate_vector is async.
        self._embedder = embedder

    def _similarity(self, a: str, b: str, cache: dict) -> float | None:
        """Cosine similarity via the injected embedder, if one is available."""
        if self._embedder is None:
            return None
        for text in (a, b):
            if text not in cache:
                try:
                    cache[text] = self._embedder(text)
                except Exception as exc:  # noqa: BLE001 - degrade, never fail
                    # stdlib logging: structured `error=` kwargs belong to
                    # structlog and raise TypeError here.
                    logger.warning("embedder failed, skipping similarity: %s", exc)
                    cache[text] = None
        va, vb = cache[a], cache[b]
        if not va or not vb:
            return None
        if len(va) != len(vb):
            return None
        dot = sum(x * y for x, y in zip(va, vb))
        na = sum(x * x for x in va) ** 0.5
        nb = sum(y * y for y in vb) ** 0.5
        if na == 0 or nb == 0:
            return None
        return dot / (na * nb)

    def detect(
        self,
        claims: Sequence[Claim],
        max_per_pair: int = 1,
    ) -> list[Contradiction]:
        """
        Find disagreements between claims from different outlets.

        ``max_per_pair`` caps how many conflicts one outlet pair may
        contribute, so two outlets with a systematic wording difference cannot
        flood an event with dozens of near-duplicate flags.
        """
        results: list[Contradiction] = []
        seen: set[tuple[str, str]] = set()
        per_outlet_pair: dict[tuple[str, str], int] = {}
        embed_cache: dict = {}
        # Pairs dropped because the paraphrase guard could not be evaluated.
        # Zero in normal operation; non-zero means the embedder is unavailable
        # and detection is deliberately reporting less rather than reporting
        # unguarded findings.
        unguardable = 0

        for i, a in enumerate(claims):
            for b in claims[i + 1:]:
                if a.source == b.source:
                    continue  # same outlet cannot contradict itself

                pair_key = tuple(sorted((a.source, b.source)))
                if per_outlet_pair.get(pair_key, 0) >= max_per_pair:
                    continue

                shared = a.content_words & b.content_words
                if len(shared) < MIN_SHARED_CONTENT_WORDS:
                    continue

                # Overlap relative to the shorter claim. Five shared words in a
                # 6-word sentence is one topic; five shared words in a 60-word
                # sentence is a shared vocabulary, not a shared claim.
                shorter = min(len(a.content_words), len(b.content_words))
                if shorter == 0 or len(shared) / shorter < MIN_OVERLAP_RATIO:
                    continue

                fingerprint = (a.text[:120], b.text[:120])
                if fingerprint in seen:
                    continue

                # Paraphrase guard: same figures and very close in meaning means
                # one is a rewrite of the other, not a disagreement.
                #
                # When similarity is unavailable the guard cannot do its job. The
                # pair is dropped rather than reported unguarded: with the embedder
                # down there is no way to tell a genuine disagreement from two
                # sentences that differ only in a figure detail, and falsely
                # accusing two outlets of contradicting each other is the one
                # error this product must not make. Skipped pairs are counted and
                # logged so the degradation is visible rather than silent.
                shared_numbers = bool(set(a.numbers) & set(b.numbers))
                if shared_numbers:
                    sim = self._similarity(a.text, b.text, embed_cache)
                    if sim is None:
                        unguardable += 1
                        continue
                    if sim >= PARAPHRASE_SIMILARITY:
                        seen.add(fingerprint)
                        continue

                # Computed once: the nature and the detail come from the same
                # test, so calling it twice repeated the number loop for free.
                numeric = _numeric_conflict(a, b)
                detail = numeric or _polarity_conflict(a, b)
                if detail is None:
                    continue

                # A very high similarity with differing numbers is usually a
                # detail that changed between publications rather than a clash.
                # Scoped to numeric conflicts only: a polarity split is an
                # explicit disagreement by construction, so applying the
                # similarity cutoff to it discards genuine findings whenever
                # the embedder returns a high score for two short sentences
                # that differ on precisely the point in dispute.
                if numeric:
                    sim = self._similarity(a.text, b.text, embed_cache)
                    if sim is None:
                        unguardable += 1
                        continue
                    if sim >= NEAR_DUPLICATE_SIMILARITY:
                        seen.add(fingerprint)
                        continue

                seen.add(fingerprint)
                per_outlet_pair[pair_key] = per_outlet_pair.get(pair_key, 0) + 1
                results.append(
                    Contradiction(
                        claim_a=a,
                        claim_b=b,
                        nature=(
                            "numeric_conflict" if numeric
                            else "polarity_conflict"
                        ),
                        detail=detail,
                    )
                )

        # %s-style, not keyword arguments. This is a stdlib logger: passing
        # claims=... as a kwarg raises TypeError inside Logger._log, but only
        # once INFO logging is actually enabled, so the bug hides until someone
        # turns the log level up and every scan starts failing.
        logger.info(
            "contradiction scan complete: %d claims, %d found, %d outlet pairs",
            len(claims), len(results), len(per_outlet_pair),
        )
        if unguardable:
            logger.warning(
                "dropped %d claim pair(s): embedder unavailable so the paraphrase "
                "guard could not be applied. Reported contradictions may be fewer "
                "than reality until embeddings recover.",
                unguardable,
            )
        return results


async def scan_event_contradictions(
    event_id,
    session,
    max_per_pair: int = 1,
) -> int:
    """
    Scan one event's articles for cross-source disagreements and persist them.

    Returns the number of contradictions stored. Safe to call repeatedly: rows
    are replaced, so a rescan of unchanged articles converges to the same
    result instead of accumulating duplicates.

    Needs at least two distinct outlets. A single-source event cannot
    contradict anything, and comparing a publication against itself is how
    naive implementations report every numeric difference as a conflict.
    """
    from sqlalchemy import select as _select
    from sqlalchemy.orm import selectinload as _selectinload

    from app.entities.models import Article as _Article
    from app.entities.models import Event as _Event
    from app.repositories.event_repository import EventRepository
    from app.services.embedding_service import EmbeddingService

    result = await session.execute(
        _select(_Event)
        .where(_Event.id == event_id)
        .options(
            _selectinload(_Event.articles).selectinload(_Article.source)
        )
    )
    event = result.scalars().first()
    if event is None:
        raise ValueError(f"Event with id {event_id} not found")

    articles = [a for a in event.articles if a.content and a.content.strip()]
    distinct_sources = {a.source_id for a in articles if a.source_id}
    if len(distinct_sources) < 2:
        logger.info(
            "contradiction scan skipped for %s: fewer than two sources (%d articles)",
            str(event_id)[:8], len(articles),
        )
        return 0

    claim_pool = collect_claims(
        (
            (a.source.name if a.source else "Unknown", str(a.id), a.content)
            for a in articles
        )
    )
    if len(claim_pool) < 2:
        return 0

    # The paraphrase guard needs real vectors. EmbeddingService is async and
    # caches by content hash, so the whole claim pool is embedded up front here
    # and the sync detector reads from a plain dict. A mock or absent embedder
    # would silently disable the guard and let paraphrases register as
    # conflicts, so failures are surfaced rather than swallowed.
    embedder = EmbeddingService()
    vectors: dict[str, list[float] | None] = {}
    for claim in claim_pool:
        try:
            vectors[claim.text] = await embedder.generate_vector(claim.text)
        except Exception as exc:  # noqa: BLE001 - degrade to no guard
            logger.warning(
                "embedding failed for claim, paraphrase guard degraded: %s", exc
            )
            vectors[claim.text] = None

    detector = ContradictionDetector(embedder=lambda text: vectors.get(text))
    found = detector.detect(claim_pool, max_per_pair=max_per_pair)

    rows = [
        {
            "nature": c.nature,
            "detail": c.detail,
            "claim_a_text": c.claim_a.text,
            "claim_a_source": c.claim_a.source,
            "claim_b_text": c.claim_b.text,
            "claim_b_source": c.claim_b.source,
        }
        for c in found
    ]

    stored = await EventRepository(session).replace_contradictions(event_id, rows)

    # Commit here rather than leaving it to the caller. Both current callers
    # (recluster.enrich and LLMService.process_pending_events) run this after
    # update_event_intelligence, which commits internally, so neither of them
    # commits again afterwards. Without this line the rows are silently rolled
    # back when the session closes: no error, no findings, nothing stored.
    await session.commit()

    logger.info(
        "contradictions stored for %s: %d from %d sources over %d claims",
        str(event_id)[:8], stored, len(distinct_sources), len(claim_pool),
    )
    return stored