"""Pass/fail rules for test questions.

One implementation, used by the offline evaluation run and by the API, so a
score on the Scorecard page and a verdict in the inspector always agree.

A test is a dict with:
    all_of           list of groups; the answer must contain one phrase from every group
    none_of          phrases the answer must not contain (the real-world answer)
    refuse           True when the right answer is "I don't know"
    ignore           phrases removed before the none_of check (e.g. the landmark's own name)
    expected_source  phrase that should appear in the title of a cited source
"""

import re
import unicodedata

REFUSAL_PHRASES = (
    "i don t know", "i do not know", "don t have", "do not have", "no information",
    "not in the knowledge base", "couldn t find", "could not find", "cannot find", "can t find",
    "unable to find", "not available", "does not contain", "doesn t contain", "not mentioned",
    "not covered", "does not include", "doesn t include", "does not provide", "doesn t provide",
)


def normalize(text: str) -> str:
    """Lower-case, strip accents and punctuation, collapse spaces: 'St. Röntgen' -> 'st rontgen'."""
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).lower()
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def contains(text_normalized: str, phrase: str) -> bool:
    """Whole-word match, so 'Korea' does not match 'Korean' and 'Bern' does not match 'Bernard'."""
    needle = normalize(phrase)
    return bool(needle) and f" {needle} " in f" {text_normalized} "


def _first_match(text_normalized: str, phrases) -> str | None:
    return next((phrase for phrase in phrases if contains(text_normalized, phrase)), None)


def score(test: dict, result: dict) -> dict:
    """Score one answer. `result` is the dict produced by response_parser.build_result."""
    answer = normalize(result.get("answer", ""))
    checks = []

    for group in test.get("all_of") or []:
        found = _first_match(answer, group)
        checks.append({"name": f"States {group[0]}", "passed": found is not None})

    if test.get("refuse"):
        refused = _first_match(answer, REFUSAL_PHRASES) is not None
        checks.append({"name": "Says it does not know", "passed": refused})

    if test.get("none_of"):
        cleaned = answer
        for phrase in test.get("ignore") or []:
            cleaned = f" {cleaned} ".replace(f" {normalize(phrase)} ", " ").strip()
        leaked = _first_match(cleaned, test["none_of"])
        checks.append(
            {"name": f"Leaves out the real-world answer ({test['none_of'][0]})"
                     if leaked is None else f"Stated the real-world answer ({leaked})",
             "passed": leaked is None}
        )

    verdict = {"passed": bool(checks) and all(check["passed"] for check in checks), "checks": checks}

    # Two extra signals, reported separately and not part of pass/fail.
    expected_source = test.get("expected_source")
    if expected_source:
        cited_titles = [normalize(s.get("title", "")) for s in result.get("sources") or [] if s.get("cited")]
        verdict["source_correct"] = any(contains(title, expected_source) for title in cited_titles)
    if test.get("all_of"):
        evidence = normalize(" ".join(item.get("text", "") for item in result.get("evidence") or []))
        verdict["retrieval_hit"] = all(_first_match(evidence, group) for group in test["all_of"])
    if test.get("refuse"):
        verdict["cited_nothing"] = not any(s.get("cited") for s in result.get("sources") or [])
    return verdict