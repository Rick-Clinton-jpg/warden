"""Tests for keyword matcher."""

from warden.matcher import (
    compare_status_to_objective,
    extract_keywords,
    similarity_score,
)


def test_extract_keywords_basic():
    kws = extract_keywords("Setting up FastAPI routes for score endpoints")
    assert "fastapi" in kws or "fastapi" in [k.lower() for k in kws]
    assert "route" in kws or "routes" in kws or any("rout" in k for k in kws)
    assert "the" not in kws
    assert "for" not in kws


def test_match_high_overlap():
    status = "Setting up FastAPI routes for /score and /debug endpoints"
    objective = "Build API wrapper for IntentGraph with /score and /debug endpoints"
    assert compare_status_to_objective(status, objective) in ("MATCH", "UNCLEAR")
    # Should be reasonably high
    assert similarity_score(status, objective) >= 0.15


def test_drift_clear():
    status = "Refactoring test suite for edge cases in scorer.py"
    objective = "Build API wrapper for IntentGraph with /score and /debug endpoints"
    tag = compare_status_to_objective(status, objective)
    # Likely DRIFT or UNCLEAR; should not be strong MATCH
    assert tag in ("DRIFT", "UNCLEAR")


def test_empty_status():
    assert compare_status_to_objective("", "Build something") == "UNCLEAR"
    assert compare_status_to_objective("   ", "Build something") == "UNCLEAR"


def test_identical():
    text = "Implement authentication middleware for the API"
    assert compare_status_to_objective(text, text) == "MATCH"
    assert similarity_score(text, text) == 1.0