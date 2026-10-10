"""
test_fairsplit.py — pytest tests for FairSplit housing matcher.

Tests run without Supabase (uses C++ matcher binary directly via Python fallback).
"""
from __future__ import annotations

import asyncio
import math
import os
import sys

import pytest

# Add repo root to path so we can import api modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_candidate(id_: str, budget: int, move_in: str = "2026-11-01",
                    smoke: str = "non_smoker", name: str | None = None):
    return {
        "id": id_,
        "display_name": name or id_,
        "max_budget": budget,
        "move_in_date": move_in,
        "smoking_preference": smoke,
        "preferred_roommate_count": 2,
    }


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ── Import matcher (falls back to Python implementation) ─────────────────────

from api.fairsplit import _python_matcher_fallback, _call_cpp_matcher


# ── Tests ──────────────────────────────────────────────────────────────────────

class TestBudgetRejection:
    """Candidates over budget must be excluded."""

    def test_over_budget_excluded(self):
        per_person = 130000  # $1,300

        candidates = [
            _make_candidate("a1", 130000),  # exact — OK
            _make_candidate("a2", 140000),  # slack — OK
            _make_candidate("a3", 120000),  # OVER BUDGET — reject
        ]

        # Need capacity=2 to form a group
        groups = _python_matcher_fallback(2, per_person, candidates)

        # All returned groups must only contain affordable candidates
        for g in groups:
            for m in g["members"]:
                assert m["max_budget"] >= per_person, \
                    f"Member {m['id']} (budget={m['max_budget']}) below per_person={per_person}"

    def test_all_over_budget_returns_empty(self):
        per_person = 200000
        candidates = [
            _make_candidate("x1", 100000),
            _make_candidate("x2", 150000),
            _make_candidate("x3", 180000),
        ]
        groups = _python_matcher_fallback(2, per_person, candidates)
        assert groups == [], "Expected no groups when all candidates are over budget"

    def test_exactly_at_budget_accepted(self):
        per_person = 122000
        candidates = [
            _make_candidate("e1", 122000),  # exactly at budget
            _make_candidate("e2", 130000),
        ]
        groups = _python_matcher_fallback(2, per_person, candidates)
        assert len(groups) >= 1, "Expected at least 1 group when budget exactly matches"


class TestMoveInDateCompatibility:
    """Move-in dates must be within 30 days of each other."""

    def test_dates_within_30_days_allowed(self):
        candidates = [
            _make_candidate("d1", 150000, "2026-11-01"),
            _make_candidate("d2", 150000, "2026-11-28"),  # 27 days apart — OK
        ]
        groups = _python_matcher_fallback(2, 100000, candidates)
        assert len(groups) >= 1, "Dates 27 days apart should be compatible"

    def test_dates_over_30_days_rejected(self):
        candidates = [
            _make_candidate("d3", 150000, "2026-11-01"),
            _make_candidate("d4", 150000, "2026-12-15"),  # 44 days apart — reject
        ]
        groups = _python_matcher_fallback(2, 100000, candidates)
        assert groups == [], "Dates 44 days apart should be incompatible"

    def test_exactly_30_days_allowed(self):
        candidates = [
            _make_candidate("d5", 150000, "2026-11-01"),
            _make_candidate("d6", 150000, "2026-12-01"),  # exactly 30 days
        ]
        groups = _python_matcher_fallback(2, 100000, candidates)
        assert len(groups) >= 1, "Exactly 30 days should be allowed"


class TestSmokingCompatibility:
    """Smokers and non-smokers must not be mixed."""

    def test_smoker_nonsmoker_mismatch_rejected(self):
        candidates = [
            _make_candidate("s1", 150000, smoke="smoker"),
            _make_candidate("s2", 150000, smoke="non_smoker"),
        ]
        groups = _python_matcher_fallback(2, 100000, candidates)
        assert groups == [], "Smoker+non_smoker should be incompatible"

    def test_both_nonsmoker_accepted(self):
        candidates = [
            _make_candidate("s3", 150000, smoke="non_smoker"),
            _make_candidate("s4", 150000, smoke="non_smoker"),
        ]
        groups = _python_matcher_fallback(2, 100000, candidates)
        assert len(groups) >= 1

    def test_no_preference_is_neutral(self):
        candidates = [
            _make_candidate("s5", 150000, smoke="non_smoker"),
            _make_candidate("s6", 150000, smoke="no_preference"),
        ]
        groups = _python_matcher_fallback(2, 100000, candidates)
        assert len(groups) >= 1, "no_preference should be compatible with non_smoker"


class TestGroupCapacity:
    """Group size must equal apartment capacity."""

    def test_capacity_respected(self):
        candidates = [_make_candidate(f"c{i}", 150000) for i in range(5)]
        groups_2 = _python_matcher_fallback(2, 100000, candidates)
        for g in groups_2:
            assert len(g["members"]) == 2

    def test_capacity_3(self):
        candidates = [_make_candidate(f"c{i}", 150000) for i in range(5)]
        groups_3 = _python_matcher_fallback(3, 100000, candidates)
        for g in groups_3:
            assert len(g["members"]) == 3

    def test_capacity_exceeds_candidates_returns_empty(self):
        candidates = [_make_candidate("c1", 150000), _make_candidate("c2", 150000)]
        groups = _python_matcher_fallback(5, 100000, candidates)
        assert groups == []


class TestDeterministicRanking:
    """Same input must produce same ranked output (deterministic)."""

    def test_deterministic(self):
        candidates = [
            _make_candidate("r1", 180000, "2026-11-01", "non_smoker"),
            _make_candidate("r2", 130000, "2026-11-03", "non_smoker"),
            _make_candidate("r3", 155000, "2026-11-10", "non_smoker"),
        ]
        g1 = _python_matcher_fallback(2, 120000, candidates)
        g2 = _python_matcher_fallback(2, 120000, candidates)
        assert len(g1) == len(g2)
        for a, b in zip(g1, g2):
            assert a["score"] == b["score"]
            ids_a = sorted(m["id"] for m in a["members"])
            ids_b = sorted(m["id"] for m in b["members"])
            assert ids_a == ids_b

    def test_higher_budget_slack_ranks_higher(self):
        """Group with more budget slack should score higher."""
        candidates_high = [
            _make_candidate("h1", 200000, "2026-11-01"),
            _make_candidate("h2", 190000, "2026-11-02"),
        ]
        candidates_low = [
            _make_candidate("l1", 125000, "2026-11-01"),
            _make_candidate("l2", 122000, "2026-11-02"),
        ]

        all_candidates = candidates_high + candidates_low
        groups = _python_matcher_fallback(2, 120000, all_candidates)
        assert len(groups) >= 2
        # High-budget group should rank first
        assert groups[0]["score"] > groups[1]["score"]
        top_ids = {m["id"] for m in groups[0]["members"]}
        assert "h1" in top_ids or "h2" in top_ids


class TestDuplicateInvitationProtection:
    """POST /groups/{id}/invite must not create duplicate invitations."""

    def test_duplicate_invitation_returns_same_id(self):
        # Import the in-memory invitation store
        from api.fairsplit import _invitations, create_invitation
        from api.fairsplit_models import InviteRequest

        _invitations.clear()
        group_id = "test-group-001"
        req = InviteRequest(
            inviter_profile_id="profile-a",
            invitee_profile_id="profile-b",
        )

        result1 = _run(create_invitation(group_id, req))
        result2 = _run(create_invitation(group_id, req))

        assert result1.invitation_id == result2.invitation_id, \
            "Duplicate invitation should return the same ID"
        assert result2.message == "Invitation already exists"


class TestInvalidApartmentId:
    """Invalid apartment IDs should return 404."""

    def test_get_invalid_apartment_raises_404(self):
        from api.fairsplit import get_apartment
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            _run(get_apartment("nonexistent-apt-id-xyz"))

        assert exc_info.value.status_code == 404

    def test_match_invalid_apartment_raises_404(self):
        from api.fairsplit import find_compatible_roommates
        from api.fairsplit_models import MatchRequest
        from fastapi import HTTPException

        req = MatchRequest(apartment_id="totally-fake-id-12345")
        with pytest.raises(HTTPException) as exc_info:
            _run(find_compatible_roommates(req))

        assert exc_info.value.status_code == 404


class TestDemoScenario:
    """Verify the required demo scenario: Brooklyn 3BR $3,660, 3 non-smokers."""

    def test_demo_trio_forms_valid_group(self):
        """Three candidates matching the demo spec should produce at least 1 group."""
        per_person = math.ceil(366000 / 3)  # $1,220
        candidates = [
            _make_candidate("demo1", 130000, "2026-11-01", "non_smoker", "Alex Chen"),
            _make_candidate("demo2", 132000, "2026-11-05", "non_smoker", "Jordan Lee"),
            _make_candidate("demo3", 135000, "2026-11-10", "non_smoker", "Sam Rivera"),
        ]
        groups = _python_matcher_fallback(3, per_person, candidates)
        assert len(groups) >= 1, "Demo trio should form at least 1 group"
        assert len(groups[0]["members"]) == 3

    def test_per_person_rent_calculation(self):
        """$3,660 / 3 bedrooms = $1,220/person (ceiling division)."""
        monthly = 366000  # cents
        bedrooms = 3
        per_person = math.ceil(monthly / bedrooms)
        assert per_person == 122000, f"Expected 122000 cents ($1,220), got {per_person}"
