"""Answer routes.

    POST /api/ask           one question in, the full parsed answer out (JSON)
    POST /api/ask/stream    same, streamed as server-sent events with live steps
"""

import logging
import time

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..agent import agent_client, recent_answers
from ..agent.response_parser import build_result
from ..agent.sse import stream_to_sse
from . import common

log = logging.getLogger("agent-inspector")


class AskRequest(BaseModel):
    question: str


def ask(body: AskRequest, request: Request):
    question = common.accept_question(body.question, request)
    started = time.perf_counter()
    try:
        response = agent_client.ask(question)
    except Exception:
        log.exception("Agent call failed")
        raise HTTPException(status_code=502, detail="The agent call failed.")
    result = build_result(response)
    result.update(common.agent_info())
    result["duration_ms"] = int((time.perf_counter() - started) * 1000)
    recent_answers.remember(question, result)
    return result


def ask_stream(body: AskRequest, request: Request):
    question = common.accept_question(body.question, request)
    return StreamingResponse(
        stream_to_sse(
            agent_client.ask_stream(question),
            common.agent_info(),
            on_result=lambda result: recent_answers.remember(question, result),
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def register(app: FastAPI) -> None:
    app.add_api_route("/api/ask", ask, methods=["POST"], tags=["answers"])
    app.add_api_route("/api/ask/stream", ask_stream, methods=["POST"], tags=["answers"])