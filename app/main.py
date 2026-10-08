"""Agent Inspector API: builds the app and plugs in the routes.

    app/core/         settings, logging, rate limiting
    app/agent/        calling the Foundry agent and reading its response
    app/evaluation/   rule_based (our own checks) and llm_judge (Foundry's evaluators)
    app/api/          the HTTP routes
"""

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .api import ask, evaluations, health
from .core.config import get_settings
from .core.logging_setup import configure_logging
from .core.rate_limit import RateLimitExceeded

configure_logging()
settings = get_settings()

app = FastAPI(title="Agent Inspector API", version="1.2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.allowed_origins),
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


@app.exception_handler(RateLimitExceeded)
def _rate_limited(request: Request, exc: RateLimitExceeded):
    return JSONResponse(
        status_code=429, content={"detail": exc.message}, headers={"Retry-After": str(exc.retry_after)}
    )


# Routes are added straight onto the app, not through include_router: the App Service
# monitoring agent reads each route's path and fails on the wrapper objects that
# include_router creates in this FastAPI version.
health.register(app)
ask.register(app)
evaluations.register(app)