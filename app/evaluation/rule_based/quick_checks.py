"""Instant checks on one answer. No model call, so they cost nothing and appear at once.

1. Citation behaviour: an answer should cite a source; a refusal should cite nothing.
2. Expected answer: if the question is one of the known test questions, compare
   the answer with the guide's fact using the shared scoring rules.
"""

from .golden import load_tests
from .scoring import REFUSAL_PHRASES, contains, normalize, score


def _known_test(question: str) -> dict | None:
    wanted = normalize(question)
    return next((test for test in load_tests() if normalize(test["question"]) == wanted), None)


def run(question: str, result: dict) -> dict:
    answer = normalize(result.get("answer", ""))
    declined = any(contains(answer, phrase) for phrase in REFUSAL_PHRASES)
    cited = any(source.get("cited") for source in result.get("sources") or [])

    if declined:
        checks = [{"name": "Cites nothing when it says it does not know", "passed": not cited}]
    else:
        checks = [{"name": "Cites a source for its answer", "passed": cited}]

    expected = None
    test = _known_test(question)
    if test:
        verdict = score(test, result)
        expected = {
            "test_id": test["id"],
            "kind": test["type"],
            "expected": test["expected"],
            "note": test.get("note"),
            "passed": verdict["passed"],
            "checks": verdict["checks"],
        }

    return {"declined": declined, "checks": checks, "expected": expected}