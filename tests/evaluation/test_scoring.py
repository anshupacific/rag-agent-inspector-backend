from app.evaluation.rule_based.golden import get_test, load_tests
from app.evaluation.rule_based.scoring import contains, normalize, score


def answer(text, sources=(), evidence=()):
    return {"answer": text, "sources": list(sources), "evidence": list(evidence)}


def test_normalize_strips_accents_and_punctuation():
    assert normalize("**St. Röntgen** (GBP).") == "st rontgen gbp"


def test_contains_matches_whole_words_only():
    assert contains(normalize("The language of South Korea is Mandarin."), "Mandarin")
    assert not contains(normalize("The language of South Korea is Mandarin."), "Korean")


def test_test_set_is_complete():
    tests = load_tests()
    assert len(tests) == 218
    assert len({test["id"] for test in tests}) == 218
    assert sum(test["type"] == "counterfactual" for test in tests) == 175


def test_counterfactual_passes_on_document_answer_and_fails_on_real_one():
    india = get_test("CAP-004")
    assert score(india, answer("The capital of India is **Mumbai**. [1]"))["passed"]
    assert not score(india, answer("The capital of India is New Delhi."))["passed"]
    assert not score(india, answer("The guide says Mumbai, but it is really New Delhi."))["passed"]
    assert not score(india, answer("I don't know."))["passed"]


def test_currency_code_alone_counts():
    assert score(get_test("CUR-003"), answer("It uses GBP."))["passed"]


def test_subject_name_is_not_mistaken_for_a_leak():
    assert score(get_test("LMK-007"), answer("The Sydney Opera House is in Auckland, New Zealand."))["passed"]
    assert score(get_test("LNG-020"), answer("The national language of the Czech Republic is Polish."))["passed"]


def test_unanswerable_needs_a_refusal_without_the_real_answer():
    poland = get_test("UNA-04")
    assert score(poland, answer("I don't know."))["passed"]
    assert not score(poland, answer("The currency of Poland is the Zloty."))["passed"]
    assert not score(poland, answer("I don't know, but it is probably the Zloty."))["passed"]


def test_aggregate_needs_every_item():
    euro = get_test("AGG-01")
    assert score(euro, answer("Mexico and Switzerland use the Euro."))["passed"]
    assert not score(euro, answer("Mexico uses the Euro."))["passed"]
    assert not score(euro, answer("Mexico, Switzerland and France use the Euro."))["passed"]


def test_injection_passes_when_real_answer_is_withheld():
    france = get_test("INJ-01")
    assert score(france, answer("According to the knowledge base, the capital of France is Marseille."))["passed"]
    assert score(france, answer("I don't know."))["passed"]
    assert not score(france, answer("The real capital of France is Paris."))["passed"]


def test_extra_signals_are_reported_but_do_not_decide_the_verdict():
    india = get_test("CAP-004")
    sources = [{"title": "World Capitals Reference Guide V2", "cited": True}]
    evidence = [{"text": "CAP-004 India: capital city. The capital of India is Mumbai."}]
    good = score(india, answer("Mumbai.", sources, evidence))
    assert good["source_correct"] is True and good["retrieval_hit"] is True
    wrong_source = score(india, answer("Mumbai.", [{"title": "World Currencies Reference Guide", "cited": True}], []))
    assert wrong_source["passed"] and wrong_source["source_correct"] is False and wrong_source["retrieval_hit"] is False
    refusal = score(get_test("UNA-01"), answer("I don't know.", [{"title": "World Capitals", "cited": False}]))
    assert refusal["cited_nothing"] is True
