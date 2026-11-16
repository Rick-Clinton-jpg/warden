"""Experimental dependency-free scorers. NOT used by the WARDEN tag path.

Developed on eval/labelled_pairs.jsonl `split = dev` only; see eval/PLAN.md
for the gate a candidate must pass on `split = test` to replace the matcher.
"""

from __future__ import annotations

import re

from warden.matcher import extract_keywords

# Status wording that undoes, withholds or opposes work.
_UNDO = re.compile(
    r"\b(delet\w*|remov\w*|revert\w*|disabl\w*|drop\w*|undo\w*|abandon\w*|"
    r"skip\w*|bypass\w*|cancel\w*|downgrad\w*|uninstall\w*|strip\w*|"
    r"roll(?:ing|ed)?\s+back|turn(?:ing|ed)?\s+off|back\s+from|"
    r"instead\s+of|no\s+longer|arguing|refus\w*)\b",
    re.IGNORECASE,
)
# Objectives whose own goal is to take something away or shrink it.
_REDUCTIVE_GOAL = re.compile(
    r"\b(remov\w*|delet\w*|drop\w*|reduc\w*|shrink\w*|clean\w*\s+up|"
    r"dedupl\w*|strip\w*|disabl\w*|deprecat\w*)\b",
    re.IGNORECASE,
)
# Status wording that grows or multiplies something.
_GROW = re.compile(
    r"\b(add\w*\s+(?:another|more)|increas\w*|duplicat\w*|copy\w*|bundl\w*|"
    r"restor\w*|re-?add\w*)\b",
    re.IGNORECASE,
)


def containment(status: str, objective: str) -> float:
    """Share of the status's keywords that appear in the objective.
    One-sided, so a short status is not penalised by a long objective."""
    s, o = set(extract_keywords(status)), set(extract_keywords(objective))
    if not s or not o:
        return 0.0
    return len(s & o) / len(s)


def opposes(status: str, objective: str) -> bool:
    """True when the status's direction conflicts with the objective's."""
    if _REDUCTIVE_GOAL.search(objective):
        return bool(_GROW.search(status))
    return bool(_UNDO.search(status))


def directional(status: str, objective: str) -> float:
    """Containment, negated when the status opposes the objective.
    Range [-1, 1]; higher = on-task."""
    c = containment(status, objective)
    return -c if opposes(status, objective) else c
