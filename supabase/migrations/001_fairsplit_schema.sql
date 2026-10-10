-- FairSplit Schema Migration
-- Hackathon: The New Agentic Economy, October 10 2026
-- Betaworks NYC, Forever 22, supported by Google DeepMind

-- Enable UUID extension (usually already enabled on Supabase)
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ── profiles ──────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS profiles (
  id            UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  display_name  TEXT        NOT NULL,
  is_synthetic  BOOLEAN     NOT NULL DEFAULT FALSE,
  created_at    TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS profiles_is_synthetic_idx ON profiles (is_synthetic);

ALTER TABLE profiles ENABLE ROW LEVEL SECURITY;

CREATE POLICY "profiles_select_all" ON profiles FOR SELECT USING (true);
CREATE POLICY "profiles_insert_own" ON profiles FOR INSERT WITH CHECK (true);
CREATE POLICY "profiles_update_own" ON profiles FOR UPDATE USING (true);

-- ── apartments ────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS apartments (
  id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  title           TEXT        NOT NULL,
  neighborhood    TEXT        NOT NULL,
  city            TEXT        NOT NULL DEFAULT 'New York',
  monthly_rent    INTEGER     NOT NULL,  -- cents
  bedrooms        INTEGER     NOT NULL CHECK (bedrooms > 0),
  available_from  DATE        NOT NULL,
  description     TEXT,
  is_synthetic    BOOLEAN     NOT NULL DEFAULT FALSE,
  created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS apartments_neighborhood_idx ON apartments (neighborhood);
CREATE INDEX IF NOT EXISTS apartments_monthly_rent_idx ON apartments (monthly_rent);
CREATE INDEX IF NOT EXISTS apartments_bedrooms_idx     ON apartments (bedrooms);
CREATE INDEX IF NOT EXISTS apartments_is_synthetic_idx ON apartments (is_synthetic);

ALTER TABLE apartments ENABLE ROW LEVEL SECURITY;

CREATE POLICY "apartments_select_all" ON apartments FOR SELECT USING (true);
CREATE POLICY "apartments_insert_all" ON apartments FOR INSERT WITH CHECK (true);

-- ── housing_preferences ───────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS housing_preferences (
  id                       UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  profile_id               UUID        NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  maximum_monthly_budget   INTEGER     NOT NULL,  -- cents
  preferred_neighborhoods  TEXT[],
  move_in_date             DATE        NOT NULL,
  preferred_roommate_count INTEGER     NOT NULL DEFAULT 2,
  smoking_preference       TEXT        NOT NULL DEFAULT 'no_preference'
                           CHECK (smoking_preference IN ('non_smoker','smoker','no_preference')),
  additional_requirements  TEXT,
  created_at               TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS housing_preferences_profile_id_idx     ON housing_preferences (profile_id);
CREATE INDEX IF NOT EXISTS housing_preferences_move_in_date_idx   ON housing_preferences (move_in_date);
CREATE INDEX IF NOT EXISTS housing_preferences_max_budget_idx     ON housing_preferences (maximum_monthly_budget);

ALTER TABLE housing_preferences ENABLE ROW LEVEL SECURITY;

CREATE POLICY "housing_preferences_select_all" ON housing_preferences FOR SELECT USING (true);
CREATE POLICY "housing_preferences_insert_own" ON housing_preferences FOR INSERT WITH CHECK (true);
CREATE POLICY "housing_preferences_update_own" ON housing_preferences FOR UPDATE USING (true);

-- ── roommate_groups ───────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS roommate_groups (
  id            UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  apartment_id  UUID        NOT NULL REFERENCES apartments(id),
  created_by    UUID        REFERENCES profiles(id),
  status        TEXT        NOT NULL DEFAULT 'forming'
                CHECK (status IN ('forming','complete','cancelled')),
  created_at    TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS roommate_groups_apartment_id_idx ON roommate_groups (apartment_id);
CREATE INDEX IF NOT EXISTS roommate_groups_created_by_idx   ON roommate_groups (created_by);
CREATE INDEX IF NOT EXISTS roommate_groups_status_idx       ON roommate_groups (status);

ALTER TABLE roommate_groups ENABLE ROW LEVEL SECURITY;

CREATE POLICY "roommate_groups_select_all" ON roommate_groups FOR SELECT USING (true);
CREATE POLICY "roommate_groups_insert_all" ON roommate_groups FOR INSERT WITH CHECK (true);
CREATE POLICY "roommate_groups_update_all" ON roommate_groups FOR UPDATE USING (true);

-- ── group_members ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS group_members (
  id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  group_id    UUID        NOT NULL REFERENCES roommate_groups(id) ON DELETE CASCADE,
  profile_id  UUID        NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  status      TEXT        NOT NULL DEFAULT 'pending'
              CHECK (status IN ('pending','accepted','declined')),
  created_at  TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(group_id, profile_id)
);

CREATE INDEX IF NOT EXISTS group_members_group_id_idx   ON group_members (group_id);
CREATE INDEX IF NOT EXISTS group_members_profile_id_idx ON group_members (profile_id);
CREATE INDEX IF NOT EXISTS group_members_status_idx     ON group_members (status);

ALTER TABLE group_members ENABLE ROW LEVEL SECURITY;

CREATE POLICY "group_members_select_all" ON group_members FOR SELECT USING (true);
CREATE POLICY "group_members_insert_all" ON group_members FOR INSERT WITH CHECK (true);
CREATE POLICY "group_members_update_all" ON group_members FOR UPDATE USING (true);

-- ── agent_activity ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS agent_activity (
  id                UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  profile_id        UUID        REFERENCES profiles(id),
  action_type       TEXT        NOT NULL,
  structured_payload JSONB,
  created_at        TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS agent_activity_profile_id_idx  ON agent_activity (profile_id);
CREATE INDEX IF NOT EXISTS agent_activity_action_type_idx ON agent_activity (action_type);
CREATE INDEX IF NOT EXISTS agent_activity_created_at_idx  ON agent_activity (created_at DESC);

ALTER TABLE agent_activity ENABLE ROW LEVEL SECURITY;

CREATE POLICY "agent_activity_select_own" ON agent_activity FOR SELECT USING (true);
CREATE POLICY "agent_activity_insert_all" ON agent_activity FOR INSERT WITH CHECK (true);
