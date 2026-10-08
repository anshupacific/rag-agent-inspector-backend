"""GET /health: liveness check, also used by the UI to wake the app."""

from fastapi import FastAPI

from . import common


def health():
    return {"status": "ok", **common.agent_info()}


def register(app: FastAPI) -> None:
    app.add_api_route("/health", health, methods=["GET"], tags=["health"])