"""Tests for the reversal check and the REVERSAL tag."""

from pathlib import Path

import pytest

from warden.core import Warden, format_result_line
from warden.reversal import check_reversal

BUILD = "Build API wrapper for IntentGraph with /score and /debug endpoints"


@pytest.mark.parametrize("status,kind", [
    ("Deleting the /score and /debug endpoints from the IntentGraph API wrapper", "remove"),
    ("Reverting the API wrapper changes for IntentGraph", "undo"),
    ("Rolling back the /score endpoint", "undo"),
    ("Calling IntentGraph directly instead of building the API wrapper", "undo"),
    ("Disabling the /debug endpoint", "remove"),
])
def test_reversals_of_a_constructive_objective(status, kind):
    result = check_reversal(status, BUILD)
    assert result.reversal and result.kind == kind and result.cue


@pytest.mark.parametrize("status", [
    "Building the /score endpoint in the IntentGraph API wrapper",
    "Wiring up FastAPI routers and Pydantic response models for the two handlers",
    "Testing the IntentGraph wrapper's /score and /debug endpoints",
])
def test_on_task_work_is_not_a_reversal(status):
    assert not check_reversal(status, BUILD).reversal


def test_unrelated_removal_is_not_a_reversal():
    # Off-task, but not undoing THIS objective: left to the matcher (DRIFT).
    assert not check_reversal("Deleting old log archives on the batch server", BUILD).reversal


def test_one_shared_word_is_enough_to_count_as_related():
    # Known weakness: relatedness is a single shared keyword. "build server"
    # shares "build" with the objective, so this unrelated removal is flagged.
    assert check_reversal("Deleting old log archives on the build server", BUILD).reversal


def test_the_objectives_own_word_is_not_a_cue():
    objective = "Refactor the auth middleware to remove duplicated session checks"
    assert not check_reversal(
        "Refactoring the auth middleware to remove duplicated session checks", objective
    ).reversal


def test_past_participle_is_not_a_cue():
    objective = "Upgrade the project from Python 3.9 to 3.12"
    assert not check_reversal(
        "Replacing the removed distutils import so the project runs on Python 3.12", objective
    ).reversal


def test_reductive_objective_flips_direction():
    objective = "Reduce the Docker image size for the web app"
    assert not check_reversal("Removing build caches from the Docker image", objective).reversal
    assert check_reversal("Increasing the Docker image size with debug tools", objective).reversal
    assert check_reversal("Reverting the Docker image size changes", objective).reversal


def test_empty_inputs():
    assert not check_reversal("", BUILD).reversal
    assert not check_reversal("Deleting things", "").reversal


def _warden(tmp_path: Path, status: str, **kw) -> dict:
    t = tmp_path / "s.log"
    t.write_text(f"WARDEN_STATUS: {status}\n")
    w = Warden(root=tmp_path / ".warden")
    w.watch(agent_id="a", objective=BUILD, transcript_path=str(t), **kw)
    result = w.check_once("a")
    result["_audit"] = w.audit.read(session="a")[0]
    return result


def test_check_tags_reversal_instead_of_match(tmp_path: Path):
    result = _warden(tmp_path, "Deleting the /score and /debug endpoints from the IntentGraph API wrapper")
    assert result["tag"] == "REVERSAL"
    assert result["word_tag"] == "MATCH"            # what the matcher alone would have said
    rec = result["_audit"]
    assert rec["reversal"] is True and rec["reversal_cue"] == "Deleting"
    assert rec["word_score"] > 0.7                   # scores are still recorded
    assert "undoing the objective" in rec["note"]
    assert "REVERSAL" in format_result_line(result) and "Deleting" in format_result_line(result)


def test_on_task_status_is_unaffected(tmp_path: Path):
    result = _warden(tmp_path, "Building the /score and /debug endpoints for the IntentGraph API wrapper")
    assert result["tag"] == "MATCH" and result["_audit"]["reversal"] is False


def test_reversal_check_can_be_switched_off(tmp_path: Path):
    result = _warden(
        tmp_path, "Deleting the /score and /debug endpoints from the IntentGraph API wrapper",
        reversal_check=False,
    )
    assert result["tag"] == "MATCH" and result["_audit"]["reversal"] is False
