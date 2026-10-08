"""Short-lived memory of the answers this API has produced.

Evaluation is only allowed for a response ID found here, so a visitor cannot
make the backend spend tokens scoring arbitrary IDs. It also gives the quick
checks the question, answer and sources without another call to Foundry.

Held in memory, which is correct for one App Service instance with one worker.
"""

import threading
import time
from collections import OrderedDict

MAX_ANSWERS = 300
KEEP_SECONDS = 2 * 60 * 60

_lock = threading.Lock()
_answers: "OrderedDict[str, dict]" = OrderedDict()


def remember(question: str, result: dict) -> None:
    """Store a parsed answer under its Foundry response ID."""
    response_id = result.get("response_id")
    if not response_id:
        return
    with _lock:
        _answers[response_id] = {"question": question, "result": result, "stored_at": time.time()}
        _answers.move_to_end(response_id)
        while len(_answers) > MAX_ANSWERS:
            _answers.popitem(last=False)


def get(response_id: str) -> dict | None:
    with _lock:
        entry = _answers.get(response_id)
        if entry and time.time() - entry["stored_at"] > KEEP_SECONDS:
            del _answers[response_id]
            return None
        return entry


def clear() -> None:
    with _lock:
        _answers.clear()