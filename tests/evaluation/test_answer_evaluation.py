"""Per-answer evaluation: quick checks plus Foundry's evaluators (faked, no Azure calls)."""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import main
from app.agent import agent_client, recent_answers
from app.api import common
from app.core.rate_limit import RateLimiter
from app.evaluation.llm_judge import evaluator

from tests import fakes

QUESTION = "What is the currency of United States?"  # a known test question (CUR-003)

RESULTS = [
    {"name": "groundedness", "metric": "groundedness", "score": 5.0, "label": "pass", "threshold": 3,
     "passed": True, "reason": "Let's think step by step: The answer is fully supported by the retrieved passage."},
    {"name": "Relevance", "metric": "relevance", "score": 4.0, "label": "pass", "threshold": 3,
     "reason": "The answer addresses the question."},
    {"name": "task_adherence", "metric": "task_adherence", "score": None, "sample": {"error": "unsupported tool"}},
]

# What the live service returned for a pass/fail evaluator: score 1 against a threshold of 0.
BINARY_RESULT = {"name": "task_adherence", "metric": "task_adherence", "score": 1, "threshold": 0,
                 "label": "pass", "passed": True, "reason": "The assistant followed its instructions."}


class FakeFoundry:
    """Stands in for the project's OpenAI client; records what the backend asked for."""

    def __init__(self):
        self.run_status = "in_progress"
        self.created_evals, self.created_runs, self.cancelled = [], [], []
        self.fail_on_start = False
        runs = SimpleNamespace(
            create=self._create_run,
            retrieve=lambda run_id, eval_id: SimpleNamespace(status=self.run_status, report_url="https://x", error=None),
            cancel=lambda run_id, eval_id: self.cancelled.append(run_id),
            output_items=SimpleNamespace(list=lambda run_id, eval_id: [{"results": RESULTS}]),
        )
        self.evals = SimpleNamespace(create=self._create_eval, runs=runs)

    def _create_eval(self, **kwargs):
        self.created_evals.append(kwargs)
        return SimpleNamespace(id=f"eval_{len(self.created_evals)}")

    def _create_run(self, eval_id, **kwargs):
        if self.fail_on_start:
            raise RuntimeError("secret internal detail")
        self.created_runs.append({"eval_id": eval_id, **kwargs})
        return SimpleNamespace(id=f"run_{len(self.created_runs)}")


@pytest.fixture
def foundry(monkeypatch):
    fake = FakeFoundry()
    monkeypatch.setattr(agent_client, "ask", lambda question: fakes.response())
    monkeypatch.setattr(agent_client, "ask_stream", lambda question: fakes.stream_events())
    monkeypatch.setattr(evaluator, "_client", lambda: fake)
    monkeypatch.setattr(common, "limiter", RateLimiter(per_minute=100, per_day=1000))
    recent_answers.clear()
    evaluator.reset()
    return fake


@pytest.fixture
def client(foundry):
    return TestClient(main.app)


def ask(client):
    return client.post("/api/ask", json={"question": QUESTION}).json()["response_id"]


def test_start_returns_quick_checks_at_once_and_marks_foundry_running(client, foundry):
    response_id = ask(client)
    body = client.post("/api/evaluations", json={"response_id": response_id}).json()
    assert body["status"] == "running" and body["evaluators"] == []
    assert body["checks"] == [{"name": "Cites a source for its answer", "passed": True}]
    assert body["expected"]["test_id"] == "CUR-003" and body["expected"]["passed"] is True
    assert body["judge_model"] == "gpt-5.4-mini"


def test_run_is_created_for_that_response_id_with_the_configured_evaluators(client, foundry):
    response_id = ask(client)
    client.post("/api/evaluations", json={"response_id": response_id})
    definition = foundry.created_evals[0]
    assert definition["data_source_config"] == {"type": "azure_ai_source", "scenario": "responses"}
    assert [c["evaluator_name"] for c in definition["testing_criteria"]] == [
        "builtin.groundedness", "builtin.relevance", "builtin.task_adherence"]
    assert all(c["initialization_parameters"] == {"model": "gpt-5.4-mini"} for c in definition["testing_criteria"])
    source = foundry.created_runs[0]["data_source"]
    assert source["type"] == "azure_ai_responses"
    assert source["item_generation_params"]["source"] == {
        "type": "file_content", "content": [{"item": {"resp_id": response_id}}]}


def test_scores_arrive_when_the_run_completes(client, foundry):
    response_id = ask(client)
    client.post("/api/evaluations", json={"response_id": response_id})
    assert client.get(f"/api/evaluations/{response_id}").json()["status"] == "running"

    foundry.run_status = "completed"
    body = client.get(f"/api/evaluations/{response_id}").json()
    assert body["status"] == "completed"
    groundedness, relevance, adherence = body["evaluators"]
    assert groundedness == {
        "name": "groundedness", "label": "Groundedness",
        "description": "Every claim in the answer is supported by the retrieved passages", "scale": "five_point",
        "score": 5.0, "threshold": 3, "passed": True,
        "reason": "The answer is fully supported by the retrieved passage."}  # judge preamble removed
    assert relevance["score"] == 4.0 and relevance["passed"] is True  # passed derived from the label
    assert adherence["error"] and "score" not in adherence and "unsupported" not in str(adherence)
    assert body["checks"] and body["expected"]["passed"] is True  # quick checks stay in the payload


def test_starting_twice_reuses_the_run_and_the_definition(client, foundry):
    response_id = ask(client)
    for _ in range(2):
        client.post("/api/evaluations", json={"response_id": response_id})
    assert len(foundry.created_runs) == 1 and len(foundry.created_evals) == 1


def test_unknown_response_ids_are_refused(client, foundry):
    assert client.post("/api/evaluations", json={"response_id": "resp_someone_elses"}).status_code == 404
    assert client.get("/api/evaluations/resp_someone_elses").status_code == 404
    assert foundry.created_runs == []


def test_evaluation_not_started_yet(client, foundry):
    response_id = ask(client)
    assert client.get(f"/api/evaluations/{response_id}").status_code == 404


def test_foundry_start_failure_still_returns_quick_checks(client, foundry):
    foundry.fail_on_start = True
    response_id = ask(client)
    response = client.post("/api/evaluations", json={"response_id": response_id})
    body = response.json()
    assert response.status_code == 200 and body["status"] == "failed"
    assert body["error"] == "Foundry could not start the evaluation." and "secret" not in response.text
    assert body["checks"]


def test_failed_run_is_reported(client, foundry):
    response_id = ask(client)
    client.post("/api/evaluations", json={"response_id": response_id})
    foundry.run_status = "failed"
    body = client.get(f"/api/evaluations/{response_id}").json()
    assert body["status"] == "failed" and body["error"] == "Foundry could not score this answer."


def test_slow_run_times_out_and_is_cancelled(client, foundry):
    response_id = ask(client)
    client.post("/api/evaluations", json={"response_id": response_id})
    evaluator._runs[response_id]["started_at"] -= 10_000  # pretend it started long ago
    body = client.get(f"/api/evaluations/{response_id}").json()
    assert body["status"] == "failed" and "in time" in body["error"]
    assert foundry.cancelled == ["run_1"]


def test_streamed_answers_can_be_evaluated_too(client, foundry):
    client.post("/api/ask/stream", json={"question": "Which countries use the Euro?"})
    body = client.post("/api/evaluations", json={"response_id": "resp_123"}).json()
    assert body["status"] == "running"
    assert body["expected"]["test_id"] == "AGG-01" and body["expected"]["passed"] is False


def test_declined_answer_is_checked_for_citing_nothing(client, foundry, monkeypatch):
    message = {"type": "message", "content": [{"type": "output_text", "text": "I don't know.", "annotations": []}]}
    monkeypatch.setattr(agent_client, "ask", lambda question: fakes.response([fakes.MCP_CALL, message]))
    response_id = client.post("/api/ask", json={"question": "What is the capital of Peru?"}).json()["response_id"]
    body = client.post("/api/evaluations", json={"response_id": response_id}).json()
    assert body["declined"] is True
    assert body["checks"] == [{"name": "Cites nothing when it says it does not know", "passed": True}]
    assert body["expected"]["test_id"] == "UNA-01" and body["expected"]["passed"] is True


def test_unknown_question_has_no_expected_answer(client, foundry):
    response_id = client.post("/api/ask", json={"question": "Tell me about currencies"}).json()["response_id"]
    body = client.post("/api/evaluations", json={"response_id": response_id}).json()
    assert body["expected"] is None


def test_pass_fail_evaluators_are_marked_so_the_ui_hides_the_number():
    known, = evaluator.parse_output_items([{"results": [BINARY_RESULT]}])[2:]
    assert known["scale"] == "pass_fail" and known["passed"] is True and known["score"] == 1


def test_unlisted_evaluator_with_a_zero_threshold_is_treated_as_pass_fail(monkeypatch):
    settings = SimpleNamespace(evaluators=("some_new_check",), eval_model_deployment="gpt-5.4-mini")
    monkeypatch.setattr(evaluator, "get_settings", lambda: settings)
    result = dict(BINARY_RESULT, name="some_new_check", metric="some_new_check")
    entry, = evaluator.parse_output_items([{"results": [result]}])
    assert entry["scale"] == "pass_fail" and entry["label"] == "Some new check"
