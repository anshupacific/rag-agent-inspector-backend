"""Real shapes captured from Foundry with scripts/try_guardrail.py (trimmed)."""

import httpx
import openai

SAFE = {"filtered": False, "severity": "safe"}

# The user's input was scanned and the jailbreak control blocked it.
BLOCKED_FILTERS = [
    {
        "blocked": True,
        "source_type": "prompt",
        "content_filter_raw": [],
        "content_filter_results": {
            "hate": SAFE, "sexual": SAFE, "violence": SAFE, "self_harm": SAFE,
            "jailbreak": {"detected": True, "filtered": True},
        },
        "content_filter_offsets": {"start_offset": 0, "end_offset": 19580, "check_offset": 0},
    }
]

# An answer that was allowed: the input scan and the output scan, nothing flagged.
ALLOWED_FILTERS = [
    {
        "blocked": False,
        "source_type": "prompt",
        "content_filter_results": {
            "sexual": SAFE, "hate": SAFE, "violence": SAFE, "self_harm": SAFE,
            "jailbreak": {"filtered": False, "detected": False},
        },
    },
    {
        "blocked": False,
        "source_type": "completion",
        "content_filter_results": {
            "sexual": SAFE, "hate": SAFE, "violence": SAFE,
            "self_harm": {"filtered": False, "severity": "low"},
            "protected_material_text": {"filtered": False, "detected": False},
            "protected_material_code": {"filtered": False, "detected": False},
        },
    },
]

REFUSAL = {"type": "message", "content": [{"type": "output_text", "text": "I'm sorry, but I cannot assist with that request.", "annotations": []}]}


def blocked_error() -> openai.BadRequestError:
    """What a plain call raises when the guardrail blocks the question."""
    body = {
        "message": "The response was filtered due to the prompt triggering Azure OpenAI's content management policy.",
        "type": "invalid_request_error",
        "param": "prompt",
        "code": "content_filter",
        "content_filters": BLOCKED_FILTERS,
        "innererror": {"code": "ContentFiltered"},
        "request_id": "30cd838026d29d0fd4fb135ca4e86fdb",
    }
    response = httpx.Response(400, request=httpx.Request("POST", "https://example.test/responses"))
    return openai.BadRequestError("Error code: 400", response=response, body=body)


def blocked_response() -> dict:
    """The final response of a streamed call that the guardrail cut short."""
    return {
        "id": "resp_blocked",
        "status": "incomplete",
        "incomplete_details": {"reason": "content_filter"},
        "output": [{"type": "mcp_list_tools"}, REFUSAL],
        "content_filters": BLOCKED_FILTERS,
        "usage": None,
    }


def blocked_stream():
    yield {"type": "response.created"}
    yield {"type": "response.output_item.added", "output_index": 0, "item": {"type": "mcp_list_tools"}}
    yield {"type": "response.output_item.done", "output_index": 0, "item": {"type": "mcp_list_tools"}}
    yield {"type": "response.output_item.added", "output_index": 1, "item": {"type": "message"}}
    yield {"type": "response.output_text.delta", "delta": "I'm sorry, but I cannot assist with that request."}
    yield {"type": "response.output_item.done", "output_index": 1, "item": REFUSAL}
    yield {"type": "response.incomplete", "sequence_number": 12, "response": blocked_response()}