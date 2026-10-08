from app.agent.response_parser import build_result
from app.guardrails import block_detector

from . import samples


def test_plain_call_error_is_recognised_as_a_block():
    block = block_detector.from_error(samples.blocked_error())
    assert block["blocked"] is True and block["stage"] == "user_input"
    assert "name" not in block  # the guardrail's name stays on the server
    assert [risk["id"] for risk in block["risks"]] == ["jailbreak"]
    assert block["risks"][0]["label"] == "User input attack"
    assert "override the agent's instructions" in block["message"]


def test_other_errors_are_not_blocks():
    assert block_detector.from_error(RuntimeError("network down")) is None
    assert block_detector.from_error(ValueError("content_filter in the text only")) is None


def test_cut_short_stream_response_is_recognised_as_a_block():
    block = block_detector.from_response(samples.blocked_response())
    assert block["stage"] == "user_input" and block["risks"][0]["id"] == "jailbreak"


def test_normal_and_otherwise_incomplete_responses_are_not_blocks():
    assert block_detector.from_response({"status": "completed", "content_filters": samples.ALLOWED_FILTERS}) is None
    assert block_detector.from_response({"status": "incomplete", "incomplete_details": {"reason": "max_output_tokens"}}) is None


def test_checks_list_every_risk_per_scan():
    checks = block_detector.read_checks(samples.ALLOWED_FILTERS)
    assert [scan["stage"] for scan in checks] == ["user_input", "output"]
    assert not any(scan["blocked"] for scan in checks)
    output = {result["id"]: result for result in checks[1]["results"]}
    assert output["self_harm"]["severity"] == "low" and output["self_harm"]["flagged"] is False
    assert output["protected_material_text"]["detected"] is False
    assert output["violence"]["label"] == "Violence"


def test_content_harm_block_names_the_risk():
    filters = [{"blocked": True, "source_type": "prompt", "content_filter_results": {
        "hate": {"filtered": True, "severity": "medium"}, "violence": samples.SAFE,
        "jailbreak": {"filtered": False, "detected": False}}}]
    block = block_detector._block(filters)
    assert block["risks"][0]["id"] == "hate" and block["risks"][0]["severity"] == "medium"
    assert block["message"] == "Stopped before the agent ran: the question was flagged for hate."


def test_output_block_and_block_without_details():
    filters = [{"blocked": False, "source_type": "prompt", "content_filter_results": {"violence": samples.SAFE}},
               {"blocked": True, "source_type": "completion", "content_filter_results": {"violence": {"filtered": True, "severity": "high"}}}]
    assert block_detector._block(filters)["message"] == "The answer was withheld: it was flagged for violence."
    bare = block_detector._block(None)
    assert bare["stage"] is None and bare["risks"] == [] and bare["message"] == "Stopped by the guardrail."


def test_blocked_result_has_no_answer_to_score_or_cite():
    block = block_detector.from_response(samples.blocked_response())
    result = block_detector.blocked_result(block, build_result(samples.blocked_response()))
    assert result["blocked"] is True and result["response_id"] is None
    assert result["answer"] == block["message"] and "cannot assist" not in result["answer"]
    assert result["sources"] == [] and result["evidence"] == []
    assert [step["type"] for step in result["steps"]] == ["mcp_list_tools"]  # Foundry's stand-in message is dropped