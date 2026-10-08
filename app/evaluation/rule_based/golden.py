"""The test set: every question with its expected outcome. Built by evaluation/build_golden.py."""

import json
from functools import lru_cache
from pathlib import Path

GOLDEN_PATH = Path(__file__).parent / "data" / "golden.jsonl"


@lru_cache
def load_tests() -> tuple:
    with GOLDEN_PATH.open(encoding="utf-8") as handle:
        return tuple(json.loads(line) for line in handle if line.strip())


def get_test(test_id: str) -> dict | None:
    return next((test for test in load_tests() if test["id"] == test_id), None)