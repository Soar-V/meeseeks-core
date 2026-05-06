from __future__ import annotations

import pytest


def _make_output(**kwargs):
    from meeseeks.meeseeks.research_prospect import ResearchProspectMeeseeks

    defaults = {
        "business_name": "Acme Corp",
        "found": True,
        "sources_consulted": 0,
    }
    defaults.update(kwargs)
    return ResearchProspectMeeseeks.Output(**defaults)


def _make_activity(**kwargs):
    from meeseeks.meeseeks.research_prospect import Activity

    defaults = {
        "summary": "Opened a new downtown location.",
        "source_url": "https://example.com/news/new-location",
        "confidence": "high",
    }
    defaults.update(kwargs)
    return Activity(**defaults)


def _meeseeks():
    from meeseeks.meeseeks.research_prospect import ResearchProspectMeeseeks

    return ResearchProspectMeeseeks()


# --- format() tests ---

def test_format_not_found_contains_not_found():
    m = _meeseeks()
    output = _make_output(found=False, notes="No website found after three attempts.")
    result = m.format(output)
    assert "not found" in result


def test_format_found_no_activity_contains_no_recent_activity():
    m = _meeseeks()
    output = _make_output(found=True)
    result = m.format(output)
    assert "no recent activity" in result


def test_format_found_with_activity_contains_name_and_summary():
    m = _meeseeks()
    activity = _make_activity(summary="Opened a Plano expansion in March.")
    output = _make_output(
        found=True,
        recent_activity=[activity],
        opening_hooks=["The Plano expansion suggests growing capacity — is after-hours the next bottleneck?"],
        sources_consulted=3,
    )
    result = m.format(output)
    assert "Acme Corp" in result
    assert "Opened a Plano expansion in March." in result


# --- validate_output() tests ---

def test_validate_output_empty_source_url_returns_failure_reason():
    m = _meeseeks()
    activity = _make_activity(source_url="", confidence="low")
    output = _make_output(found=True, recent_activity=[activity], sources_consulted=1)
    reason = m.validate_output(output, set())
    assert reason is not None
    assert isinstance(reason, str)
    assert len(reason) > 0


def test_validate_output_high_confidence_url_not_fetched_returns_failure_reason():
    m = _meeseeks()
    activity = _make_activity(
        source_url="https://example.com/news/announcement",
        confidence="high",
    )
    output = _make_output(found=True, recent_activity=[activity], sources_consulted=1)
    reason = m.validate_output(output, set())
    assert reason is not None
    assert isinstance(reason, str)
    assert "hallucination_guard" in reason


def test_validate_output_high_confidence_url_in_fetched_passes():
    m = _meeseeks()
    url = "https://example.com/news/announcement"
    activity = _make_activity(source_url=url, confidence="high")
    output = _make_output(found=True, recent_activity=[activity], sources_consulted=1)
    reason = m.validate_output(output, {url})
    assert reason is None


def test_validate_output_medium_confidence_url_not_fetched_passes():
    m = _meeseeks()
    activity = _make_activity(
        source_url="https://example.com/news",
        confidence="medium",
    )
    output = _make_output(found=True, recent_activity=[activity], sources_consulted=1)
    reason = m.validate_output(output, set())
    assert reason is None


# --- registry test ---

def test_research_prospect_in_registry():
    import meeseeks.meeseeks.research_prospect  # noqa: F401 — triggers @register_meeseeks

    from meeseeks.registry import get_registry

    registry = get_registry()
    assert "research_prospect" in registry
