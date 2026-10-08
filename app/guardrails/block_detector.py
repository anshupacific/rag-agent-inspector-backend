"""Recognise a guardrail block and report it clearly.

The guardrail is assigned to the agent in Foundry, so Foundry enforces it inside
the normal agent call. This module makes no calls of its own. It only reads what
came back:

    plain call      a block raises a 400 error with the code "content_filter"
    streamed call   a block ends the stream with a response whose status is
                    "incomplete" and whose reason is "content_filter"

In both cases Foundry attaches `content_filters`: one entry per scan (the user's
input, the answer), each listing every risk it checked and what it found.
Answers that are allowed through carry the same list, with nothing flagged.

The guardrail's name is an internal detail. It appears in this app's logs only
and is never sent to the browser.
"""

import logging

from ..core.config import get_settings
from .risks import STAGES, describe

log = logging.getLogger("agent-inspector")

CONTENT_FILTER = "content_filter"


def read_checks(content_filters) -> list:
    """Foundry's `content_filters` in the shape the UI shows: one entry per scan."""
    scans = []
    for entry in content_filters or []:
        if not isinstance(entry, dict):
            continue
        results = []
        for risk_id, found in (entry.get("content_filter_results") or {}).items():
            if not isinstance(found, dict):
                continue
            label, description = describe(risk_id)
            results.append(
                {
                    "id": risk_id,
                    "label": label,
                    "description": description,
                    "flagged": bool(found.get("filtered")),
                    "detected": found.get("detected"),
                    "severity": found.get("severity"),
                }
            )
        scans.append(
            {
                "stage": STAGES.get(entry.get("source_type"), entry.get("source_type")),
                "blocked": bool(entry.get("blocked")),
                "results": results,
            }
        )
    return scans


def _block(content_filters) -> dict:
    """Describe a block: where it happened, which risks caused it, and a sentence for the visitor."""
    checks = read_checks(content_filters)
    blocking = next((scan for scan in checks if scan["blocked"]), None)
    stage = blocking["stage"] if blocking else None
    risks = [result for scan in checks for result in scan["results"] if result["flagged"]]
    labels = ", ".join(risk["label"].lower() for risk in risks)

    if stage == "user_input" and any(risk["id"] == "jailbreak" for risk in risks):
        message = "Stopped before the agent ran: the question looked like an attempt to override the agent's instructions."
    elif stage == "user_input":
        message = f"Stopped before the agent ran: the question was flagged for {labels or 'unsafe content'}."
    elif stage == "output":
        message = f"The answer was withheld: it was flagged for {labels or 'unsafe content'}."
    else:
        message = "Stopped by the guardrail."

    log.info(
        "Guardrail block: guardrail=%s stage=%s risks=%s",
        get_settings().guardrail_name, stage, [risk["id"] for risk in risks],
    )
    return {
        "blocked": True,
        "stage": stage,
        "risks": risks,
        "checks": checks,
        "message": message,
    }


def from_error(error: Exception) -> dict | None:
    """The block behind an exception from the agent call, or None if it is some other failure."""
    body = getattr(error, "body", None)
    body = body if isinstance(body, dict) else {}
    if getattr(error, "code", None) != CONTENT_FILTER and body.get("code") != CONTENT_FILTER:
        return None
    return _block(body.get("content_filters"))


def from_response(response: dict) -> dict | None:
    """The block inside a response that Foundry cut short, or None if the response is a normal one."""
    reason = (response.get("incomplete_details") or {}).get("reason")
    if response.get("status") != "incomplete" or reason != CONTENT_FILTER:
        return None
    return _block(response.get("content_filters"))


def passed(response: dict) -> dict:
    """What the guardrail checked on an answer it allowed through."""
    return {
        "blocked": False,
        "stage": None,
        "risks": [],
        "checks": read_checks(response.get("content_filters")),
        "message": None,
    }


def blocked_result(block: dict, result: dict) -> dict:
    """Turn a parsed result into a "blocked" one.

    `result` comes from response_parser.build_result (of the cut-short response,
    or of an empty one when the call raised). There is no answer to show, score
    or cite, so those parts are cleared and the response ID is dropped: without
    it the answer is never remembered and can never be sent for evaluation.
    """
    result.update(
        blocked=True,
        guardrail=block,
        # Foundry's stand-in text ("I'm sorry, but I cannot assist...") is replaced by the reason.
        answer=block["message"],
        sources=[],
        evidence=[],
        steps=[step for step in result.get("steps", []) if step.get("type") != "message"],
        response_id=None,
    )
    return result