"""Reproducible evaluation of the matcher against hand-labelled pairs.

Input: a JSONL file, one pair per line:

    {"id": "p01", "objective": "...", "status": "...", "label": "on_task"}

`label` is the ground truth: "on_task" or "off_task". Optional fields:
`objective_id` (cluster; defaults to the objective text), `kind` (a named
sub-type, reported separately) and `split`.

Statuses that share an objective are not independent, so every interval
resamples whole objectives, not single pairs.

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
                "cluster": str(obj.get("objective_id") or obj["objective"]),
                "kind": obj.get("kind"),
                "split": obj.get("split"),
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


def cluster_bootstrap_auc_ci(
    scores: Sequence[float],
    labels: Sequence[str],
    clusters: Sequence[str],
    resamples: int = BOOTSTRAP_RESAMPLES,
    seed: int = BOOTSTRAP_SEED,
) -> tuple[float, float] | None:
    """95% percentile interval, resampling whole clusters with replacement.

    Fixed seed, and draws made with rng.random() only, so the result is
    identical on every run and every supported Python version. With few
    clusters a bootstrap interval is too narrow; read it as optimistic.
    Returns None when there is a single cluster.
    """
    names = sorted(set(clusters))
    if len(names) < 2:
        return None
    members: dict[str, tuple[list[float], list[float]]] = {n: ([], []) for n in names}
    for score, label, cluster in zip(scores, labels, clusters):
        members[cluster][0 if label == "on_task" else 1].append(score)

    rng = random.Random(seed)
    k = len(names)
    stats: list[float] = []
    while len(stats) < resamples:
        pos: list[float] = []
        neg: list[float] = []
        for _ in range(k):
            p, n = members[names[int(rng.random() * k)]]
            pos += p
            neg += n
        if pos and neg:
            stats.append(auc(pos, neg))
    stats.sort()
    return stats[int(0.025 * resamples)], stats[min(resamples - 1, int(0.975 * resamples))]


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
def _auc_block(scores, labels, clusters) -> dict:
    pos = [s for s, l in zip(scores, labels) if l == "on_task"]
    neg = [s for s, l in zip(scores, labels) if l == "off_task"]
    ci = cluster_bootstrap_auc_ci(scores, labels, clusters)
    return {
        "auc": round(auc(pos, neg), _ROUND),
        "auc_ci95": None if ci is None else [round(ci[0], _ROUND), round(ci[1], _ROUND)],
    }


def _rater_report(
    pairs: list[dict], scorer: Callable[[str, str], float]
) -> tuple[dict, list[float]]:
    scores = [scorer(p["status"], p["objective"]) for p in pairs]
    labels = [p["label"] for p in pairs]
    clusters = [p["cluster"] for p in pairs]
    pos = [s for s, l in zip(scores, labels) if l == "on_task"]
    neg = [s for s, l in zip(scores, labels) if l == "off_task"]
    report = _auc_block(scores, labels, clusters)
    acc, threshold = best_threshold(pos, neg)
    report["best_threshold_accuracy"] = round(acc, _ROUND)
    report["best_threshold"] = None if threshold == float("inf") else round(threshold, _ROUND)

    # One AUC per (on-task kind, off-task kind): the pooled AUC depends on
    # the mix of kinds in the file; these do not.
    on_kinds = sorted({p["kind"] for p in pairs if p["kind"] and p["label"] == "on_task"})
    off_kinds = sorted({p["kind"] for p in pairs if p["kind"] and p["label"] == "off_task"})
    contrasts = {}
    for on in on_kinds:
        for off in off_kinds:
            keep = [i for i, p in enumerate(pairs) if p["kind"] in (on, off)]
            contrasts[f"{on} vs {off}"] = _auc_block(
                [scores[i] for i in keep], [labels[i] for i in keep], [clusters[i] for i in keep]
            )
    if contrasts:
        report["by_kind"] = contrasts
    return report, scores


def evaluate(pairs: list[dict], dataset_sha256: str | None = None) -> dict:
    pairs = [
        {"cluster": str(p.get("objective_id") or p["objective"]), "kind": None, "split": None, **p}
        for p in pairs
    ]
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

    group_key = "kind" if any(p["kind"] for p in pairs) else "label"
    tags: dict[str, dict[str, int]] = {}
    for p in pairs:
        tag = dual_compare(p["status"], p["objective"]).final_tag
        row = tags.setdefault(str(p[group_key]), {})
        row[tag] = row.get(tag, 0) + 1

    return {
        "dataset_sha256": dataset_sha256,
        "n": len(pairs),
        "n_on_task": n_on,
        "n_off_task": n_off,
        "n_clusters": len({p["cluster"] for p in pairs}),
        "always_match_accuracy": round(n_on / len(pairs), _ROUND),
        "raters": {"word": word, "trigram": trigram},
        "pearson_word_trigram": None if r is None else round(r, _ROUND),
        "final_tag_by": group_key,
        "final_tags": tags,
        "bootstrap": {
            "resamples": BOOTSTRAP_RESAMPLES, "seed": BOOTSTRAP_SEED, "unit": "objective",
        },
    }


def evaluate_file(path: str | Path, split: str | None = None) -> dict:
    digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    pairs = load_pairs(path)
    if split is not None:
        pairs = [p for p in pairs if p["split"] == split]
        if not pairs:
            raise ValueError(f"no pairs with split = {split!r} in {path}")
    report = evaluate(pairs, dataset_sha256=digest)
    report["split"] = split
    return report


def _verdict(ci) -> str:
    """Describe where the interval sits. Deliberately not a significance
    claim: the interval is optimistic with few objectives, and a file's
    pre-committed tests (see eval/PLAN.md) decide what can be claimed."""
    if ci is None:
        return "no interval (one objective)"
    if ci[1] < 0.5:
        return "interval below 0.5"
    if ci[0] > 0.5:
        return "interval above 0.5"
    return "interval spans 0.5"


def _fmt_auc(block: dict) -> str:
    ci = block["auc_ci95"]
    span = "" if ci is None else f" (95% CI {ci[0]:.3f}-{ci[1]:.3f})"
    return f"AUC {block['auc']:.3f}{span} -> {_verdict(ci)}"


def format_report(report: dict) -> str:
    lines = [
        f"Pairs: {report['n']} "
        f"({report['n_on_task']} on_task, {report['n_off_task']} off_task) "
        f"across {report['n_clusters']} objectives",
        f"Dataset SHA-256: {report['dataset_sha256']}",
        "Intervals resample whole objectives; with few objectives they are optimistic.",
        "",
        f"Always-MATCH accuracy (baseline): {report['always_match_accuracy']:.3f}",
        "",
    ]
    for name, label in (("word", "Rater A (word)"), ("trigram", "Rater B (trigram)")):
        r = report["raters"][name]
        lines.append(f"{label}: {_fmt_auc(r)}")
        lines.append(
            f"  best accuracy at any threshold: {r['best_threshold_accuracy']:.3f}"
        )
        for contrast, block in r.get("by_kind", {}).items():
            lines.append(f"  {contrast}: {_fmt_auc(block)}")
    rho = report["pearson_word_trigram"]
    lines += [
        "",
        "Pearson r (word vs trigram): " + ("n/a" if rho is None else f"{rho:.3f}"),
        "",
        f"Final tag by {report['final_tag_by']}:",
    ]
    for group, counts in sorted(report["final_tags"].items()):
        cells = ", ".join(f"{t}={c}" for t, c in sorted(counts.items())) or "-"
        lines.append(f"  {group:14}: {cells}")
    return "\n".join(lines)
