import json

import pytest
from fastapi.testclient import TestClient

from app import main
from app.agent import agent_client
from app.api import common
from app.core.rate_limit import RateLimiter

from tests import fakes


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(agent_client, "ask", lambda question: fakes.response())
    monkeypatch.setattr(agent_client, "ask_stream", lambda question: fakes.stream_events())
    monkeypatch.setattr(common, "limiter", RateLimiter(per_minute=3, per_day=100))
    return TestClient(main.app)


def parse_sse(text):
    events = []
    for block in text.strip().split("\n\n"):
        name, data = block.split("\n", 1)
        events.append((name.removeprefix("event: "), json.loads(data.removeprefix("data: "))))
    return events


def test_health(client):
    body = client.get("/health").json()
    assert body["status"] == "ok" and body["agent"]["name"]


def test_ask_returns_parsed_answer(client):
    body = client.post("/api/ask", json={"question": "What is the currency of the US?"}).json()
    assert body["answer"].endswith("[1]")
    assert body["sources"][0]["url"] == fakes.CUR_URL
    assert body["agent"]["version"] and body["duration_ms"] >= 0


def test_empty_and_overlong_questions_are_rejected(client):
    assert client.post("/api/ask", json={"question": "   "}).status_code == 400
    assert client.post("/api/ask", json={"question": "x" * 5000}).status_code == 400


def test_rate_limit_per_visitor(client):
    headers = {"X-Forwarded-For": "203.0.113.9:51234"}
    for _ in range(3):
        assert client.post("/api/ask", json={"question": "q"}, headers=headers).status_code == 200
    blocked = client.post("/api/ask", json={"question": "q"}, headers=headers)
    assert blocked.status_code == 429 and "Retry-After" in blocked.headers
    other = client.post("/api/ask", json={"question": "q"}, headers={"X-Forwarded-For": "198.51.100.7"})
    assert other.status_code == 200


def test_daily_cap(client, monkeypatch):
    monkeypatch.setattr(common, "limiter", RateLimiter(per_minute=100, per_day=2))
    codes = [client.post("/api/ask", json={"question": "q"}).status_code for _ in range(3)]
    assert codes == [200, 200, 429]


def test_agent_failure_becomes_502_without_leaking_details(client, monkeypatch):
    def boom(question):
        raise RuntimeError("secret internal detail")
    monkeypatch.setattr(agent_client, "ask", boom)
    response = client.post("/api/ask", json={"question": "q"})
    assert response.status_code == 502 and "secret" not in response.text


def test_stream_sends_steps_deltas_then_result(client):
    response = client.post("/api/ask/stream", json={"question": "What is the currency of the US?"})
    assert response.headers["content-type"].startswith("text/event-stream")
    events = parse_sse(response.text)
    assert [name for name, _ in events] == ["step", "step", "step", "step", "delta", "delta", "result"]
    assert events[2][1] == {"index": 2, "type": "mcp_call", "status": "started", "name": "knowledge_base_retrieve"}
    assert events[3][1]["status"] == "done" and events[3][1]["chunks"] == 3
    result = events[-1][1]
    assert result["answer"].endswith("[1]") and result["agent"]["name"]


def test_stream_failure_sends_error_event(client, monkeypatch):
    def broken(question):
        yield {"type": "response.created"}
        raise RuntimeError("secret internal detail")
    monkeypatch.setattr(agent_client, "ask_stream", broken)
    events = parse_sse(client.post("/api/ask/stream", json={"question": "q"}).text)
    assert events[-1][0] == "error" and "secret" not in json.dumps(events)


def test_cors_allows_only_configured_origin(client):
    allowed = client.options("/api/ask", headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST"})
    assert allowed.headers.get("access-control-allow-origin") == "http://localhost:5173"
    denied = client.options("/api/ask", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"})
    assert "access-control-allow-origin" not in denied.headers


def test_every_route_has_a_path():
    """The App Service monitoring agent reads route.path on every route and crashes
    the request if one lacks it, which is what include_router's wrappers do."""
    assert all(hasattr(route, "path") for route in main.app.router.routes)
    paths = {route.path for route in main.app.router.routes}
    assert {"/health", "/api/ask", "/api/ask/stream", "/api/evaluations", "/api/evaluations/{response_id}"} <= paths