"""
fairsplit.py — FastAPI router for FairSplit housing platform.

Mounts on the existing LOB app via:
    from .fairsplit import fairsplit_router
    app.include_router(fairsplit_router)

If SUPABASE_URL is not set, all endpoints return synthetic in-memory data
so the demo works without a live Supabase project.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import os
import secrets
import subprocess
from datetime import date, datetime, timedelta
from typing import Any, Optional

from fastapi import APIRouter, Header, HTTPException, WebSocket, WebSocketDisconnect

from .fairsplit_models import (
    AcceptInvitationResponse,
    ApartmentOut,
    ApartmentSearchRequest,
    CandidateOut,
    GroupMemberOut,
    GroupOut,
    HousingOfferCreate,
    HousingOfferOut,
    InviteRequest,
    InviteResponse,
    MatchRequest,
    MatchResponse,
    ProfileGroupsResponse,
    ProposeGroupRequest,
    RoommateGroupOut,
)

logger = logging.getLogger("fairsplit.api")

fairsplit_router = APIRouter(prefix="/fairsplit", tags=["FairSplit"])

# ── Supabase client (optional) ─────────────────────────────────────────────────

_supabase = None

def _get_supabase():
    """Return a Supabase client using the service role key (bypasses RLS).
    The service key is used only in trusted backend code and never sent to the browser."""
    global _supabase
    if _supabase is not None:
        return _supabase
    url = os.getenv("SUPABASE_URL")
    # Prefer service key (bypasses RLS); fall back to anon key for read-only ops
    key = os.getenv("SUPABASE_SERVICE_KEY") or os.getenv("SUPABASE_KEY")
    if not url or not key:
        return None
    try:
        from supabase import create_client
        _supabase = create_client(url, key)
        logger.info("[fairsplit] Supabase client initialized (service key)")
        return _supabase
    except Exception as e:
        logger.warning(f"[fairsplit] Supabase init failed: {e}")
        return None


def _using_supabase() -> bool:
    return _get_supabase() is not None


# ── C++ matcher bridge ─────────────────────────────────────────────────────────

_MATCHER_BINARY = os.getenv("HOUSING_MATCHER_BINARY", "./build/housing_matcher")

async def _call_cpp_matcher(capacity: int, per_person_rent: int,
                             candidates: list[dict]) -> list[dict]:
    """Call the housing_matcher C++ binary with the MATCH command."""
    binary = _MATCHER_BINARY
    if not os.path.isfile(binary):
        # Try build-release path
        alt = os.path.join(os.path.dirname(__file__), "..", "build-release", "housing_matcher")
        if os.path.isfile(alt):
            binary = alt
        else:
            logger.warning("[fairsplit] housing_matcher binary not found; using Python fallback")
            return _python_matcher_fallback(capacity, per_person_rent, candidates)

    try:
        proc = await asyncio.create_subprocess_exec(
            binary,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        # Wait for READY
        ready_line = await asyncio.wait_for(proc.stdout.readline(), timeout=5.0)
        if b"READY" not in ready_line:
            raise RuntimeError(f"matcher did not send READY: {ready_line}")

        # Send MATCH command
        candidates_json = json.dumps(candidates)
        cmd = f"MATCH {capacity} {per_person_rent} {candidates_json}\n"
        proc.stdin.write(cmd.encode())
        await proc.stdin.drain()

        # Read RESULT line
        result_line = await asyncio.wait_for(proc.stdout.readline(), timeout=10.0)
        result_str = result_line.decode().strip()

        # Read OK
        await asyncio.wait_for(proc.stdout.readline(), timeout=5.0)

        proc.stdin.write(b"QUIT\n")
        await proc.stdin.drain()
        try:
            await asyncio.wait_for(proc.wait(), timeout=3.0)
        except asyncio.TimeoutError:
            proc.kill()

        if result_str.startswith("RESULT "):
            return json.loads(result_str[7:])
        elif result_str.startswith("ERROR "):
            raise RuntimeError(result_str[6:])
        else:
            raise RuntimeError(f"unexpected matcher output: {result_str}")

    except Exception as e:
        logger.warning(f"[fairsplit] C++ matcher error: {e}; using Python fallback")
        return _python_matcher_fallback(capacity, per_person_rent, candidates)


def _python_matcher_fallback(capacity: int, per_person_rent: int,
                              candidates: list[dict]) -> list[dict]:
    """Pure-Python fallback matching when C++ binary is unavailable."""
    import itertools

    def parse_date(s: str) -> int:
        try:
            d = datetime.strptime(s, "%Y-%m-%d")
            return d.year * 365 + d.month * 30 + d.day
        except Exception:
            return 0

    def is_compatible(group):
        for c in group:
            if c.get("max_budget", 0) < per_person_rent:
                return False
        dates = [parse_date(c.get("move_in_date", "2026-01-01")) for c in group]
        if max(dates) - min(dates) > 30:
            return False
        smokes = [c.get("smoking_preference", "no_preference") for c in group]
        has_smoker = "smoker" in smokes
        has_non = "non_smoker" in smokes
        if has_smoker and has_non:
            return False
        return True

    def score(group):
        total = 0.0
        dates = [parse_date(c.get("move_in_date", "2026-01-01")) for c in group]
        spread = max(dates) - min(dates) if dates else 0
        overlap = max(0.0, 30.0 - spread)
        smokes = [c.get("smoking_preference", "no_preference") for c in group]
        same_smoke = len(set(s for s in smokes if s != "no_preference")) <= 1
        for c in group:
            slack = (c.get("max_budget", 0) - per_person_rent) / max(per_person_rent, 1) * 100
            total += slack
        total += overlap * len(group)
        if same_smoke:
            total += 10 * len(group)
        return total

    groups = []
    if capacity < 1 or capacity > len(candidates):
        return []

    for combo in itertools.combinations(candidates, capacity):
        group = list(combo)
        if is_compatible(group):
            s = score(group)
            names = [c.get("display_name", c.get("id", "?")) for c in group]
            explanation = f"Score={int(s)}; members: {', '.join(names)}"
            groups.append({"score": s, "explanation": explanation, "members": group})

    groups.sort(key=lambda g: g["score"], reverse=True)
    return groups[:3]


# ── Synthetic in-memory data ───────────────────────────────────────────────────

SYNTHETIC_APTS = [
    {
        "id": "apt-brooklyn-3br-001",
        "title": "Sunny 3BR in Park Slope",
        "neighborhood": "Park Slope",
        "city": "New York",
        "monthly_rent": 366000,  # $3,660
        "bedrooms": 3,
        "available_from": "2026-11-01",
        "description": "Bright 3-bedroom apartment in Park Slope, close to Prospect Park.",
        "is_synthetic": True,
    },
    {
        "id": "apt-brooklyn-2br-001",
        "title": "Cozy 2BR in Williamsburg",
        "neighborhood": "Williamsburg",
        "city": "New York",
        "monthly_rent": 340000,
        "bedrooms": 2,
        "available_from": "2026-11-15",
        "description": "Renovated 2-bedroom in the heart of Williamsburg.",
        "is_synthetic": True,
    },
    {
        "id": "apt-manhattan-1br-001",
        "title": "Studio in Murray Hill",
        "neighborhood": "Murray Hill",
        "city": "New York",
        "monthly_rent": 280000,
        "bedrooms": 1,
        "available_from": "2026-10-15",
        "description": "Modern studio in Murray Hill.",
        "is_synthetic": True,
    },
    {
        "id": "apt-queens-3br-001",
        "title": "Spacious 3BR in Astoria",
        "neighborhood": "Astoria",
        "city": "New York",
        "monthly_rent": 320000,
        "bedrooms": 3,
        "available_from": "2026-11-01",
        "description": "Large 3-bedroom near the N/W trains.",
        "is_synthetic": True,
    },
    {
        "id": "apt-brooklyn-4br-001",
        "title": "4BR Townhouse in Crown Heights",
        "neighborhood": "Crown Heights",
        "city": "New York",
        "monthly_rent": 480000,
        "bedrooms": 4,
        "available_from": "2026-12-01",
        "description": "Spacious townhouse perfect for 4 roommates.",
        "is_synthetic": True,
    },
]

SYNTHETIC_PROFILES = [
    {"id": "profile-alex-001", "display_name": "Alex Chen", "max_budget": 130000,
     "move_in_date": "2026-11-01", "smoking_preference": "non_smoker", "preferred_roommate_count": 2},
    {"id": "profile-jordan-001", "display_name": "Jordan Lee", "max_budget": 135000,
     "move_in_date": "2026-11-05", "smoking_preference": "non_smoker", "preferred_roommate_count": 2},
    {"id": "profile-sam-001", "display_name": "Sam Rivera", "max_budget": 140000,
     "move_in_date": "2026-11-10", "smoking_preference": "non_smoker", "preferred_roommate_count": 2},
    {"id": "profile-taylor-001", "display_name": "Taylor Kim", "max_budget": 125000,
     "move_in_date": "2026-11-03", "smoking_preference": "no_preference", "preferred_roommate_count": 2},
    {"id": "profile-morgan-001", "display_name": "Morgan Patel", "max_budget": 160000,
     "move_in_date": "2026-11-15", "smoking_preference": "no_preference", "preferred_roommate_count": 3},
]

SYNTHETIC_GROUPS = [
    {
        "id": "group-001",
        "apartment_id": "apt-brooklyn-3br-001",
        "created_by": "profile-alex-001",
        "status": "forming",
        "members": [
            {"id": "gm-001", "profile_id": "profile-alex-001", "display_name": "Alex Chen", "status": "accepted"},
            {"id": "gm-002", "profile_id": "profile-jordan-001", "display_name": "Jordan Lee", "status": "pending"},
        ],
        "created_at": "2026-10-05T12:00:00Z",
    },
]

# In-memory invitation store (for demo without Supabase)
_invitations: dict[str, dict] = {}


def _apt_out(apt: dict) -> ApartmentOut:
    per_person = math.ceil(apt["monthly_rent"] / apt["bedrooms"])
    return ApartmentOut(
        id=apt["id"],
        title=apt["title"],
        neighborhood=apt["neighborhood"],
        city=apt["city"],
        monthly_rent=apt["monthly_rent"],
        bedrooms=apt["bedrooms"],
        available_from=apt["available_from"],
        description=apt.get("description"),
        is_synthetic=apt.get("is_synthetic", False),
        per_person_rent=per_person,
    )


# ── Apartment endpoints ────────────────────────────────────────────────────────

@fairsplit_router.get("/apartments", response_model=list[ApartmentOut])
async def list_apartments():
    if _using_supabase():
        try:
            sb = _get_supabase()
            res = sb.table("apartments").select("*").execute()
            apts = res.data or []
        except Exception as e:
            logger.warning(f"[fairsplit] Supabase error: {e}")
            apts = SYNTHETIC_APTS
    else:
        apts = SYNTHETIC_APTS
    return [_apt_out(a) for a in apts]


@fairsplit_router.get("/apartments/{apartment_id}", response_model=ApartmentOut)
async def get_apartment(apartment_id: str):
    if _using_supabase():
        try:
            sb = _get_supabase()
            res = sb.table("apartments").select("*").eq("id", apartment_id).execute()
            if res.data:
                return _apt_out(res.data[0])
        except Exception as e:
            logger.warning(f"[fairsplit] Supabase error: {e}")

    # Fallback to synthetic
    for apt in SYNTHETIC_APTS:
        if apt["id"] == apartment_id:
            return _apt_out(apt)
    raise HTTPException(status_code=404, detail=f"Apartment {apartment_id!r} not found")


@fairsplit_router.post("/search", response_model=list[ApartmentOut])
async def search_apartments(req: ApartmentSearchRequest):
    if _using_supabase():
        try:
            sb = _get_supabase()
            query = sb.table("apartments").select("*")
            if req.max_budget:
                query = query.lte("monthly_rent", req.max_budget)
            if req.neighborhood:
                # Match neighborhood name OR city (e.g. "Brooklyn" matches Park Slope, Williamsburg, etc.)
                n = req.neighborhood
                query = query.or_(f"neighborhood.ilike.%{n}%,city.ilike.%{n}%")
            if req.bedrooms:
                query = query.eq("bedrooms", req.bedrooms)
            if req.available_before:
                query = query.lte("available_from", req.available_before)
            res = query.limit(req.limit).execute()
            apts = res.data or []
            return [_apt_out(a) for a in apts]
        except Exception as e:
            logger.warning(f"[fairsplit] Supabase error: {e}")

    # Synthetic fallback
    results = []
    for apt in SYNTHETIC_APTS:
        if req.max_budget and apt["monthly_rent"] > req.max_budget:
            continue
        if req.neighborhood and req.neighborhood.lower() not in apt["neighborhood"].lower():
            continue
        if req.bedrooms and apt["bedrooms"] != req.bedrooms:
            continue
        results.append(_apt_out(apt))
        if len(results) >= req.limit:
            break
    return results


# ── Match endpoint ─────────────────────────────────────────────────────────────

@fairsplit_router.post("/match", response_model=MatchResponse)
async def find_compatible_roommates(req: MatchRequest):
    # Fetch apartment
    apt = None
    if _using_supabase():
        try:
            sb = _get_supabase()
            res = sb.table("apartments").select("*").eq("id", req.apartment_id).execute()
            if res.data:
                apt = res.data[0]
        except Exception as e:
            logger.warning(f"[fairsplit] Supabase error: {e}")

    if apt is None:
        for a in SYNTHETIC_APTS:
            if a["id"] == req.apartment_id:
                apt = a
                break

    if apt is None:
        raise HTTPException(status_code=404, detail=f"Apartment {req.apartment_id!r} not found")

    per_person = math.ceil(apt["monthly_rent"] / apt["bedrooms"])
    capacity = apt["bedrooms"]

    # Fetch candidates — always try Supabase first (with or without candidate_ids filter)
    candidates_raw = []
    if _using_supabase():
        try:
            sb = _get_supabase()
            # Join housing_preferences with profiles to get display_name
            prefs_res = sb.table("housing_preferences")\
                .select("profile_id,maximum_monthly_budget,move_in_date,smoking_preference,preferred_roommate_count,profiles(display_name)")\
                .execute()
            for row in (prefs_res.data or []):
                # Filter to requested candidates if a list was provided
                if req.candidate_ids and row["profile_id"] not in req.candidate_ids:
                    continue
                profile_info = row.get("profiles") or {}
                candidates_raw.append({
                    "id": row["profile_id"],
                    "display_name": profile_info.get("display_name", "Unknown"),
                    "max_budget": row["maximum_monthly_budget"],
                    "move_in_date": str(row["move_in_date"]),
                    "smoking_preference": row["smoking_preference"],
                    "preferred_roommate_count": row["preferred_roommate_count"],
                })
            logger.info(f"[fairsplit] Fetched {len(candidates_raw)} candidates from Supabase")
        except Exception as e:
            logger.warning(f"[fairsplit] Supabase candidate fetch error: {e}")

    if not candidates_raw:
        logger.warning("[fairsplit] Using synthetic candidates (Supabase unavailable)")
        candidates_raw = [
            {
                "id": p["id"],
                "display_name": p["display_name"],
                "max_budget": p["max_budget"],
                "move_in_date": p["move_in_date"],
                "smoking_preference": p["smoking_preference"],
                "preferred_roommate_count": p["preferred_roommate_count"],
            }
            for p in SYNTHETIC_PROFILES
        ]
        if req.candidate_ids:
            candidates_raw = [c for c in candidates_raw if c["id"] in req.candidate_ids]

    # Call C++ matcher
    groups_raw = await _call_cpp_matcher(capacity, per_person, candidates_raw)

    top_groups = []
    for g in groups_raw:
        members = [
            CandidateOut(
                id=m["id"],
                display_name=m["display_name"],
                max_budget=m["max_budget"],
                move_in_date=m["move_in_date"],
                smoking_preference=m["smoking_preference"],
                preferred_roommate_count=m["preferred_roommate_count"],
            )
            for m in g.get("members", [])
        ]
        top_groups.append(RoommateGroupOut(
            members=members,
            score=g.get("score", 0.0),
            explanation=g.get("explanation", ""),
        ))

    return MatchResponse(
        apartment_id=req.apartment_id,
        per_person_rent=per_person,
        top_groups=top_groups,
        candidate_count=len(candidates_raw),
    )


# ── Group endpoints ────────────────────────────────────────────────────────────

@fairsplit_router.post("/groups", response_model=GroupOut)
async def propose_group(req: ProposeGroupRequest):
    if _using_supabase():
        try:
            sb = _get_supabase()
            # Verify apartment exists
            apt_res = sb.table("apartments").select("id").eq("id", req.apartment_id).execute()
            if not apt_res.data:
                raise HTTPException(status_code=404, detail="Apartment not found")

            group_res = sb.table("roommate_groups").insert({
                "apartment_id": req.apartment_id,
                "created_by": req.created_by,
                "status": "forming",
            }).execute()
            group_id = group_res.data[0]["id"]

            # Add creator as accepted member
            all_members = [req.created_by] + req.member_ids
            for pid in all_members:
                status = "accepted" if pid == req.created_by else "pending"
                sb.table("group_members").insert({
                    "group_id": group_id,
                    "profile_id": pid,
                    "status": status,
                }).execute()

            return await get_group(group_id)
        except HTTPException:
            raise
        except Exception as e:
            logger.warning(f"[fairsplit] Supabase error: {e}")

    # Synthetic fallback
    import uuid
    group_id = str(uuid.uuid4())
    members = [{
        "id": str(uuid.uuid4()),
        "profile_id": req.created_by,
        "display_name": "You",
        "status": "accepted",
    }]
    for pid in req.member_ids:
        profile = next((p for p in SYNTHETIC_PROFILES if p["id"] == pid), None)
        members.append({
            "id": str(uuid.uuid4()),
            "profile_id": pid,
            "display_name": profile["display_name"] if profile else pid,
            "status": "pending",
        })
    return GroupOut(
        id=group_id,
        apartment_id=req.apartment_id,
        created_by=req.created_by,
        status="forming",
        members=[GroupMemberOut(**m) for m in members],
        created_at=datetime.utcnow().isoformat() + "Z",
    )


@fairsplit_router.get("/groups/{group_id}", response_model=GroupOut)
async def get_group(group_id: str):
    if _using_supabase():
        try:
            sb = _get_supabase()
            g_res = sb.table("roommate_groups").select("*").eq("id", group_id).execute()
            if not g_res.data:
                raise HTTPException(status_code=404, detail="Group not found")
            group = g_res.data[0]

            m_res = sb.table("group_members").select("*,profiles(display_name)").eq("group_id", group_id).execute()
            members = []
            for m in (m_res.data or []):
                members.append(GroupMemberOut(
                    id=m["id"],
                    profile_id=m["profile_id"],
                    display_name=m.get("profiles", {}).get("display_name"),
                    status=m["status"],
                ))
            return GroupOut(
                id=group["id"],
                apartment_id=group["apartment_id"],
                created_by=group.get("created_by"),
                status=group["status"],
                members=members,
                created_at=str(group.get("created_at", "")),
            )
        except HTTPException:
            raise
        except Exception as e:
            logger.warning(f"[fairsplit] Supabase error: {e}")

    # Synthetic fallback
    for g in SYNTHETIC_GROUPS:
        if g["id"] == group_id:
            members = [GroupMemberOut(**m) for m in g["members"]]
            return GroupOut(
                id=g["id"],
                apartment_id=g["apartment_id"],
                created_by=g.get("created_by"),
                status=g["status"],
                members=members,
                created_at=g.get("created_at"),
            )
    raise HTTPException(status_code=404, detail="Group not found")


@fairsplit_router.post("/groups/{group_id}/invite", response_model=InviteResponse)
async def create_invitation(group_id: str, req: InviteRequest):
    # Check for duplicate invitation (idempotency protection)
    dup_key = f"{group_id}:{req.invitee_profile_id}"
    if dup_key in _invitations:
        existing = _invitations[dup_key]
        return InviteResponse(
            invitation_id=existing["id"],
            group_id=group_id,
            invitee_id=req.invitee_profile_id,
            token=existing["token"],
            message="Invitation already exists",
        )

    if _using_supabase():
        try:
            sb = _get_supabase()
            g_res = sb.table("roommate_groups").select("id").eq("id", group_id).execute()
            if not g_res.data:
                raise HTTPException(status_code=404, detail="Group not found")

            # Check for existing membership
            existing = sb.table("group_members")\
                .select("id")\
                .eq("group_id", group_id)\
                .eq("profile_id", req.invitee_profile_id)\
                .execute()
            if existing.data:
                raise HTTPException(status_code=409, detail="Profile already invited or member")

            res = sb.table("group_members").insert({
                "group_id": group_id,
                "profile_id": req.invitee_profile_id,
                "status": "pending",
            }).execute()
            member_id = res.data[0]["id"]
        except HTTPException:
            raise
        except Exception as e:
            logger.warning(f"[fairsplit] Supabase error: {e}")
            member_id = secrets.token_hex(8)
    else:
        member_id = secrets.token_hex(8)

    import uuid
    inv_id = str(uuid.uuid4())
    token = secrets.token_urlsafe(32)
    _invitations[dup_key] = {"id": inv_id, "token": token, "member_id": member_id}

    return InviteResponse(
        invitation_id=inv_id,
        group_id=group_id,
        invitee_id=req.invitee_profile_id,
        token=token,
        message="Invitation created successfully",
    )


@fairsplit_router.post("/invitations/{invitation_id}/accept",
                       response_model=AcceptInvitationResponse)
async def accept_invitation(invitation_id: str):
    # Find invitation
    inv = None
    for key, val in _invitations.items():
        if val["id"] == invitation_id:
            inv = val
            group_id, invitee_id = key.split(":", 1)
            break

    if inv is None:
        raise HTTPException(status_code=404, detail="Invitation not found")

    if _using_supabase():
        try:
            sb = _get_supabase()
            sb.table("group_members")\
                .update({"status": "accepted"})\
                .eq("group_id", group_id)\
                .eq("profile_id", invitee_id)\
                .execute()
        except Exception as e:
            logger.warning(f"[fairsplit] Supabase error: {e}")

    return AcceptInvitationResponse(
        group_id=group_id,
        member_id=inv["member_id"],
        status="accepted",
        message="Invitation accepted",
    )


# ── Housing Offers ─────────────────────────────────────────────────────────────
#
# Authorization (demo mode):
#   Creating an offer requires the X-Demo-Profile-Id header to contain a
#   profile ID from FAIRSPLIT_DEMO_OWNER_IDS (env, comma-separated) or the
#   built-in demo set.  This prevents anonymous writes via the service key.
#   In a production deployment, replace this guard with real session auth.
#
_DEFAULT_DEMO_OWNERS = {
    "profile-alex-001",
    "profile-jordan-001",
    "profile-sam-001",
    "profile-taylor-001",
    "profile-morgan-001",
}

def _allowed_owners() -> set[str]:
    env = os.getenv("FAIRSPLIT_DEMO_OWNER_IDS", "")
    if env.strip():
        return {s.strip() for s in env.split(",") if s.strip()}
    return _DEFAULT_DEMO_OWNERS


SYNTHETIC_OFFERS: list[dict] = [
    {
        "id": "offer-demo-001",
        "owner_profile_id": "profile-alex-001",
        "title": "Private room in Bushwick share",
        "city": "New York",
        "neighborhood": "Bushwick",
        "rooms_available": 1,
        "rent_per_room_cents": 120000,
        "available_from": "2026-11-01",
        "smoking_policy": "non_smoker",
        "description": "Furnished room in a 4BR apartment, 2 mins from the J train.",
        "status": "open",
        "is_synthetic": True,
        "created_at": "2026-10-01T00:00:00Z",
    },
]

# In-memory offer store for demo without Supabase
_demo_offers: list[dict] = []


def _offer_out(row: dict) -> HousingOfferOut:
    return HousingOfferOut(
        id=str(row["id"]),
        owner_profile_id=row["owner_profile_id"],
        title=row["title"],
        city=row.get("city", "New York"),
        neighborhood=row["neighborhood"],
        rooms_available=row["rooms_available"],
        rent_per_room_cents=row["rent_per_room_cents"],
        available_from=str(row["available_from"]),
        smoking_policy=row.get("smoking_policy", "no_preference"),
        description=row.get("description"),
        status=row.get("status", "open"),
        is_synthetic=row.get("is_synthetic", False),
        created_at=str(row.get("created_at", "")),
    )


@fairsplit_router.post("/offers", response_model=HousingOfferOut, status_code=201)
async def create_housing_offer(
    req: HousingOfferCreate,
    x_demo_profile_id: Optional[str] = Header(None, alias="X-Demo-Profile-Id"),
):
    """Create a housing offer (room-provider proposal).

    DEMO MODE: The X-Demo-Profile-Id header must match a known demo profile and
    must equal req.owner_profile_id.  This prevents arbitrary profile
    impersonation via the service key.
    """
    allowed = _allowed_owners()

    # The header is required and must match the body's owner_profile_id
    if not x_demo_profile_id:
        raise HTTPException(
            status_code=403,
            detail=(
                "X-Demo-Profile-Id header required. "
                "FairSplit offers use demo-mode auth — "
                "pass a known demo profile ID in the header."
            ),
        )
    if x_demo_profile_id not in allowed:
        raise HTTPException(
            status_code=403,
            detail=f"Profile {x_demo_profile_id!r} is not in the demo-owner allow-list.",
        )
    if x_demo_profile_id != req.owner_profile_id:
        raise HTTPException(
            status_code=403,
            detail="X-Demo-Profile-Id must match owner_profile_id in the request body.",
        )

    if _using_supabase():
        try:
            sb = _get_supabase()
            row = sb.table("housing_offers").insert({
                "owner_profile_id": req.owner_profile_id,
                "title": req.title,
                "city": req.city,
                "neighborhood": req.neighborhood,
                "rooms_available": req.rooms_available,
                "rent_per_room_cents": req.rent_per_room_cents,
                "available_from": req.available_from,
                "smoking_policy": req.smoking_policy,
                "description": req.description,
                "status": "open",
                "is_synthetic": False,
            }).execute()
            return _offer_out(row.data[0])
        except HTTPException:
            raise
        except Exception as e:
            logger.warning(f"[fairsplit] Supabase offer insert error: {e}")
            # Fall through to in-memory store

    # In-memory fallback (demo without Supabase)
    import uuid
    record = {
        "id": str(uuid.uuid4()),
        "owner_profile_id": req.owner_profile_id,
        "title": req.title,
        "city": req.city,
        "neighborhood": req.neighborhood,
        "rooms_available": req.rooms_available,
        "rent_per_room_cents": req.rent_per_room_cents,
        "available_from": req.available_from,
        "smoking_policy": req.smoking_policy,
        "description": req.description,
        "status": "open",
        "is_synthetic": False,
        "created_at": datetime.utcnow().isoformat() + "Z",
    }
    _demo_offers.append(record)
    logger.info(f"[fairsplit] Offer created in-memory (Supabase unavailable): {record['id']}")
    return _offer_out(record)


@fairsplit_router.get("/offers", response_model=list[HousingOfferOut])
async def list_housing_offers(
    neighborhood: Optional[str] = None,
    max_rent_per_room_cents: Optional[int] = None,
    status: str = "open",
    limit: int = 20,
):
    """List open room offers, optionally filtered by neighborhood and budget."""
    if _using_supabase():
        try:
            sb = _get_supabase()
            q = sb.table("housing_offers").select("*").eq("status", status)
            if neighborhood:
                q = q.or_(f"neighborhood.ilike.%{neighborhood}%,city.ilike.%{neighborhood}%")
            if max_rent_per_room_cents:
                q = q.lte("rent_per_room_cents", max_rent_per_room_cents)
            res = q.limit(limit).execute()
            rows = res.data or []
            # Merge in-memory demo offers not yet in Supabase
            return [_offer_out(r) for r in rows]
        except Exception as e:
            logger.warning(f"[fairsplit] Supabase offer list error: {e}")

    # In-memory fallback
    all_offers = list(SYNTHETIC_OFFERS) + _demo_offers
    results = []
    for o in all_offers:
        if o.get("status", "open") != status:
            continue
        if neighborhood and neighborhood.lower() not in (
            o.get("neighborhood", "") + " " + o.get("city", "")
        ).lower():
            continue
        if max_rent_per_room_cents and o["rent_per_room_cents"] > max_rent_per_room_cents:
            continue
        results.append(_offer_out(o))
        if len(results) >= limit:
            break
    return results


@fairsplit_router.get("/profiles/{profile_id}/groups",
                      response_model=ProfileGroupsResponse)
async def get_profile_groups(profile_id: str):
    if _using_supabase():
        try:
            sb = _get_supabase()
            m_res = sb.table("group_members")\
                .select("group_id")\
                .eq("profile_id", profile_id)\
                .execute()
            group_ids = [r["group_id"] for r in (m_res.data or [])]
            groups = []
            for gid in group_ids:
                try:
                    g = await get_group(gid)
                    groups.append(g)
                except HTTPException:
                    pass
            return ProfileGroupsResponse(profile_id=profile_id, groups=groups)
        except Exception as e:
            logger.warning(f"[fairsplit] Supabase error: {e}")

    # Synthetic fallback
    groups = []
    for g in SYNTHETIC_GROUPS:
        for m in g["members"]:
            if m["profile_id"] == profile_id:
                members = [GroupMemberOut(**mem) for mem in g["members"]]
                groups.append(GroupOut(
                    id=g["id"],
                    apartment_id=g["apartment_id"],
                    created_by=g.get("created_by"),
                    status=g["status"],
                    members=members,
                    created_at=g.get("created_at"),
                ))
                break
    return ProfileGroupsResponse(profile_id=profile_id, groups=groups)
