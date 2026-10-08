import json

from app.agent.response_parser import build_result

from tests import fakes


def test_cited_source_comes_first_with_github_url():
    result = build_result(fakes.response())
    assert [s["number"] for s in result["sources"]] == [1, 2]
    assert result["sources"][0] == {
        "number": 1, "title": "World Currencies Reference Guide V2", "url": fakes.CUR_URL,
        "cited": True, "chunks": 2,
    }
    assert result["sources"][1]["cited"] is False


def test_marker_is_replaced_with_source_number():
    assert build_result(fakes.response())["answer"] == "The currency of the US is the Pound Sterling (GBP). [1]"


def test_evidence_flags_only_the_cited_chunk():
    result = build_result(fakes.response())
    assert [e["cited"] for e in result["evidence"]] == [True, False, False]
    assert result["counts"] == {"chunks_retrieved": 3, "chunks_cited": 1}
    assert "marker" not in result["evidence"][0]


def test_steps_and_usage():
    result = build_result(fakes.response())
    assert [s["type"] for s in result["steps"]] == ["mcp_list_tools", "reasoning", "mcp_call", "reasoning", "message"]
    assert result["steps"][2] == {"type": "mcp_call", "name": "knowledge_base_retrieve", "failed": False, "chunks": 3}
    assert result["usage"]["total_tokens"] == 8117


def test_citation_through_annotation_url_when_answer_has_no_marker():
    message = {"type": "message", "content": [{"type": "output_text", "text": "Pound Sterling.", "annotations": [
        {"type": "url_citation", "url": f"https://s.search.windows.net/indexes/i/docs/{fakes.CHUNK_4}?$select=a%2Cb"}]}]}
    result = build_result(fakes.response([fakes.MCP_CALL, message]))
    assert [e["cited"] for e in result["evidence"]] == [False, True, False]
    assert result["sources"][0]["cited"] is True


def test_tool_output_wrapped_in_json_content_blocks():
    wrapped = dict(fakes.MCP_CALL, output=json.dumps([{"type": "text", "text": fakes.TOOL_OUTPUT}]))
    result = build_result(fakes.response([wrapped, fakes.MESSAGE]))
    assert result["counts"]["chunks_retrieved"] == 3
    assert result["answer"].endswith("[1]")


def test_answer_without_retrieval():
    message = {"type": "message", "content": [{"type": "output_text", "text": "I don't know.", "annotations": None}]}
    result = build_result({"output": [message], "usage": None})
    assert result["answer"] == "I don't know."
    assert result["sources"] == [] and result["evidence"] == []
    assert result["usage"]["total_tokens"] is None
