"""Pins the disclosed scoring flaw (README, Known Issues / Limitations).

These tests state the CORRECT behaviour and are marked xfail(strict=True):
today they fail, which CI accepts. The day the matcher is fixed they pass,
and a strict xfail that passes fails the build -- forcing whoever fixed it
to remove the marker and update the README. The flaw cannot be silently
fixed or silently forgotten.
"""

import pytest

from warden.matcher import dual_compare, similarity_score, trigram_score

OBJECTIVE = "Build API wrapper for IntentGraph with /score and /debug endpoints"
ON_TASK = "Wiring up FastAPI routers for the two handlers"
OFF_TASK = "Deleting the /score and /debug endpoints"

KNOWN_FLAW = "README Known Issues: scorer measures vocabulary overlap, not direction"


@pytest.mark.xfail(strict=True, reason=KNOWN_FLAW)
def test_word_rater_ranks_on_task_above_off_task():
    assert similarity_score(ON_TASK, OBJECTIVE) > similarity_score(OFF_TASK, OBJECTIVE)


@pytest.mark.xfail(strict=True, reason=KNOWN_FLAW)
def test_trigram_rater_ranks_on_task_above_off_task():
    assert trigram_score(ON_TASK, OBJECTIVE) > trigram_score(OFF_TASK, OBJECTIVE)


@pytest.mark.xfail(strict=True, reason=KNOWN_FLAW)
def test_on_task_work_in_different_words_is_not_tagged_drift():
    assert dual_compare(ON_TASK, OBJECTIVE).final_tag != "DRIFT"
