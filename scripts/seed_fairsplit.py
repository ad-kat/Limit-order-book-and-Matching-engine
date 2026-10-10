#!/usr/bin/env python3
"""
seed_fairsplit.py — Idempotent seed script for FairSplit demo data.

Usage:
    python3 scripts/seed_fairsplit.py

Requires SUPABASE_URL + SUPABASE_SERVICE_KEY env vars.
Falls back to printing SQL if not configured.

Fixed random seed: 42
"""
from __future__ import annotations

import os
import random
import sys
from datetime import date, timedelta

# Fixed seed for reproducibility
random.seed(42)

# ── Fixed UUIDs for idempotency ───────────────────────────────────────────────

# Demo scenario: Brooklyn 3BR at $3,660/mo
DEMO_APT_ID = "aaaa0001-0000-0000-0000-000000000001"

APT_IDS = [DEMO_APT_ID] + [f"aaaa{i:04d}-0000-0000-0000-000000000001" for i in range(2, 16)]

PROFILE_IDS = [f"bbbb{i:04d}-0000-0000-0000-000000000002" for i in range(1, 51)]

# Demo trio profiles (budget ~$1,300 each, Nov 2026, non-smoker)
DEMO_PROFILE_IDS = PROFILE_IDS[:3]

GROUP_IDS = [f"cccc{i:04d}-0000-0000-0000-000000000003" for i in range(1, 8)]

# ── Apartment data ────────────────────────────────────────────────────────────

NEIGHBORHOODS = [
    ("Park Slope", "Brooklyn"),
    ("Williamsburg", "Brooklyn"),
    ("Bushwick", "Brooklyn"),
    ("Crown Heights", "Brooklyn"),
    ("Greenpoint", "Brooklyn"),
    ("Murray Hill", "Manhattan"),
    ("Upper East Side", "Manhattan"),
    ("Harlem", "Manhattan"),
    ("Hell's Kitchen", "Manhattan"),
    ("Astoria", "Queens"),
    ("Long Island City", "Queens"),
    ("Jackson Heights", "Queens"),
]

APT_TEMPLATES = [
    # Demo 3BR Brooklyn $3,660 (ID: DEMO_APT_ID)
    {
        "id": DEMO_APT_ID,
        "title": "Sunny 3BR in Park Slope",
        "neighborhood": "Park Slope",
        "city": "New York",
        "monthly_rent": 366000,  # $3,660 → $1,220/person
        "bedrooms": 3,
        "available_from": "2026-11-01",
        "description": "Bright 3-bedroom apartment in Park Slope near Prospect Park. "
                        "Renovated kitchen, hardwood floors, in-unit laundry.",
        "is_synthetic": True,
    },
]


def gen_apartments():
    """Generate 15 apartments (including the required demo one)."""
    apts = [APT_TEMPLATES[0]]

    configs = [
        ("Cozy 2BR in Williamsburg",      "Williamsburg",    "Brooklyn",   340000, 2, "2026-11-15"),
        ("Modern 1BR in Murray Hill",      "Murray Hill",     "Manhattan",  290000, 1, "2026-10-15"),
        ("Spacious 3BR in Astoria",        "Astoria",         "Queens",     320000, 3, "2026-11-01"),
        ("4BR Townhouse Crown Heights",    "Crown Heights",   "Brooklyn",   480000, 4, "2026-12-01"),
        ("Bright 2BR Greenpoint",          "Greenpoint",      "Brooklyn",   350000, 2, "2026-11-01"),
        ("Charming 3BR Upper East Side",   "Upper East Side", "Manhattan",  520000, 3, "2026-11-15"),
        ("Hip 2BR Bushwick",               "Bushwick",        "Brooklyn",   280000, 2, "2026-10-01"),
        ("Airy 1BR Long Island City",      "Long Island City","Queens",     240000, 1, "2026-10-15"),
        ("Roomy 4BR Harlem",               "Harlem",          "Manhattan",  460000, 4, "2026-12-01"),
        ("Stylish 2BR Hell's Kitchen",     "Hell's Kitchen",  "Manhattan",  420000, 2, "2026-11-01"),
        ("Quiet 3BR Jackson Heights",      "Jackson Heights", "Queens",     300000, 3, "2026-11-15"),
        ("Renovated 2BR Park Slope",       "Park Slope",      "Brooklyn",   380000, 2, "2026-11-01"),
        ("Sun-drenched 1BR Astoria",       "Astoria",         "Queens",     210000, 1, "2026-10-01"),
        ("Classic 3BR Williamsburg",       "Williamsburg",    "Brooklyn",   450000, 3, "2026-12-01"),
    ]

    for i, (title, nhd, city, rent, beds, avail) in enumerate(configs):
        apts.append({
            "id": APT_IDS[i + 1],
            "title": title,
            "neighborhood": nhd,
            "city": city,
            "monthly_rent": rent,
            "bedrooms": beds,
            "available_from": avail,
            "description": f"A great {beds}-bedroom apartment in {nhd}.",
            "is_synthetic": True,
        })

    return apts


# ── Profile + preferences data ────────────────────────────────────────────────

NAMES = [
    "Alex Chen", "Jordan Lee", "Sam Rivera", "Taylor Kim", "Morgan Patel",
    "Casey Zhou", "Riley Nguyen", "Drew Okafor", "Quinn Hassan", "Avery Singh",
    "Blake Torres", "Skyler Amara", "Rowan Diaz", "Finley Kobayashi", "Harper Osei",
    "Sage Williams", "Logan Andersen", "River Santos", "Dakota Müller", "Emery Kovacs",
    "Oakley Ferraro", "Reese Abebe", "Shiloh Ito", "Elliot Vasquez", "Zephyr Nkosi",
    "Charlie Park", "Phoenix Reyes", "Camden Liu", "Marlowe Bhatt", "Oakley Sato",
    "Wren Nakamura", "Juniper Adeyemi", "Sloane Bergstrom", "Remy Volkov", "Indigo Cross",
    "Blythe Yamamoto", "Crew Mensah", "Larkin Petrov", "Vesper Darko", "Cove Otieno",
    "Soleil Tanaka", "Ash Holmberg", "Paz Chowdhury", "Stellan Okafor", "Zuri Johansson",
    "Nico Gupta", "Sable Ferreira", "Orion Nakagawa", "Lyric Kamara", "Echo Lindqvist",
]

SMOKING_PREFS = ["non_smoker", "non_smoker", "non_smoker", "smoker", "no_preference"]
NHDS = [
    ["Park Slope", "Williamsburg"],
    ["Astoria", "Long Island City"],
    ["Murray Hill", "Hell's Kitchen"],
    ["Bushwick", "Crown Heights"],
    ["Greenpoint", "Williamsburg"],
]


def gen_profiles():
    profiles = []
    prefs = []

    for i, pid in enumerate(PROFILE_IDS):
        name = NAMES[i] if i < len(NAMES) else f"User {i+1}"

        # Demo trio: budget ~$1,300, Nov 2026, non-smoker
        if i < 3:
            budget = random.randint(128000, 135000)  # $1,280–$1,350
            move_in = "2026-11-0" + str(i + 1)
            smoke = "non_smoker"
            nhds = ["Park Slope", "Williamsburg", "Astoria"]
        else:
            budget = random.randint(100000, 200000)  # $1,000–$2,000
            base_date = date(2026, 10, 1) + timedelta(days=random.randint(0, 90))
            move_in = base_date.isoformat()
            smoke = random.choice(SMOKING_PREFS)
            nhds = random.choice(NHDS)

        profiles.append({
            "id": pid,
            "display_name": name,
            "is_synthetic": True,
        })

        prefs.append({
            "profile_id": pid,
            "maximum_monthly_budget": budget,
            "preferred_neighborhoods": nhds,
            "move_in_date": move_in,
            "preferred_roommate_count": random.randint(1, 3),
            "smoking_preference": smoke,
            "additional_requirements": None,
            "is_synthetic": True,
        })

    return profiles, prefs


# ── Groups ────────────────────────────────────────────────────────────────────

def gen_groups(apt_ids, profile_ids):
    groups = []
    members = []

    # Group 1: forming — demo trio on demo apartment
    groups.append({
        "id": GROUP_IDS[0],
        "apartment_id": DEMO_APT_ID,
        "created_by": DEMO_PROFILE_IDS[0],
        "status": "forming",
    })
    for j, pid in enumerate(DEMO_PROFILE_IDS):
        members.append({
            "group_id": GROUP_IDS[0],
            "profile_id": pid,
            "status": "accepted" if j == 0 else "pending",
        })

    # Group 2: complete — 4 profiles on apt index 4 (4BR)
    groups.append({
        "id": GROUP_IDS[1],
        "apartment_id": apt_ids[4],
        "created_by": profile_ids[10],
        "status": "complete",
    })
    for pid in profile_ids[10:14]:
        members.append({"group_id": GROUP_IDS[1], "profile_id": pid, "status": "accepted"})

    # Group 3: forming with pending invite
    groups.append({
        "id": GROUP_IDS[2],
        "apartment_id": apt_ids[1],
        "created_by": profile_ids[20],
        "status": "forming",
    })
    members.append({"group_id": GROUP_IDS[2], "profile_id": profile_ids[20], "status": "accepted"})
    members.append({"group_id": GROUP_IDS[2], "profile_id": profile_ids[21], "status": "pending"})

    # Group 4: cancelled
    groups.append({
        "id": GROUP_IDS[3],
        "apartment_id": apt_ids[2],
        "created_by": profile_ids[30],
        "status": "cancelled",
    })
    members.append({"group_id": GROUP_IDS[3], "profile_id": profile_ids[30], "status": "declined"})

    return groups, members


# ── SQL output fallback ────────────────────────────────────────────────────────

def print_sql(apts, profiles, prefs, groups, members):
    print("-- FairSplit seed data SQL")
    print("-- Run against your Supabase project SQL editor\n")

    print("-- Delete existing synthetic data (idempotent)")
    print("DELETE FROM agent_activity WHERE true;")
    print("DELETE FROM group_members WHERE true;")
    print("DELETE FROM roommate_groups WHERE true;")
    print("DELETE FROM housing_preferences WHERE true;")
    print("DELETE FROM profiles WHERE is_synthetic = true;")
    print("DELETE FROM apartments WHERE is_synthetic = true;\n")

    print("-- Apartments")
    for a in apts:
        desc = a["description"].replace("'", "''") if a["description"] else ""
        print(f"INSERT INTO apartments (id, title, neighborhood, city, monthly_rent, bedrooms, "
              f"available_from, description, is_synthetic) VALUES "
              f"('{a['id']}', '{a['title']}', '{a['neighborhood']}', '{a['city']}', "
              f"{a['monthly_rent']}, {a['bedrooms']}, '{a['available_from']}', "
              f"'{desc}', true);")

    print("\n-- Profiles")
    for p in profiles:
        print(f"INSERT INTO profiles (id, display_name, is_synthetic) VALUES "
              f"('{p['id']}', '{p['display_name']}', true);")

    print("\n-- Housing Preferences")
    for p in prefs:
        nhds = "{" + ",".join(f'"{n}"' for n in p["preferred_neighborhoods"]) + "}"
        print(f"INSERT INTO housing_preferences (profile_id, maximum_monthly_budget, "
              f"preferred_neighborhoods, move_in_date, preferred_roommate_count, "
              f"smoking_preference) VALUES "
              f"('{p['profile_id']}', {p['maximum_monthly_budget']}, '{nhds}', "
              f"'{p['move_in_date']}', {p['preferred_roommate_count']}, "
              f"'{p['smoking_preference']}');")

    print("\n-- Roommate Groups")
    for g in groups:
        cb = f"'{g['created_by']}'" if g.get("created_by") else "NULL"
        print(f"INSERT INTO roommate_groups (id, apartment_id, created_by, status) VALUES "
              f"('{g['id']}', '{g['apartment_id']}', {cb}, '{g['status']}');")

    print("\n-- Group Members")
    for m in members:
        print(f"INSERT INTO group_members (group_id, profile_id, status) VALUES "
              f"('{m['group_id']}', '{m['profile_id']}', '{m['status']}');")


# ── Supabase insert ────────────────────────────────────────────────────────────

def seed_supabase(apts, profiles, prefs, groups, members):
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_KEY")
    if not url or not key:
        print("[seed] SUPABASE_URL or SUPABASE_SERVICE_KEY not set; printing SQL instead.")
        print_sql(apts, profiles, prefs, groups, members)
        return

    try:
        from supabase import create_client
    except ImportError:
        print("[seed] supabase-py not installed (pip install supabase); printing SQL instead.")
        print_sql(apts, profiles, prefs, groups, members)
        return

    sb = create_client(url, key)
    print("[seed] Connected to Supabase. Deleting existing synthetic data…")

    # Delete in reverse FK order
    sb.table("agent_activity").delete().neq("id", "00000000-0000-0000-0000-000000000000").execute()
    sb.table("group_members").delete().neq("id", "00000000-0000-0000-0000-000000000000").execute()
    sb.table("roommate_groups").delete().neq("id", "00000000-0000-0000-0000-000000000000").execute()
    sb.table("housing_preferences").delete().neq("id", "00000000-0000-0000-0000-000000000000").execute()
    sb.table("profiles").delete().eq("is_synthetic", True).execute()
    sb.table("apartments").delete().eq("is_synthetic", True).execute()

    print("[seed] Inserting apartments…")
    sb.table("apartments").insert(apts).execute()

    print("[seed] Inserting profiles…")
    sb.table("profiles").insert(profiles).execute()

    print("[seed] Inserting housing preferences…")
    # Remove is_synthetic field not in schema
    prefs_clean = [{k: v for k, v in p.items() if k != "is_synthetic"} for p in prefs]
    sb.table("housing_preferences").insert(prefs_clean).execute()

    print("[seed] Inserting groups…")
    sb.table("roommate_groups").insert(groups).execute()

    print("[seed] Inserting group members…")
    sb.table("group_members").insert(members).execute()

    print("[seed] Done! Seeded:")
    print(f"  {len(apts)} apartments")
    print(f"  {len(profiles)} profiles")
    print(f"  {len(prefs)} housing preferences")
    print(f"  {len(groups)} roommate groups")
    print(f"  {len(members)} group members")
    print(f"\n  Demo apartment ID: {DEMO_APT_ID}")
    print(f"  Demo apartment:    Park Slope 3BR $3,660/mo ($1,220/person)")
    print(f"  Demo profiles:     {DEMO_PROFILE_IDS[:3]}")


def main():
    apts = gen_apartments()
    profiles, prefs = gen_profiles()
    groups, members = gen_groups(APT_IDS, PROFILE_IDS)

    assert len(apts) == 15,    f"Expected 15 apartments, got {len(apts)}"
    assert len(profiles) == 50, f"Expected 50 profiles, got {len(profiles)}"

    # Verify demo scenario
    demo_apt = next(a for a in apts if a["id"] == DEMO_APT_ID)
    assert demo_apt["monthly_rent"] == 366000, "Demo rent must be $3,660"
    assert demo_apt["bedrooms"] == 3, "Demo must be 3BR"
    per_person = -(-demo_apt["monthly_rent"] // demo_apt["bedrooms"])  # ceil division
    assert per_person == 122000, f"Expected $1,220/person, got ${per_person//100}"

    for pid in DEMO_PROFILE_IDS:
        p = next(pr for pr in prefs if pr["profile_id"] == pid)
        assert p["maximum_monthly_budget"] >= per_person, \
            f"Demo profile {pid} budget too low: {p['maximum_monthly_budget']} < {per_person}"
        assert p["smoking_preference"] == "non_smoker", f"Demo profile {pid} should be non_smoker"

    print(f"[seed] Validation passed. Demo: 3BR Brooklyn $3,660 → ${per_person//100}/person")

    seed_supabase(apts, profiles, prefs, groups, members)


if __name__ == "__main__":
    main()
