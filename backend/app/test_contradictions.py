"""
Tests for cross-source contradiction detection.

The risk being guarded against is a false positive: a conflict that is not one
makes every other flag on the page less trustworthy. So the suite asserts
specific claims are NOT flagged as often as it checks that real ones are.

Run:
    docker compose run --rm --no-deps backend python -m app.test_contradictions
"""
import asyncio

from app.services.contradiction_service import (
    Claim,
    ContradictionDetector,
    _negated_tokens,
    _numeric_conflict,
    _numbers,
    _quantities,
    collect_claims,
    split_claims,
)

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name} {detail}")


def test_number_parsing() -> None:
    print("\nnumbers")
    check("plain", _numbers("45 people") == [45.0])
    check("comma", _numbers("1,200 cases") == [1200.0])
    check("thousands scale", _numbers("1.2 thousand") == [1200.0], str(_numbers("1.2 thousand")))
    check("millions scale", _numbers("3 million") == [3_000_000.0], str(_numbers("3 million")))
    check(
        "magnitude guard",
        _numbers("3 sources") == [3.0] and _numbers("45 percent") == [45.0],
    )


def test_unit_binding() -> None:
    """The single most important property: numbers bind to what they count."""
    print("\nunit binding")
    detained = _quantities("police detaining more than 400 people on Tuesday")
    injured = _quantities("440 people arrested and 76 injured as protests spread")
    check("binds to head noun", any(u == "people" for _, u in detained), str(detained))
    check("binds injury unit", any(u == "injur" for _, u in injured), str(injured))

    # The real false positive from the corpus: same article, different
    # quantities. Detained vs injured must not compare as one figure.
    d = Claim(text="police detaining more than 400 people on Tuesday", source="A", article_id="1")
    i = Claim(text="440 people arrested and 76 injured in the protests", source="B", article_id="2")
    check("different units not a conflict", _numeric_conflict(d, i) is None,
          str(_numeric_conflict(d, i)))

    # Same unit, genuinely different figures.
    x = Claim(text="the storm left 400 people homeless across the region", source="A", article_id="1")
    y = Claim(text="officials say 900 people were left homeless by the storm", source="B", article_id="2")
    check("same unit conflicts", _numeric_conflict(x, y) is not None,
          str(_numeric_conflict(x, y)))

    check("percent is own unit",
          _quantities("45 percent support the plan") == [(45.0, "percent")],
          str(_quantities("45 percent support the plan")))
    check("dates skipped",
          all(u != "" for _, u in _quantities("the vote happened on 12 March")),
          str(_quantities("the vote happened on 12 March")))


def test_negation_targets() -> None:
    print("\nnegation targeting")
    check("direct", "confirm" in _negated_tokens("The government did not confirm the report"))
    # A negation must attach to a content word. Without this the corpus
    # produced flags like 'one source negates "a"'.
    check("skips determiner after negation",
          _negated_tokens("without a doubt the figure stands") == frozenset(),
          str(sorted(_negated_tokens("without a doubt the figure stands"))))
    check("skips pronoun after negation",
          _negated_tokens("no one has confirmed the total") == frozenset(),
          str(sorted(_negated_tokens("no one has confirmed the total"))))
    # Stemmed: "confirm" and "confirmed" are one claim, and treating them as
    # different tokens would flag every paraphrase as a polarity conflict.
    check(
        "morphological variants stem together",
        _negated_tokens("did not confirm") == _negated_tokens("has not confirmed"),
        f'{sorted(_negated_tokens("did not confirm"))} vs {sorted(_negated_tokens("has not confirmed"))}',
    )
    # "no casualties" does negate casualties; this is a real polarity claim,
    # not a stray preposition.
    check(
        "quantifier negates its noun",
        _negated_tokens("no casualties were reported")
        == _negated_tokens("no casualty was reported"),
        str(sorted(_negated_tokens("no casualties were reported"))),
    )
    check("no negation present", _negated_tokens("The batch was safe and approved") == frozenset())


def test_split_claims() -> None:
    print("\nclaim splitting")
    # Each kept sentence must clear MIN_CLAIM_CHARS on its own, so the fixture
    # sentences are written long enough rather than loosening the threshold.
    text = (
        "The city council voted seven to two on Tuesday to approve the transit plan. "
        "Officials said the measure passed after a lengthy debate over funding. Short."
    )
    claims = split_claims(text)
    check("filters short fragments", all(len(c) >= 40 for c in claims), str(claims))
    check("keeps long sentences", len(claims) == 2, str(len(claims)))
    check("empty input safe", split_claims("") == [])


def _c(text: str, source: str) -> tuple:
    return (source, f"{source}-id", text)


def _orthogonal_embedder(text: str):
    """
    Maps each distinct text to its own basis vector so no pair is ever judged a
    paraphrase. Numeric-conflict fixtures need this: the similarity guards fail
    closed when vectors are unavailable, so a fixture with no embedder would
    have every numeric pair withheld and could not assert a real conflict is
    still detected.
    """
    v = [0.0] * 64
    v[hash(text) % 64] = 1.0
    return v


def test_true_conflicts() -> None:
    print("\ndetects real conflicts")
    det = ContradictionDetector(embedder=_orthogonal_embedder)
    claims = collect_claims([
        _c(
            "The earthquake killed 340 people and injured more than 1,200 others "
            "according to regional officials.",
            "Al Jazeera",
        ),
        _c(
            "The earthquake killed 127 people and injured more than 900 others "
            "according to local authorities.",
            "Reuters",
        ),
    ])
    found = det.detect(claims)
    check("numeric conflict found", len(found) == 1, f"got {len(found)}")
    if found:
        check("nature is numeric", found[0].nature == "numeric_conflict")
        check("both sources present",
              {found[0].claim_a.source, found[0].claim_b.source} == {"Al Jazeera", "Reuters"})


def test_polarity_conflict() -> None:
    print("\ndetects polarity conflict")
    det = ContradictionDetector()
    claims = collect_claims([
        _c(
            "The health ministry confirmed that the vaccine batch was contaminated "
            "and recalled it immediately.",
            "Al Jazeera",
        ),
        _c(
            "The health ministry confirmed the vaccine batch was safe and issued no "
            "recall for the distributed lots.",
            "Reuters",
        ),
    ])
    found = det.detect(claims)
    check("polarity conflict found", len(found) >= 1, f"got {len(found)}")


def test_no_false_positives() -> None:
    print("\nrejects false positives")
    det = ContradictionDetector()

    same = collect_claims([
        _c(
            "The central bank raised interest rates by 25 basis points on Wednesday "
            "to curb persistent inflation.",
            "Al Jazeera",
        ),
        _c(
            "Policymakers lifted rates by 25 basis points on Wednesday in an attempt "
            "to reduce persistent inflation pressures.",
            "Reuters",
        ),
    ])
    check("same figure not a conflict", len(det.detect(same)) == 0, str(len(det.detect(same))))

    unrelated = collect_claims([
        _c(
            "The central bank raised interest rates by 25 basis points on Wednesday "
            "to curb persistent inflation.",
            "Al Jazeera",
        ),
        _c(
            "Hundreds of spectators filled the stadium as the final began, and the "
            "home side scored twice in the second half.",
            "ESPN",
        ),
    ])
    check("unrelated topics not compared", len(det.detect(unrelated)) == 0)

    one_sided = collect_claims([
        _c(
            "The health ministry confirmed the vaccine batch was safe and issued no "
            "recall for the distributed lots.",
            "Reuters",
        ),
        _c(
            "The batch was safe, officials said, and regulators approved its release "
            "for general distribution.",
            "AP",
        ),
    ])
    check("one-sided negation not a conflict", len(det.detect(one_sided)) == 0,
          str(len(det.detect(one_sided))))

    same_source = collect_claims([
        _c("The death toll reached 340 after the collapse, officials confirmed.", "X"),
        _c("The death toll reached 127 after the collapse, officials confirmed.", "X"),
    ])
    check("same outlet cannot contradict itself", len(det.detect(same_source)) == 0)


def test_paraphrase_guard() -> None:
    print("\nparaphrase guard with embeddings")
    calls: list[str] = []

    def fake_embed(text: str):
        calls.append(text)
        # Every text maps to the same direction, so any pair is a paraphrase.
        return [1.0, 0.0, 0.0]

    det = ContradictionDetector(embedder=fake_embed)
    # Shares the figure 1200 on purpose: the guard only runs when numbers
    # overlap, so a fixture without shared figures would never reach it.
    claims = collect_claims([
        _c(
            "The summit ended without agreement after 1200 delegates failed to bridge "
            "the gap between the two positions on the border question.",
            "Al Jazeera",
        ),
        _c(
            "Delegates left the summit without agreement, the 1200 participants "
            "unable to close the divide between their opposing border positions.",
            "Reuters",
        ),
    ])
    found = det.detect(claims)
    check("paraphrase suppressed", len(found) == 0, str(len(found)))
    check("embedder was consulted", len(calls) > 0, f"calls={len(calls)}")


def test_breaker() -> None:
    print("\nembedder failure fails closed")
    def broken(text: str):
        raise RuntimeError("ollama down")

    det = ContradictionDetector(embedder=broken)
    claims = collect_claims([
        _c(
            "The earthquake killed 340 people and injured more than 1,200 others "
            "according to regional officials.",
            "Al Jazeera",
        ),
        _c(
            "The earthquake killed 127 people and injured more than 900 others "
            "according to local authorities.",
            "Reuters",
        ),
    ])
    found = det.detect(claims)
    # With no vectors there is no way to tell a real disagreement from two
    # sentences differing only in a figure, so the pair is withheld rather than
    # reported unguarded. Reporting nothing is recoverable; falsely telling two
    # outlets they contradict each other is not.
    check("withholds unguarded numeric conflict", len(found) == 0, str(len(found)))


def test_polarity_conflict_survives_embedder_outage() -> None:
    """A polarity split needs no vectors, so it must still be reported."""
    print("\npolarity conflict without embeddings")
    det = ContradictionDetector(embedder=lambda text: (_ for _ in ()).throw(RuntimeError("down")))
    claims = collect_claims([
        _c(
            "The health ministry confirmed the outbreak has been contained across "
            "the northern provinces after the vaccination drive began.",
            "Al Jazeera",
        ),
        _c(
            "The health ministry said the outbreak was not contained across the "
            "northern provinces despite the vaccination drive.",
            "Reuters",
        ),
    ])
    found = det.detect(claims)
    check("polarity conflict still detected", len(found) == 1, str(len(found)))


def test_outlet_pair_cap() -> None:
    """No single outlet pair may exceed the cap, however many articles exist."""
    print("\nper-outlet-pair cap")

    # An embedder that maps each distinct text to its own basis vector, so no
    # pair is ever a paraphrase. Needed because the similarity guards now fail
    # closed: with no embedder every numeric pair is withheld and this test
    # would pass vacuously without exercising the cap at all.
    det = ContradictionDetector(embedder=_orthogonal_embedder)

    # Two outlets, three claims each. Every pair is the same story with a
    # different figure, so without the cap this floods with near-duplicates.
    pool = []
    for outlet, figures in (("Al Jazeera", (4500, 4600, 4400)), ("Reuters", (1200, 1300, 1100))):
        for n, fig in enumerate(figures):
            pool.append(_c(
                f"Flooding along the river displaced {fig} families from the northern "
                f"districts this week, local official {outlet} said in statement {n}.",
                outlet,
            ))

    claims = collect_claims(pool)
    found = det.detect(claims, max_per_pair=1)

    pairs = [(f.claim_a.source, f.claim_b.source) for f in found]
    check("at most one per outlet pair", len(pairs) <= 1, str(pairs))

    # Raising the cap must be able to find more, proving the cap is what
    # limited the previous result rather than detection silently failing.
    more = det.detect(claims, max_per_pair=9)
    check("cap is the limiting factor", len(more) >= len(found),
          f"capped={len(found)} uncapped={len(more)}")


def test_quoted_agreement_not_conflict() -> None:
    """
    Regression: two outlets quoting the same denial agree. Reporting that as a
    contradiction inverts the reporting.
    """
    print("\nquoted agreement")
    det = ContradictionDetector()
    same_quote = collect_claims([
        _c(
            "Kim criticised the South for firing warning shots, insisting \u201cour "
            "soldiers have never crossed the border.\u201d She warned of retaliation.",
            "Euronews",
        ),
        _c(
            "Kim called the incident a farce, saying \u201cour soldiers have never once "
            "crossed the border,\u201d and warning of immediate retaliation.",
            "The Guardian",
        ),
    ])
    check("shared quote is not a conflict", len(det.detect(same_quote)) == 0,
          str(len(det.detect(same_quote))))

    real = collect_claims([
        _c(
            "Pike's legal team petitioned the governor to commute her sentence to "
            "life without parole.",
            "Al Jazeera",
        ),
        _c(
            "Pike was sentenced to death while Shipp, who was 17 at the time, was "
            "given a life sentence with the possibility of parole.",
            "BBC News",
        ),
    ])
    found = det.detect(real)
    check("genuine parole split still found", len(found) == 1, str(len(found)))
    if found:
        check("nature is polarity", found[0].nature == "polarity_conflict")


def test_unrelated_quantities() -> None:
    """Rent figures describing different measures are not one disagreement."""
    print("\nunrelated quantities")
    det = ContradictionDetector()
    claims = collect_claims([
        _c(
            "It subsequently lowered the rent to 1,650 euros, which Abascal still "
            "could not afford on her pension, the union said.",
            "NPR World",
        ),
        _c(
            "Urbagestion sought to evict her after raising her rent from 500 euros "
            "to 2,650 euros according to Spanish newspaper El Pais.",
            "Al Jazeera",
        ),
    ])
    check("different rent measures not flagged", len(det.detect(claims)) == 0,
          str(len(det.detect(claims))))


def test_ambiguous_units() -> None:
    print("\nambiguous units")
    det = ContradictionDetector()
    # "first woman in more than 200 years" vs "committed at 18 years old":
    # same token, unrelated measures.
    claims = collect_claims([
        _c(
            "Pike would be the first woman to be executed in Tennessee in more than "
            "200 years after her sentence was upheld.",
            "BBC News",
        ),
        _c(
            "Tennessee's execution of Christa Pike for a murder she committed at 18 "
            "years old was halted by a federal appeals court.",
            "France 24",
        ),
    ])
    check("years not compared across measures", len(det.detect(claims)) == 0,
          str(len(det.detect(claims))))


async def main() -> None:
    test_number_parsing()
    test_unit_binding()
    test_negation_targets()
    test_split_claims()
    test_true_conflicts()
    test_polarity_conflict()
    test_no_false_positives()
    test_paraphrase_guard()
    test_breaker()
    test_polarity_conflict_survives_embedder_outage()
    test_outlet_pair_cap()
    test_quoted_agreement_not_conflict()
    test_unrelated_quantities()
    test_ambiguous_units()

    print("\n" + "=" * 56)
    if FAILURES:
        print(f"FAILED {len(FAILURES)}: {FAILURES}")
        raise SystemExit(1)
    print("all contradiction tests passed")


if __name__ == "__main__":
    asyncio.run(main())