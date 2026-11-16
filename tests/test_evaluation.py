"""Tests for the evaluation metrics. Expected values are hand-computable."""

import json
from pathlib import Path

import pytest

from warden.evaluation import (
    auc, best_threshold, cluster_bootstrap_auc_ci, evaluate, evaluate_file,
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


def test_cluster_bootstrap_is_deterministic_and_brackets_the_estimate():
    scores = [0.9, 0.2, 0.7, 0.8, 0.6, 0.4, 0.3, 0.1]
    labels = ["on_task", "off_task"] * 4
    clusters = ["a", "a", "b", "b", "c", "c", "d", "d"]
    first = cluster_bootstrap_auc_ci(scores, labels, clusters)
    assert first == cluster_bootstrap_auc_ci(scores, labels, clusters)
    pos = scores[0::2]; neg = scores[1::2]
    assert first[0] <= auc(pos, neg) <= first[1]


def test_single_cluster_has_no_interval():
    assert cluster_bootstrap_auc_ci([0.9, 0.1], ["on_task", "off_task"], ["a", "a"]) is None


def test_by_kind_contrasts_and_split(tmp_path: Path):
    rows = []
    for obj in ("Build the importer", "Write the exporter"):
        for kind, label, status in (
            ("on_echo", "on_task", f"{obj} now"),
            ("off_unrelated", "off_task", "Painting the fence"),
        ):
            rows.append({"objective": obj, "status": status, "label": label,
                         "kind": kind, "split": "dev" if "importer" in obj else "test"})
    path = _write(tmp_path / "k.jsonl", rows)
    report = evaluate_file(path)
    assert report["n_clusters"] == 2
    assert report["raters"]["word"]["by_kind"]["on_echo vs off_unrelated"]["auc"] == 1.0
    assert report["final_tag_by"] == "kind"
    assert evaluate_file(path, split="dev")["n"] == 2
    with pytest.raises(ValueError):
        evaluate_file(path, split="nope")


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
