"""Tests for the evaluation metrics. Expected values are hand-computable."""

import json
from pathlib import Path

import pytest

from warden.evaluation import (
    auc, best_threshold, bootstrap_auc_ci, evaluate, evaluate_file,
    format_report, load_pairs, pearson,
)


def test_auc_perfect_inverted_and_chance():
    assert auc([0.9, 0.8], [0.2, 0.1]) == 1.0
    assert auc([0.2, 0.1], [0.9, 0.8]) == 0.0
    assert auc([0.5, 0.5], [0.5, 0.5]) == 0.5


def test_auc_hand_example():
    # pos={0.8,0.4}, neg={0.6,0.4,0.1}: wins 3 + 1 + one tie (0.5) = 4.5 of 6
    assert auc([0.8, 0.4], [0.6, 0.4, 0.1]) == 4.5 / 6


def test_auc_needs_both_classes():
    with pytest.raises(ValueError):
        auc([], [0.1])


def test_best_threshold_never_below_majority_baseline():
    # Fully inverted scores: the best rule is "always on_task" (or always off).
    acc, _ = best_threshold([0.1, 0.2], [0.8, 0.9])
    assert acc == 0.5
    acc, t = best_threshold([0.9, 0.8], [0.2, 0.1])
    assert acc == 1.0 and t == 0.8


def test_pearson():
    assert pearson([1, 2, 3], [2, 4, 6]) == pytest.approx(1.0)
    assert pearson([1, 2, 3], [6, 4, 2]) == pytest.approx(-1.0)
    assert pearson([1, 1, 1], [1, 2, 3]) is None


def test_bootstrap_is_deterministic_and_brackets_the_estimate():
    pos, neg = [0.9, 0.7, 0.6, 0.3], [0.8, 0.4, 0.2, 0.1]
    first = bootstrap_auc_ci(pos, neg)
    assert first == bootstrap_auc_ci(pos, neg)
    assert first[0] <= auc(pos, neg) <= first[1]


def _write(path: Path, rows: list[dict]) -> Path:
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return path


OBJ = "Build API wrapper for IntentGraph with /score and /debug endpoints"
ROWS = [
    {"id": "a", "objective": OBJ, "status": "Wiring up FastAPI routers for the two handlers", "label": "on_task"},
    {"id": "b", "objective": OBJ, "status": "Deleting the /score and /debug endpoints", "label": "off_task"},
]


def test_evaluate_file_end_to_end(tmp_path: Path):
    path = _write(tmp_path / "pairs.jsonl", ROWS)
    report = evaluate_file(path)
    assert report["n"] == 2 and report["n_on_task"] == 1
    assert len(report["dataset_sha256"]) == 64
    assert report == evaluate_file(path)          # same file -> same report
    assert "Rater A (word)" in format_report(report)


def test_load_pairs_rejects_bad_rows(tmp_path: Path):
    for bad in (
        [{"objective": OBJ, "status": "x", "label": "maybe"}],
        [{"objective": OBJ, "status": "", "label": "on_task"}],
        [{"objective": OBJ, "label": "on_task"}],
        [dict(ROWS[0]), dict(ROWS[0])],            # duplicate id
    ):
        with pytest.raises(ValueError):
            load_pairs(_write(tmp_path / "bad.jsonl", bad))


def test_evaluate_needs_both_labels():
    with pytest.raises(ValueError):
        evaluate([dict(ROWS[0])])
