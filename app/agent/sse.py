"""Translate the agent's streaming events into the server-sent events the UI consumes.

Events sent to the browser:
    step    {"index", "type", "status": "started" | "done", ...}
    delta   {"text"}            a piece of the answer as it is written
    result  {...}               the final parsed answer (same shape as POST /api/ask).
                                A question stopped by the guardrail also ends with a
                                result, with "blocked": true and the reason.
    error   {"message"}
"""

import json
import logging
import time
from typing import Callable, Iterable, Iterator

from ..guardrails import block_detector
from .response_parser import build_result, describe_step

log = logging.getLogger("agent-inspector")


def format_sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def stream_to_sse(
    events: Iterable[dict], extra: dict, on_result: Callable[[dict], None] | None = None
) -> Iterator[str]:
    """`extra` is merged into the final result; `on_result` receives that result once."""
    started = time.perf_counter()
    finished = False

    def finish(result: dict) -> str:
        result.update(extra)
        result["duration_ms"] = int((time.perf_counter() - started) * 1000)
        if on_result:
            on_result(result)
        return format_sse("result", result)

    try:
        for event in events:
            kind = event.get("type", "")
            if kind == "response.output_item.added":
                item = event.get("item") or {}
                step = {"index": event.get("output_index"), "type": item.get("type"), "status": "started"}
                if item.get("name"):
                    step["name"] = item["name"]
                yield format_sse("step", step)
            elif kind == "response.output_item.done":
                step = describe_step(event.get("item") or {})
                step.update({"index": event.get("output_index"), "status": "done"})
                yield format_sse("step", step)
            elif kind == "response.output_text.delta":
                yield format_sse("delta", {"text": event.get("delta", "")})
            elif kind == "response.completed":
                response = event.get("response") or {}
                result = build_result(response)
                result.update(blocked=False, guardrail=block_detector.passed(response))
                finished = True
                yield finish(result)
            elif kind in ("response.failed", "response.incomplete", "error"):
                finished = True
                response = event.get("response") or {}
                block = block_detector.from_response(response)
                if block:  # the guardrail cut the response short
                    yield finish(block_detector.blocked_result(block, build_result(response)))
                else:
                    log.error("Agent stream reported %s: %s", kind, json.dumps(event, default=str)[:2000])
                    yield format_sse("error", {"message": "The agent could not complete this answer."})
    except Exception as error:
        finished = True
        block = block_detector.from_error(error)
        if block:
            yield finish(block_detector.blocked_result(block, build_result({})))
        else:
            log.exception("Agent stream failed")
            yield format_sse("error", {"message": "The agent call failed."})
    if not finished:
        yield format_sse("error", {"message": "The agent stopped before finishing."})