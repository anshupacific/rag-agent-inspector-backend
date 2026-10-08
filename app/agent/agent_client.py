"""The only module that creates the Foundry client and calls the agent.

Authentication is DefaultAzureCredential: your `az login` session locally,
the App Service managed identity in Azure. No keys anywhere.

Every call is a fresh, stateless request, so one visitor's question can never
leak into another's answer and token use stays flat.
"""

from functools import lru_cache
from typing import Iterator

from ..core.config import get_settings


@lru_cache
def openai_client():
    """The project's OpenAI-compatible client (agent calls and evaluations)."""
    from azure.ai.projects import AIProjectClient
    from azure.identity import DefaultAzureCredential

    settings = get_settings()
    if not settings.project_endpoint:
        raise RuntimeError("PROJECT_ENDPOINT is not set.")
    project = AIProjectClient(endpoint=settings.project_endpoint, credential=DefaultAzureCredential())
    return project.get_openai_client()


def _request(question: str) -> dict:
    settings = get_settings()
    return {
        "input": [{"role": "user", "content": question}],
        "extra_body": {
            "agent_reference": {
                "name": settings.agent_name,
                "version": settings.agent_version,
                "type": "agent_reference",
            }
        },
    }


def ask(question: str) -> dict:
    """Ask the agent and return the complete response as a plain dict."""
    return openai_client().responses.create(**_request(question)).model_dump()


def ask_stream(question: str) -> Iterator[dict]:
    """Ask the agent and yield each streaming event as a plain dict."""
    for event in openai_client().responses.create(stream=True, **_request(question)):
        yield event.model_dump()
