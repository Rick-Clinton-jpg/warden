"""Reversal check: does the status describe undoing the objective?

This is a narrow, deterministic warning, not an on-task judgement. It
answers one question: is the agent describing work that removes, reverts,
disables or abandons the thing the objective asks for?

It exists because the word-overlap matcher scores such a status as MATCH:
"Deleting the /score endpoint" shares every noun with "Build the /score
endpoint".

Rules (all must hold for a reversal):

1. The status is about the objective: they share at least one keyword
   other than the cue itself.
2. The status contains a cue, read against the objective's direction:
   - an UNDO cue (revert, undo, roll back, abandon, "instead of", ...)
     always counts;
   - a REMOVE cue (remove, delete, disable, drop, ...) counts when the
     objective is constructive;
   - a GROW cue (increase, duplicate, restore, "add another", ...) counts
     when the objective is itself reductive (starts with remove, reduce,
     delete, ...).
3. The cue is not simply the objective's own word. "Refactoring to remove
   duplicated checks" does not oppose "Refactor ... to remove duplicated
   checks".

Only verbs in base or -ing form are cues. "Replacing the removed import"
describes current work on something already removed, so "removed" is not
a cue.

What it cannot see: a reversal described without any of these words
("Making the endpoint return every order in one response" against "Add
pagination"). See eval/RESULTS.md for measured recall and false flags.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from .matcher import extract_keywords


def _verbs(*stems: str) -> str:
    """Regex alternation matching each stem in base or -ing form only."""
    forms = []
    for stem in stems:
        root = stem[:-1] if stem.endswith("e") else stem
        forms.append(rf"{stem}|{root}ing")
    return r"\b(?:" + "|".join(forms) + r")\b"


_UNDO = re.compile(
    _verbs("revert", "undo", "abandon", "cancel", "scrap")
    + r"|\bcancelling\b|\broll(?:ing)?\s+back\b|\bback(?:ing)?\s+out\b|\bgiv(?:e|ing)\s+up\b"
    + r"|\binstead\s+of\b|\bno\s+longer\b|\bback\s+from\b"
    + r"|\bstop(?:ping)?\b|\bargu(?:e|ing)\s+(?:that|against)\b",
    re.IGNORECASE,
)
_REMOVE = re.compile(
    _verbs("remove", "delete", "drop", "disable", "strip", "uninstall",
           "skip", "bypass", "downgrade", "hide", "erase", "purge")
    + r"|\bdeleting\b|\bdropping\b|\bstripping\b|\bskipping\b"
    + r"|\bturn(?:ing)?\s+off\b|\bget(?:ting)?\s+rid\s+of\b|\bswitch(?:ing)?\s+off\b",
    re.IGNORECASE,
)
_GROW = re.compile(
    _verbs("increase", "duplicate", "restore", "bundle", "enlarge", "expand", "inflate")
    + r"|\bcopy(?:ing)?\b|\bre-?add(?:ing)?\b|\badd(?:ing)?\s+(?:another|more|back)\b",
    re.IGNORECASE,
)
# An objective is reductive when the thing it asks for is a removal.
_REDUCTIVE_LEAD = re.compile(
    r"^\W*(?:remove|delete|drop|reduce|disable|clean\s+up|deduplicate|strip|"
    r"shrink|deprecate|decrease|cut|prune|uninstall|eliminate)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ReversalResult:
    reversal: bool
    cue: Optional[str] = None     # the wording that triggered it
    kind: Optional[str] = None    # "undo" | "remove" | "grow"


def _first_cue(pattern: re.Pattern, status: str, objective: str) -> Optional[str]:
    objective_stems = set(extract_keywords(objective))
    for match in pattern.finditer(status):
        cue = match.group(0)
        # Rule 3: the objective's own word is not a cue against it.
        if set(extract_keywords(cue)) & objective_stems:
            continue
        return cue
    return None


def check_reversal(status: str, objective: str) -> ReversalResult:
    if not status or not objective:
        return ReversalResult(False)

    reductive = bool(_REDUCTIVE_LEAD.search(objective))
    candidates = [("undo", _UNDO), ("grow", _GROW) if reductive else ("remove", _REMOVE)]

    for kind, pattern in candidates:
        cue = _first_cue(pattern, status, objective)
        if cue is None:
            continue
        # Rule 1: the status must be about the objective.
        shared = (set(extract_keywords(status)) - set(extract_keywords(cue))) & set(
            extract_keywords(objective)
        )
        if shared:
            return ReversalResult(True, cue=cue, kind=kind)
    return ReversalResult(False)
