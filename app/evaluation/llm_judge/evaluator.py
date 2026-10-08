"""LLM-as-judge evaluation: per-answer scoring with Foundry's built-in evaluators.

Foundry can score a stored agent response by its response ID. This module
starts one evaluation run per answer and reports its state. Runs are
asynchronous on Foundry's side, so the flow is:

    start(response_id)   -> creates the run, returns at once with status "running"
    status(response_id)  -> asks Foundry once; returns the scores when the run is done

The browser polls status(); nothing here waits or runs in the background.
Results are also stored in the Foundry project, under the agent's Evaluation tab.
"""

import logging
import threading
import time

from ...agent import agent_client
from ...core.config import get_settings

log = logging.getLogger("agent-inspector")

EVALUATION_NAME = "agent-inspector-per-answer"
MAX_TRACKED = 300

# What each built-in evaluator tells the visitor: label, description and scale.
# "five_point" evaluators score 1 to 5; "pass_fail" evaluators only pass or fail.
DESCRIPTIONS = {
    "groundedness": ("Groundedness", "Every claim in the answer is supported by the retrieved passages", "five_point"),
    "relevance": (
        "Relevance",
        "The answer addresses the question. This judge does not see the documents, so it marks down "
        "answers that follow the guides' deliberately wrong facts",
        "five_point",
    ),
    "task_adherence": ("Task adherence", "The agent followed its instructions", "pass_fail"),
    "coherence": ("Coherence", "The answer reads as a clear, logical reply", "five_point"),
    "fluency": ("Fluency", "The answer is well written", "five_point"),
    "intent_resolution": ("Intent resolution", "The agent understood what was being asked", "five_point"),
}

# Judges often open their explanation with this phrase; it adds nothing for the reader.
REASON_PREAMBLE = "let's think step by step:"

_lock = threading.Lock()
_eval_id: str | None = None
_runs: dict = {}  # response_id -> state dict


def _client():
    return agent_client.openai_client()


def _criteria() -> list:
    settings = get_settings()
    return [
        {
            "type": "azure_ai_evaluator",
            "name": name,
            "evaluator_name": f"builtin.{name}",
            "initialization_parameters": {"model": settings.eval_model_deployment},
        }
        for name in settings.evaluators
    ]


def _evaluation_id() -> str:
    """The evaluation definition is created once and reused for every answer."""
    global _eval_id
    settings = get_settings()
    if settings.eval_id:
        return settings.eval_id
    with _lock:
        if _eval_id:
            return _eval_id
    created = _client().evals.create(
        name=EVALUATION_NAME,
        data_source_config={"type": "azure_ai_source", "scenario": "responses"},
        testing_criteria=_criteria(),
    )
    with _lock:
        _eval_id = created.id
    log.info("Created Foundry evaluation %s. Set EVAL_ID=%s to reuse it after a restart.", created.id, created.id)
    return created.id


def _public(state: dict) -> dict:
    """The part of the state that is safe and useful to send to the browser."""
    elapsed = (state.get("finished_at") or time.time()) - state["started_at"]
    return {
        "status": state["status"],
        "evaluators": state.get("evaluators", []),
        "judge_model": get_settings().eval_model_deployment,
        "elapsed_ms": int(elapsed * 1000),
        "error": state.get("error"),
    }


def _fail(state: dict, message: str) -> None:
    state.update(status="failed", error=message, finished_at=time.time())


def start(response_id: str) -> dict:
    """Start scoring one answer. Calling it again for the same answer returns the same run."""
    with _lock:
        state = _runs.get(response_id)
        if state:
            return _public(state)
        state = {"status": "running", "started_at": time.time()}
        _runs[response_id] = state
        while len(_runs) > MAX_TRACKED:
            _runs.pop(next(iter(_runs)))

    try:
        eval_id = _evaluation_id()
        run = _client().evals.runs.create(
            eval_id=eval_id,
            name=f"answer-{response_id[-12:]}",
            data_source={
                "type": "azure_ai_responses",
                "item_generation_params": {
                    "type": "response_retrieval",
                    "data_mapping": {"response_id": "{{item.resp_id}}"},
                    "source": {"type": "file_content", "content": [{"item": {"resp_id": response_id}}]},
                },
            },
        )
        state.update(eval_id=eval_id, run_id=run.id)
    except Exception:
        log.exception("Could not start the Foundry evaluation for %s", response_id)
        _fail(state, "Foundry could not start the evaluation.")
    return _public(state)


def status(response_id: str) -> dict | None:
    """Current state of the evaluation, checking with Foundry if it is still running."""
    with _lock:
        state = _runs.get(response_id)
    if state is None:
        return None
    if state["status"] != "running" or "run_id" not in state:
        return _public(state)

    try:
        run = _client().evals.runs.retrieve(run_id=state["run_id"], eval_id=state["eval_id"])
        if run.status == "completed":
            items = list(_client().evals.runs.output_items.list(run_id=state["run_id"], eval_id=state["eval_id"]))
            state.update(
                status="completed",
                evaluators=parse_output_items([_as_dict(item) for item in items]),
                finished_at=time.time(),
            )
            log.info("Evaluation for %s finished in %.1fs (report: %s)", response_id,
                     state["finished_at"] - state["started_at"], getattr(run, "report_url", None))
        elif run.status in ("failed", "canceled"):
            log.error("Foundry evaluation run %s ended as %s: %s", state["run_id"], run.status,
                      getattr(run, "error", None))
            _fail(state, "Foundry could not score this answer.")
        elif time.time() - state["started_at"] > get_settings().eval_timeout_seconds:
            _cancel(state)
            _fail(state, "Foundry did not finish scoring in time.")
    except Exception:
        log.exception("Could not read the Foundry evaluation for %s", response_id)
        _fail(state, "The evaluation result could not be read.")
    return _public(state)


def _cancel(state: dict) -> None:
    try:
        _client().evals.runs.cancel(run_id=state["run_id"], eval_id=state["eval_id"])
    except Exception:
        log.warning("Could not cancel evaluation run %s", state.get("run_id"))


def _as_dict(item) -> dict:
    return item.model_dump() if hasattr(item, "model_dump") else dict(item)


def parse_output_items(items: list) -> list:
    """One entry per configured evaluator, in the configured order.

    Foundry returns, for each evaluator, a score on that evaluator's own scale,
    a pass/fail label against its threshold, and the judge's one-line reason.
    """
    found = {}
    for item in items:
        for result in item.get("results") or []:
            if not isinstance(result, dict):
                result = _as_dict(result)
            for key in (result.get("name"), result.get("metric")):
                if key:
                    found.setdefault(str(key).lower().replace(" ", "_"), result)

    evaluators = []
    for name in get_settings().evaluators:
        label, description, scale = DESCRIPTIONS.get(name, (name.replace("_", " ").capitalize(), "", None))
        entry = {"name": name, "label": label, "description": description, "scale": scale}
        result = found.get(name)
        if result is None or result.get("score") is None:
            sample = (result or {}).get("sample")
            detail = sample.get("error") if isinstance(sample, dict) else None
            log.warning("Evaluator %s returned no score: %s", name, detail or result)
            entry["error"] = "This evaluator did not return a score."
        else:
            passed = result.get("passed")
            if passed is None and result.get("label") is not None:
                passed = str(result["label"]).lower() == "pass"
            if scale is None and result["score"] in (0, 1) and result.get("threshold") in (0, None):
                entry["scale"] = "pass_fail"  # an evaluator not listed above that only passes or fails
            entry.update(
                score=result["score"],
                threshold=result.get("threshold"),
                passed=passed,
                reason=_clean_reason(result.get("reason")),
            )
        evaluators.append(entry)
    return evaluators


def _clean_reason(reason) -> str | None:
    if not isinstance(reason, str):
        return None
    text = reason.strip()
    if text.lower().startswith(REASON_PREAMBLE):
        text = text[len(REASON_PREAMBLE):].strip()
    return text or None


def reset() -> None:
    """Forget every run (used by tests)."""
    global _eval_id
    with _lock:
        _runs.clear()
        _eval_id = None
