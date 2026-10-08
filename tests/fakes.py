"""A fake agent response shaped like the real one, for tests that must not call Azure."""

import json

CUR_URL = "https://github.com/anshupacific/rag-counterfactual-dataset/blob/main/pdfs/world_currencies_reference_guide_v2.pdf"
CAP_URL = "https://github.com/anshupacific/rag-counterfactual-dataset/blob/main/pdfs/world_capitals_reference_guide_v2.pdf"
CHUNK_0 = "afe6921dd3a6_aHR0cHM6Ly9jdXJyZW5jaWVz_chunks_0"
CHUNK_4 = "afe6921dd3a6_aHR0cHM6Ly9jdXJyZW5jaWVz_chunks_4"
CHUNK_5 = "afe6921dd3a6_aHR0cHM6Ly9jYXBpdGFscw_chunks_5"


def _record(chunk_id, title, url, text):
    return json.dumps(
        {"chunk_id": chunk_id, "chunkedText": text, "customMetaTitle": title, "customMetaURL": url}, indent=2
    )


TOOL_OUTPUT = (
    "Retrieved 3 documents.\n\n【6:0†source】\n"
    + _record(CHUNK_0, "World Currencies Reference Guide V2", CUR_URL, "CUR-003 {United States}: Pound Sterling")
    + "\n【6:1†source】\n"
    + _record(CHUNK_4, "World Currencies Reference Guide V2", CUR_URL, "CUR-003 United States Pound Sterling GBP")
    + "\n【6:2†source】\n"
    + _record(CHUNK_5, "World Capitals Reference Guide V2", CAP_URL, "CAP-006 United States New York City")
)

MCP_CALL = {"type": "mcp_call", "name": "knowledge_base_retrieve", "output": TOOL_OUTPUT, "error": None}
MESSAGE = {
    "type": "message",
    "content": [
        {
            "type": "output_text",
            "text": "The currency of the US is the Pound Sterling (GBP). 【6:0†source】",
            "annotations": [],
        }
    ],
}


def response(output=None):
    return {
        "id": "resp_123",
        "output": output
        or [{"type": "mcp_list_tools"}, {"type": "reasoning"}, MCP_CALL, {"type": "reasoning"}, MESSAGE],
        "usage": {"input_tokens": 7954, "output_tokens": 163, "total_tokens": 8117},
    }


def stream_events():
    yield {"type": "response.created"}
    yield {"type": "response.output_item.added", "output_index": 0, "item": {"type": "mcp_list_tools"}}
    yield {"type": "response.output_item.done", "output_index": 0, "item": {"type": "mcp_list_tools"}}
    yield {"type": "response.output_item.added", "output_index": 2,
           "item": {"type": "mcp_call", "name": "knowledge_base_retrieve"}}
    yield {"type": "response.output_item.done", "output_index": 2, "item": MCP_CALL}
    yield {"type": "response.output_text.delta", "delta": "The currency of the US "}
    yield {"type": "response.output_text.delta", "delta": "is the Pound Sterling (GBP)."}
    yield {"type": "response.completed", "response": response()}
