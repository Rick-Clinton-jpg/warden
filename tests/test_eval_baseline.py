"""Recompute the committed evaluation and fail if any number has moved.

Skipped until eval/labelled_pairs.jsonl and eval/baseline.json both exist
(see eval/README.md).
"""

import json
from pathlib import Path

import pytest

from warden.evaluation import evaluate_file

EVAL_DIR = Path(__file__).resolve().parent.parent / "eval"
PAIRS = EVAL_DIR / "labelled_pairs.jsonl"
BASELINE = EVAL_DIR / "baseline.json"


@pytest.mark.skipif(
    not (PAIRS.exists() and BASELINE.exists()),
    reason="eval/labelled_pairs.jsonl and eval/baseline.json not committed yet",
)
def test_committed_baseline_reproduces():
    assert evaluate_file(PAIRS) == json.loads(BASELINE.read_text(encoding="utf-8"))
