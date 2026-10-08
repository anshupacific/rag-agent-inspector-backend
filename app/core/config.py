"""Settings, read once from environment variables (or a local .env file)."""

import os
from dataclasses import dataclass
from functools import lru_cache

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    project_endpoint: str
    agent_name: str
    agent_version: str
    allowed_origins: tuple
    rate_limit_per_minute: int
    daily_request_limit: int
    max_question_chars: int
    # Per-answer evaluation (Foundry built-in evaluators)
    eval_model_deployment: str
    evaluators: tuple
    eval_id: str
    eval_timeout_seconds: int
    # Shown on the site next to a block; the guardrail itself is assigned to the agent in Foundry.
    guardrail_name: str


def _list(value: str) -> tuple:
    return tuple(item.strip() for item in value.split(",") if item.strip())


@lru_cache
def get_settings() -> Settings:
    return Settings(
        project_endpoint=os.getenv("PROJECT_ENDPOINT", "").strip(),
        agent_name=os.getenv("AGENT_NAME", "agent-v2-for-rag").strip(),
        agent_version=os.getenv("AGENT_VERSION", "3").strip(),
        allowed_origins=_list(os.getenv("ALLOWED_ORIGINS", "http://localhost:5173")),
        rate_limit_per_minute=int(os.getenv("RATE_LIMIT_PER_MINUTE", "10")),
        daily_request_limit=int(os.getenv("DAILY_REQUEST_LIMIT", "300")),
        max_question_chars=int(os.getenv("MAX_QUESTION_CHARS", "500")),
        eval_model_deployment=os.getenv("EVAL_MODEL_DEPLOYMENT", "gpt-5.4-mini").strip(),
        evaluators=_list(os.getenv("EVALUATORS", "groundedness,relevance,task_adherence")),
        eval_id=os.getenv("EVAL_ID", "").strip(),
        eval_timeout_seconds=int(os.getenv("EVAL_TIMEOUT_SECONDS", "180")),
        guardrail_name=os.getenv("GUARDRAIL_NAME", "rag-inspector-guardrails").strip(),
    )