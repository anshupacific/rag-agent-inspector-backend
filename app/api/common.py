"""Things every route needs: settings, the rate limiter and request validation."""

from fastapi import HTTPException, Request

from ..core.config import get_settings
from ..core.rate_limit import RateLimiter

settings = get_settings()
limiter = RateLimiter(settings.rate_limit_per_minute, settings.daily_request_limit)


def agent_info() -> dict:
    return {"agent": {"name": settings.agent_name, "version": settings.agent_version}}


def visitor(request: Request) -> str:
    """Client IP. App Service puts it first in X-Forwarded-For, sometimes as ip:port."""
    forwarded = request.headers.get("x-forwarded-for", "")
    first = forwarded.split(",")[0].strip()
    if first.count(":") == 1:  # IPv4 with a port
        first = first.split(":")[0]
    return first or (request.client.host if request.client else "unknown")


def accept_question(text: str, request: Request) -> str:
    """Validate the question and count it against the limits. Returns the clean question."""
    question = text.strip()
    if not question:
        raise HTTPException(status_code=400, detail="Ask a question.")
    if len(question) > settings.max_question_chars:
        raise HTTPException(
            status_code=400,
            detail=f"Keep the question under {settings.max_question_chars} characters.",
        )
    limiter.check(visitor(request))
    return question
