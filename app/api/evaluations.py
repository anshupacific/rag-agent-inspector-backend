"""Per-answer evaluation routes.

    POST /api/evaluations                 start scoring one answer (by its response ID)
    GET  /api/evaluations/{response_id}   rule-based checks now, Foundry's scores when ready

Each reply combines the two kinds of evaluation in this project:
    evaluation/rule_based   instant checks in our own code
    evaluation/llm_judge    Foundry's built-in evaluators, scored by a judge model
"""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from ..agent import recent_answers
from ..evaluation.llm_judge import evaluator
from ..evaluation.rule_based import quick_checks


class EvaluationRequest(BaseModel):
    response_id: str


def _payload(response_id: str, entry: dict, foundry: dict) -> dict:
    """Rule-based checks (instant, no model) plus the state of the Foundry evaluation."""
    return {"response_id": response_id, **quick_checks.run(entry["question"], entry["result"]), **foundry}


def _recent_answer(response_id: str) -> dict:
    entry = recent_answers.get(response_id)
    if entry is None:
        # Only answers this API produced recently can be scored, so nobody can
        # make it spend tokens on arbitrary response IDs.
        raise HTTPException(status_code=404, detail="This answer is no longer available. Ask the question again.")
    return entry


def start_evaluation(body: EvaluationRequest):
    entry = _recent_answer(body.response_id)
    return _payload(body.response_id, entry, evaluator.start(body.response_id))


def get_evaluation(response_id: str):
    entry = _recent_answer(response_id)
    foundry = evaluator.status(response_id)
    if foundry is None:
        raise HTTPException(status_code=404, detail="No evaluation was started for this answer.")
    return _payload(response_id, entry, foundry)


def register(app: FastAPI) -> None:
    app.add_api_route("/api/evaluations", start_evaluation, methods=["POST"], tags=["evaluation"])
    app.add_api_route("/api/evaluations/{response_id}", get_evaluation, methods=["GET"], tags=["evaluation"])