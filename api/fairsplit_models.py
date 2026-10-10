"""
fairsplit_models.py — Pydantic models for FairSplit API.
"""
from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field


# ── Enums ──────────────────────────────────────────────────────────────────────

class SmokingPreference(str, Enum):
    non_smoker   = "non_smoker"
    smoker       = "smoker"
    no_preference = "no_preference"


class GroupStatus(str, Enum):
    forming   = "forming"
    complete  = "complete"
    cancelled = "cancelled"


class MemberStatus(str, Enum):
    pending  = "pending"
    accepted = "accepted"
    declined = "declined"


# ── Apartments ─────────────────────────────────────────────────────────────────

class ApartmentOut(BaseModel):
    id:              str
    title:           str
    neighborhood:    str
    city:            str
    monthly_rent:    int          # cents
    bedrooms:        int
    available_from:  str          # ISO date string
    description:     Optional[str] = None
    is_synthetic:    bool = False
    per_person_rent: int = 0      # computed: monthly_rent / bedrooms (rounded up)

    model_config = {"from_attributes": True}


class ApartmentSearchRequest(BaseModel):
    max_budget:           Optional[int]   = None   # cents per month (total)
    neighborhood:         Optional[str]   = None
    bedrooms:             Optional[int]   = None
    available_before:     Optional[str]   = None   # ISO date
    smoking_preference:   Optional[SmokingPreference] = None
    limit:                int             = Field(20, ge=1, le=100)


# ── Housing Preferences ────────────────────────────────────────────────────────

class HousingPreferencesIn(BaseModel):
    maximum_monthly_budget:   int
    preferred_neighborhoods:  list[str] = []
    move_in_date:             str
    preferred_roommate_count: int = 2
    smoking_preference:       SmokingPreference = SmokingPreference.no_preference
    additional_requirements:  Optional[str] = None


# ── Match ──────────────────────────────────────────────────────────────────────

class MatchRequest(BaseModel):
    apartment_id:  str
    candidate_ids: list[str] = Field(default_factory=list,
                                      description="Profile IDs to consider; empty = use all")


class CandidateOut(BaseModel):
    id:                      str
    display_name:            str
    max_budget:              int
    move_in_date:            str
    smoking_preference:      str
    preferred_roommate_count: int


class RoommateGroupOut(BaseModel):
    members:     list[CandidateOut]
    score:       float
    explanation: str


class MatchResponse(BaseModel):
    apartment_id:      str
    per_person_rent:   int
    top_groups:        list[RoommateGroupOut]
    candidate_count:   int


# ── Groups ─────────────────────────────────────────────────────────────────────

class GroupMemberOut(BaseModel):
    id:           str
    profile_id:   str
    display_name: Optional[str] = None
    status:       str


class GroupOut(BaseModel):
    id:           str
    apartment_id: str
    apartment:    Optional[ApartmentOut] = None
    created_by:   Optional[str] = None
    status:       str
    members:      list[GroupMemberOut] = []
    created_at:   Optional[str] = None


class ProposeGroupRequest(BaseModel):
    apartment_id: str
    created_by:   str              # profile ID of proposer
    member_ids:   list[str] = []   # additional member profile IDs


class InviteRequest(BaseModel):
    inviter_profile_id: str
    invitee_profile_id: str


class InviteResponse(BaseModel):
    invitation_id: str
    group_id:      str
    invitee_id:    str
    token:         str
    message:       str


class AcceptInvitationResponse(BaseModel):
    group_id:  str
    member_id: str
    status:    str
    message:   str


# ── Profiles ───────────────────────────────────────────────────────────────────

class ProfileGroupsResponse(BaseModel):
    profile_id: str
    groups:     list[GroupOut]


# ── Housing Offers (room-provider proposals) ───────────────────────────────────

class OfferStatus(str, Enum):
    open   = "open"
    filled = "filled"
    closed = "closed"


class HousingOfferCreate(BaseModel):
    """Body for POST /fairsplit/offers.

    rent_per_room_cents is normalized once server-side from dollars — callers
    never send cents directly to avoid double-conversion bugs.
    """
    title:               str
    city:                str = "New York"
    neighborhood:        str
    rooms_available:     int = Field(1, ge=1, le=10)
    rent_per_room_cents: int = Field(..., ge=1, description="Monthly rent per room in cents")
    available_from:      str                         # ISO date YYYY-MM-DD
    smoking_policy:      str = "no_preference"       # non_smoker | smoker | no_preference
    description:         Optional[str] = None
    owner_profile_id:    str


class HousingOfferOut(BaseModel):
    id:                  str
    owner_profile_id:    Optional[str] = None   # NULL in legacy Supabase rows
    title:               str
    city:                str
    neighborhood:        str
    rooms_available:     int
    rent_per_room_cents: int
    available_from:      str
    smoking_policy:      str
    description:         Optional[str] = None
    status:              str = "open"
    is_synthetic:        bool = False
    created_at:          Optional[str] = None
