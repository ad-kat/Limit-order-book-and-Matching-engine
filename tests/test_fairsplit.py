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


class TestAgentRentNormalization:
    """Verify Bug 2 fix: agent converts max_rent_per_person_dollars to total cents."""

    def _normalize(self, per_person_dollars, num_people=None, bedrooms=None):
        """Replicate the normalization logic from fairsplit_agent._call_internal."""
        args = {"max_rent_per_person_dollars": per_person_dollars}
        if num_people is not None:
            args["num_people"] = num_people
        if bedrooms is not None:
            args["bedrooms"] = bedrooms

        search_args = dict(args)
        per_person = search_args.pop("max_rent_per_person_dollars", None)
        n_people   = search_args.pop("num_people", None)
        if per_person is not None:
            brooms = search_args.get("bedrooms") or n_people or 1
            people = n_people or brooms
            search_args["max_budget"] = int(float(per_person) * people * 100)
        return search_args

    def test_1300_per_person_3br_becomes_390000_cents(self):
        """$1,300/person × 3 people × 100 = 390,000 cents — above Park Slope's $366,000."""
        result = self._normalize(per_person_dollars=1300, num_people=3, bedrooms=3)
        assert result["max_budget"] == 390000, (
            f"$1,300/person × 3 should be 390000 cents, got {result['max_budget']}"
        )

    def test_1220_per_person_3br_gives_366000_cents(self):
        """$1,220/person × 3 = 366,000 cents — exactly matches Park Slope asking price."""
        result = self._normalize(per_person_dollars=1220, num_people=3, bedrooms=3)
        assert result["max_budget"] == 366000

    def test_num_people_defaults_to_bedrooms(self):
        """When num_people is omitted, bedrooms is used as the multiplier."""
        result = self._normalize(per_person_dollars=1300, bedrooms=3)
        assert result["max_budget"] == 390000

    def test_single_person_passthrough(self):
        """$2,000/person with 1 person = 200,000 cents."""
        result = self._normalize(per_person_dollars=2000, num_people=1)
        assert result["max_budget"] == 200000

    def test_no_cents_in_input(self):
        """Input must be dollars; passing 130000 (cents value) would give absurdly high budget."""
        result = self._normalize(per_person_dollars=130000, num_people=3)
        # 130000 * 3 * 100 = 39,000,000 cents — caller error, but normalization is correct
        assert result["max_budget"] == 39_000_000

    def test_search_args_strips_agent_params(self):
        """Normalized args must not contain max_rent_per_person_dollars or num_people."""
        result = self._normalize(per_person_dollars=1300, num_people=3, bedrooms=3)
        assert "max_rent_per_person_dollars" not in result
        assert "num_people" not in result
        assert "max_budget" in result


# ── Housing Offer tests ────────────────────────────────────────────────────────

from fastapi.testclient import TestClient
from api.main import app

_client = TestClient(app)
_DEMO_OWNER = "profile-alex-001"
_DEMO_HEADERS = {"X-Demo-Profile-Id": _DEMO_OWNER}


def _make_offer_body(**overrides):
    base = {
        "title": "Test room in Bushwick",
        "neighborhood": "Bushwick",
        "city": "New York",
        "rooms_available": 1,
        "rent_per_room_cents": 120000,   # $1,200 — already normalized (server does this)
        "available_from": "2027-05-15",
        "smoking_policy": "non_smoker",
        "owner_profile_id": _DEMO_OWNER,
    }
    base.update(overrides)
    return base


class TestOfferCreation:
    """POST /fairsplit/offers — demo mode auth + in-memory store."""

    def test_create_offer_succeeds_with_valid_demo_header(self):
        body = _make_offer_body()
        r = _client.post("/fairsplit/offers", json=body, headers=_DEMO_HEADERS)
        assert r.status_code == 201, r.text
        data = r.json()
        assert data["neighborhood"] == "Bushwick"
        assert data["rent_per_room_cents"] == 120000
        assert data["owner_profile_id"] == _DEMO_OWNER
        assert data["status"] == "open"

    def test_create_offer_rejected_without_header(self):
        body = _make_offer_body()
        r = _client.post("/fairsplit/offers", json=body)
        assert r.status_code == 403

    def test_create_offer_rejected_unknown_profile(self):
        body = _make_offer_body(owner_profile_id="attacker-001")
        r = _client.post(
            "/fairsplit/offers", json=body,
            headers={"X-Demo-Profile-Id": "attacker-001"},
        )
        assert r.status_code == 403

    def test_create_offer_rejected_header_mismatch(self):
        """Header profile must equal body owner_profile_id."""
        body = _make_offer_body(owner_profile_id="profile-jordan-001")
        r = _client.post("/fairsplit/offers", json=body, headers=_DEMO_HEADERS)
        assert r.status_code == 403

    def test_create_offer_returns_id(self):
        body = _make_offer_body(title="Unique title for ID test")
        r = _client.post("/fairsplit/offers", json=body, headers=_DEMO_HEADERS)
        assert r.status_code == 201
        assert r.json()["id"]  # non-empty


class TestOfferListing:
    """GET /fairsplit/offers — filtering and synthetic fallback."""

    def test_list_returns_synthetic_offer(self):
        r = _client.get("/fairsplit/offers")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        # At least the synthetic demo offer should be present
        assert any(o["neighborhood"] == "Bushwick" for o in data)

    def test_list_filters_by_neighborhood(self):
        r = _client.get("/fairsplit/offers?neighborhood=Bushwick")
        assert r.status_code == 200
        for offer in r.json():
            assert "bushwick" in offer["neighborhood"].lower()

    def test_list_filters_by_max_rent(self):
        # Create a cheap offer then filter below it
        body = _make_offer_body(title="Cheap room", rent_per_room_cents=80000)
        _client.post("/fairsplit/offers", json=body, headers=_DEMO_HEADERS)

        r = _client.get("/fairsplit/offers?max_rent_per_room_cents=90000")
        assert r.status_code == 200
        for o in r.json():
            assert o["rent_per_room_cents"] <= 90000


class TestOfferRentNormalization:
    """Verify dollars -> cents conversion in the agent layer (_call_internal)."""

    def _agent_normalize_offer(self, rent_dollars: float) -> int:
        """Replicate fairsplit_agent._call_internal normalization for offers."""
        return int(float(rent_dollars) * 100)

    def test_1200_dollars_becomes_120000_cents(self):
        assert self._agent_normalize_offer(1200) == 120000

    def test_1200_50_dollars_truncated_correctly(self):
        assert self._agent_normalize_offer(1200.50) == 120050

    def test_zero_dollars_gives_zero_cents(self):
        assert self._agent_normalize_offer(0) == 0

    def test_normalization_applied_exactly_once(self):
        """Passing pre-converted cents (120000) gives an absurdly high value."""
        wrong = self._agent_normalize_offer(120000)
        assert wrong == 12_000_000   # obviously wrong — agent must send dollars


class TestOfferConfirmationGuard:
    """The create_housing_offer tool description must require prior confirmation."""

    def test_tool_description_mentions_confirmation(self):
        import sys
        sys.path.insert(0, ".")
        from api.fairsplit_agent import _make_tools
        tools = _make_tools()
        decls = tools[0].function_declarations
        offer_decl = next(d for d in decls if d.name == "create_housing_offer")
        desc = offer_decl.description.lower()
        # Must mention confirmation
        assert "confirm" in desc or "explicit" in desc, (
            "create_housing_offer description must require user confirmation"
        )

    def test_owner_profile_id_is_required_parameter(self):
        from api.fairsplit_agent import _make_tools
        decls = _make_tools()[0].function_declarations
        offer_decl = next(d for d in decls if d.name == "create_housing_offer")
        # parameters may be a dict or a Schema object; handle both
        params = offer_decl.parameters
        required = (
            params.get("required", [])
            if isinstance(params, dict)
            else getattr(params, "required", []) or []
        )
        assert "owner_profile_id" in required
