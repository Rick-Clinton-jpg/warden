"""Keyword extraction and lightweight similarity matching."""

from __future__ import annotations

import re
from typing import Set

# Minimal English stop-word list — good enough for v1
STOP_WORDS: Set[str] = {
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "as", "is", "are", "was", "were", "be",
    "been", "being", "have", "has", "had", "do", "does", "did", "will",
    "would", "could", "should", "may", "might", "must", "shall", "can",
    "this", "that", "these", "those", "it", "its", "i", "you", "he",
    "she", "we", "they", "me", "him", "her", "us", "them", "my", "your",
    "his", "our", "their", "what", "which", "who", "whom", "whose",
    "where", "when", "why", "how", "all", "each", "every", "both",
    "few", "more", "most", "other", "some", "such", "no", "nor", "not",
    "only", "own", "same", "so", "than", "too", "very", "just", "about",
    "into", "over", "after", "before", "between", "under", "again",
    "further", "then", "once", "here", "there", "up", "down", "out",
    "off", "above", "below", "now", "also", "if", "any", "while",
}

# Very light stemming rules (suffix stripping)
_STEM_RULES = [
    (r"ing$", ""),
    (r"tion$", "t"),
    (r"sion$", "s"),
    (r"ness$", ""),
    (r"ment$", ""),
    (r"able$", ""),
    (r"ible$", ""),
    (r"ies$", "y"),
    (r"es$", ""),
    (r"s$", ""),
    (r"ed$", ""),
    (r"ly$", ""),
    (r"er$", ""),
    (r"est$", ""),
]


def _stem(word: str) -> str:
    if len(word) <= 3:
        return word
    for pattern, repl in _STEM_RULES:
        new = re.sub(pattern, repl, word)
        if new != word and len(new) >= 2:
            return new
    return word


def extract_keywords(text: str) -> list[str]:
    """
    Lowercase, drop stop words, keep alphanumeric tokens, light stem.
    """
    if not text:
        return []
    tokens = re.findall(r"[a-z0-9_]+", text.lower())
    keywords = []
    for t in tokens:
        if t in STOP_WORDS or len(t) < 2:
            continue
        keywords.append(_stem(t))
    return keywords


def compare_status_to_objective(status: str, objective: str) -> str:
    """
    Returns: MATCH | DRIFT | UNCLEAR

    Keyword-overlap Jaccard similarity with calibrated thresholds.
    """
    if not status or not status.strip():
        return "UNCLEAR"

    status_words = set(extract_keywords(status))
    objective_words = set(extract_keywords(objective))

    if not status_words or not objective_words:
        return "UNCLEAR"

    overlap = len(status_words & objective_words)
    total = len(status_words | objective_words)
    similarity = overlap / total if total > 0 else 0.0

    if similarity >= 0.45:
        return "MATCH"
    if similarity >= 0.18:
        return "UNCLEAR"
    return "DRIFT"


def similarity_score(status: str, objective: str) -> float:
    """Return the raw Jaccard score for debugging / notes."""
    status_words = set(extract_keywords(status))
    objective_words = set(extract_keywords(objective))
    if not status_words or not objective_words:
        return 0.0
    overlap = len(status_words & objective_words)
    total = len(status_words | objective_words)
    return overlap / total if total > 0 else 0.0


def make_note(tag: str, status: str, objective: str, score: float) -> str:
    """Generate a short human-readable note for the audit log."""
    if tag == "MATCH":
        return (
            f"Status aligns with objective (score={score:.2f}). On track."
        )
    if tag == "DRIFT":
        return (
            f"Objective: '{objective[:80]}…'. "
            f"Status: '{status[:80]}…'. "
            f"Low keyword overlap (score={score:.2f}). "
            "Possible drift — verify with user."
        )
    if not status:
        return (
            "No WARDEN_STATUS found in last polling window. "
            "Agent may have stopped or status line was malformed."
        )
    return (
        f"Status unclear relative to objective "
        f"(score={score:.2f}). Cannot assess confidently."
    )