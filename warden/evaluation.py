"""Reproducible evaluation of the matcher against hand-labelled pairs.

Input: a JSONL file, one pair per line:

    {"id": "p01", "objective": "...", "status": "...", "label": "on_task"}

`label` is the human ground truth: "on_task" or "off_task".

Everything here is deterministic and dependency-free: the same file always
produces the same report, and the report carries the file's SHA-256 so a
published number can be tied to the exact data it came from.

Convention: a higher score should mean "on task". AUC is the probability
that a randomly chosen on-task pair outscores a randomly chosen off-task
pair (ties count half). 0.5 is chance; below 0.5 the score is inverted.
"""

from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path
from typing import Callable, Sequence

from .matcher import dual_compare, similarity_score, trigram_score

LABELS = ("on_task", "off_task")
BOOTSTRAP_RESAMPLES = 2000
BOOTSTRAP_SEED = 0
_ROUND = 4


# ----------------------------------------------------------------------
# Loading
# ----------------------------------------------------------------------
def load_pairs(path: str | Path) -> list[dict]:
    pairs: list[dict] = []
    seen_ids: set[str] = set()
    text = Path(path).read_text(encoding="utf-8")
    for lineno, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{lineno}: not valid JSON ({exc.msg})")
        if not isinstance(obj, dict):
            raise ValueError(f"{path}:{lineno}: expected a JSON object")
        for key in ("objective", "status", "label"):
            if not isinstance(obj.get(key), str) or not obj[key].strip():
                raise ValueError(f"{path}:{lineno}: missing or empty '{key}'")
        if obj["label"] not in LABELS:
            raise ValueError(
                f"{path}:{lineno}: label must be one of {LABELS}, got {obj['label']!r}"
            )
        pair_id = str(obj.get("id", f"line{lineno}"))
        if pair_id in seen_ids:
            raise ValueError(f"{path}:{lineno}: duplicate id {pair_id!r}")
        seen_ids.add(pair_id)
        pairs.append(
            {
                "id": pair_id,
                "objective": obj["objective"],
                "status": obj["status"],
                "label": obj["label"],
            }
        )
    return pairs


# ----------------------------------------------------------------------
# Metrics
# ----------------------------------------------------------------------
def auc(pos: Sequence[float], neg: Sequence[float]) -> float:
    """P(pos > neg) + 0.5 * P(pos == neg), over all pos/neg pairs."""
    if not pos or not neg:
        raise ValueError("AUC needs at least one on_task and one off_task pair")
    wins = 0.0
    for p in pos:
        for n in neg:
            if p > n:
                wins += 1.0
            elif p == n:
                wins += 0.5
    return wins / (len(pos) * len(neg))


def bootstrap_auc_ci(
    pos: Sequence[float],
    neg: Sequence[float],
    resamples: int = BOOTSTRAP_RESAMPLES,
    seed: int = BOOTSTRAP_SEED,
) -> tuple[float, float]:
    """95% percentile interval, resampling each class separately.

    Fixed seed, and index draws done with rng.random() only, so the result
    is identical on every run and every supported Python version.
    """
    rng = random.Random(seed)

    def draw(values: Sequence[float]) -> list[float]:
        k = len(values)
        return [values[int(rng.random() * k)] for _ in range(k)]

    stats = sorted(auc(draw(pos), draw(neg)) for _ in range(resamples))
    lo = stats[int(0.025 * resamples)]
    hi = stats[min(resamples - 1, int(0.975 * resamples))]
    return lo, hi


def best_threshold(pos: Sequence[float], neg: Sequence[float]) -> tuple[float, float]:
    """Best accuracy of the rule "score >= t means on_task", over every t.

    Returns (accuracy, threshold). Includes t = +inf (always off_task) and
    t = min score (always on_task), so no threshold is left untried.
    """
    total = len(pos) + len(neg)
    candidates = sorted(set(pos) | set(neg)) + [float("inf")]
    best_acc, best_t = -1.0, candidates[0]
    for t in candidates:
        correct = sum(1 for p in pos if p >= t) + sum(1 for n in neg if n < t)
        acc = correct / total
        if acc > best_acc:
            best_acc, best_t = acc, t
    return best_acc, best_t


def pearson(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    n = len(xs)
    if n != len(ys) or n < 2:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx == 0 or syy == 0:
        return None
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    return sxy / (sxx * syy) ** 0.5


# ----------------------------------------------------------------------
# Report
# ----------------------------------------------------------------------
def _rater_report(
    pairs: list[dict], scorer: Callable[[str, str], float]
) -> tuple[dict, list[float]]:
    scores = [scorer(p["status"], p["objective"]) for p in pairs]
    pos = [s for s, p in zip(scores, pairs) if p["label"] == "on_task"]
    neg = [s for s, p in zip(scores, pairs) if p["label"] == "off_task"]
    value = auc(pos, neg)
    lo, hi = bootstrap_auc_ci(pos, neg)
    acc, threshold = best_threshold(pos, neg)
    return (
        {
            "auc": round(value, _ROUND),
            "auc_ci95": [round(lo, _ROUND), round(hi, _ROUND)],
            "best_threshold_accuracy": round(acc, _ROUND),
            "best_threshold": None if threshold == float("inf") else round(threshold, _ROUND),
        },
        scores,
    )


def evaluate(pairs: list[dict], dataset_sha256: str | None = None) -> dict:
    n_on = sum(1 for p in pairs if p["label"] == "on_task")
    n_off = len(pairs) - n_on
    if n_on == 0 or n_off == 0:
        raise ValueError(
            "need at least one on_task and one off_task pair "
            f"(got {n_on} on_task, {n_off} off_task)"
        )

    word, word_scores = _rater_report(pairs, similarity_score)
    trigram, trigram_scores = _rater_report(pairs, trigram_score)
    r = pearson(word_scores, trigram_scores)

    tags: dict[str, dict[str, int]] = {label: {} for label in LABELS}
    for p in pairs:
        tag = dual_compare(p["status"], p["objective"]).final_tag
        tags[p["label"]][tag] = tags[p["label"]].get(tag, 0) + 1

    return {
        "dataset_sha256": dataset_sha256,
        "n": len(pairs),
        "n_on_task": n_on,
        "n_off_task": n_off,
        "always_match_accuracy": round(n_on / len(pairs), _ROUND),
        "raters": {"word": word, "trigram": trigram},
        "pearson_word_trigram": None if r is None else round(r, _ROUND),
        "final_tag_by_label": tags,
        "bootstrap": {"resamples": BOOTSTRAP_RESAMPLES, "seed": BOOTSTRAP_SEED},
    }


def evaluate_file(path: str | Path) -> dict:
    digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    return evaluate(load_pairs(path), dataset_sha256=digest)


def format_report(report: dict) -> str:
    lines = [
        f"Pairs: {report['n']} "
        f"({report['n_on_task']} on_task, {report['n_off_task']} off_task)",
        f"Dataset SHA-256: {report['dataset_sha256']}",
        "",
        f"Always-MATCH accuracy (baseline): {report['always_match_accuracy']:.3f}",
        "",
    ]
    for name, label in (("word", "Rater A (word)"), ("trigram", "Rater B (trigram)")):
        r = report["raters"][name]
        verdict = "inverted" if r["auc_ci95"][1] < 0.5 else (
            "better than chance" if r["auc_ci95"][0] > 0.5 else "not distinguishable from chance"
        )
        lines.append(
            f"{label}: AUC {r['auc']:.3f} "
            f"(95% CI {r['auc_ci95'][0]:.3f}-{r['auc_ci95'][1]:.3f}) -> {verdict}"
        )
        lines.append(
            f"  best accuracy at any threshold: {r['best_threshold_accuracy']:.3f}"
        )
    rho = report["pearson_word_trigram"]
    lines += [
        "",
        "Pearson r (word vs trigram): " + ("n/a" if rho is None else f"{rho:.3f}"),
        "",
        "Final tag by human label:",
    ]
    for label in LABELS:
        counts = report["final_tag_by_label"][label]
        cells = ", ".join(f"{t}={c}" for t, c in sorted(counts.items())) or "-"
        lines.append(f"  {label:9}: {cells}")
    return "\n".join(lines)
