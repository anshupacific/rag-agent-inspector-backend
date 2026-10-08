"""Turn a raw agent response into what the UI shows: answer, sources, evidence, steps."""

import json
import re
from urllib.parse import unquote

# Citation markers look like 【6:0†source】 in both the tool output and the answer.
MARKER = re.compile(r"【(\d+:\d+)†[^】]*】")


def _items(response: dict, kind: str) -> list:
    return [item for item in response.get("output") or [] if item.get("type") == kind]


def get_answer(response: dict) -> str:
    """Join the text parts of every message item (citation markers still inside)."""
    parts = []
    for item in _items(response, "message"):
        for content in item.get("content") or []:
            if content.get("text"):
                parts.append(content["text"])
    return "\n".join(parts).strip()


def find_chunks(value, found: list) -> None:
    """Collect chunk records from tool output, whatever shape it arrives in.

    The output can be plain text, JSON, or JSON wrapped inside JSON, so strings
    are scanned for embedded JSON and whatever is decoded is walked again.
    """
    if isinstance(value, dict):
        if "chunk_id" in value:
            found.append(value)
            return
        for child in value.values():
            find_chunks(child, found)
    elif isinstance(value, list):
        for child in value:
            find_chunks(child, found)
    elif isinstance(value, str) and ("{" in value or "[" in value):
        decoder = json.JSONDecoder()
        markers = [(m.start(), m.group(1)) for m in MARKER.finditer(value)]
        pos = 0
        while True:
            starts = [p for p in (value.find("{", pos), value.find("[", pos)) if p != -1]
            if not starts:
                break
            start = min(starts)
            try:
                decoded, end = decoder.raw_decode(value, start)
            except json.JSONDecodeError:
                pos = start + 1
                continue
            before = len(found)
            find_chunks(decoded, found)
            label = next((name for at, name in reversed(markers) if at < start), None)
            for chunk in found[before:]:
                chunk.setdefault("_marker", label)
            pos = end


def get_retrieved_chunks(response: dict) -> list:
    chunks = []
    for item in _items(response, "mcp_call"):
        find_chunks(item.get("output"), chunks)
    return chunks


def get_cited_urls(response: dict) -> list:
    """URLs attached to the answer as annotations (raw index links)."""
    urls = []
    for item in _items(response, "message"):
        for content in item.get("content") or []:
            for note in content.get("annotations") or []:
                if note.get("url"):
                    urls.append(unquote(note["url"]))
    return urls


def describe_step(item: dict) -> dict:
    """One step of the agent's run, in the shape the steps panel shows."""
    step = {"type": item.get("type", "unknown")}
    if step["type"] == "mcp_call":
        step["name"] = item.get("name")
        step["failed"] = bool(item.get("error"))
        chunks = []
        find_chunks(item.get("output"), chunks)
        step["chunks"] = len(chunks)
    return step


def _number_citations(answer: str, marker_numbers: dict) -> str:
    """Swap raw markers like 【6:0†source】 for [1], [2] matching the source list."""

    def replace(match):
        number = marker_numbers.get(match.group(1))
        return f"[{number}]" if number else ""

    return re.sub(r"\s+([.,;])", r"\1", MARKER.sub(replace, answer)).strip()


def build_result(response: dict) -> dict:
    """Everything the UI needs for one answer."""
    raw_answer = get_answer(response)
    chunks = get_retrieved_chunks(response)
    cited_markers = set(MARKER.findall(raw_answer))
    cited_urls = get_cited_urls(response)

    # Evidence: one entry per chunk, flagged if the answer cited it.
    evidence = []
    for chunk in chunks:
        cited = chunk.get("_marker") in cited_markers or any(
            str(chunk["chunk_id"]) in url for url in cited_urls
        )
        evidence.append(
            {
                "title": chunk.get("customMetaTitle", ""),
                "url": chunk.get("customMetaURL", ""),
                "text": chunk.get("chunkedText", ""),
                "cited": cited,
                "marker": chunk.get("_marker"),
            }
        )

    # Sources: one entry per document, cited documents first, numbered from 1.
    by_url = {}
    for item in evidence:
        entry = by_url.setdefault(
            item["url"] or item["title"],
            {"title": item["title"], "url": item["url"], "cited": False, "chunks": 0, "markers": set()},
        )
        entry["chunks"] += 1
        entry["cited"] = entry["cited"] or item["cited"]
        if item["marker"]:
            entry["markers"].add(item["marker"])
    ordered = sorted(by_url.values(), key=lambda source: not source["cited"])

    marker_numbers = {}
    sources = []
    for number, entry in enumerate(ordered, start=1):
        for marker in entry["markers"]:
            marker_numbers[marker] = number
        sources.append(
            {"number": number, "title": entry["title"], "url": entry["url"],
             "cited": entry["cited"], "chunks": entry["chunks"]}
        )
    for item in evidence:
        del item["marker"]

    usage = response.get("usage") or {}
    return {
        "answer": _number_citations(raw_answer, marker_numbers),
        "sources": sources,
        "evidence": evidence,
        "steps": [describe_step(item) for item in response.get("output") or []],
        "usage": {
            "input_tokens": usage.get("input_tokens"),
            "output_tokens": usage.get("output_tokens"),
            "total_tokens": usage.get("total_tokens"),
        },
        "counts": {
            "chunks_retrieved": len(evidence),
            "chunks_cited": sum(1 for item in evidence if item["cited"]),
        },
        "response_id": response.get("id"),
    }
