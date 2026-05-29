-- Migration 015: Add uniqueness constraints, indexes, and RLS policies

-- 1) Uniqueness constraints and indexes
-- Use unique indexes which are supported with IF NOT EXISTS in Postgres
CREATE UNIQUE INDEX IF NOT EXISTS uq_users_supabase_user_id_idx ON users (supabase_user_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_users_telegram_chat_id_idx ON users (telegram_chat_id);

-- Also keep a simple index for lookups by supabase_user_id (non-unique index is optional)
CREATE INDEX IF NOT EXISTS idx_users_supabase_user_id ON users(supabase_user_id);

-- 2) Row Level Security: restrict access so that a signed-in Supabase user can only select/update their row.
-- NOTE: Enabling RLS will block queries that do not present a valid JWT. Apply carefully and test.
ALTER TABLE IF EXISTS users ENABLE ROW LEVEL SECURITY;

-- Create policies only if they don't already exist (Postgres doesn't support IF NOT EXISTS on CREATE POLICY)
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_catalog.pg_policy p
    JOIN pg_catalog.pg_class c ON p.polrelid = c.oid
    WHERE p.polname = 'users_select_own' AND c.relname = 'users'
  ) THEN
    EXECUTE 'CREATE POLICY users_select_own ON users
      FOR SELECT
      USING (supabase_user_id::text = auth.uid());';
  END IF;
END
$$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_catalog.pg_policy p
    JOIN pg_catalog.pg_class c ON p.polrelid = c.oid
    WHERE p.polname = 'users_update_own' AND c.relname = 'users'
  ) THEN
    EXECUTE 'CREATE POLICY users_update_own ON users
      FOR UPDATE
      USING (supabase_user_id::text = auth.uid());';
  END IF;
END
$$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_catalog.pg_policy p
    JOIN pg_catalog.pg_class c ON p.polrelid = c.oid
    WHERE p.polname = 'users_insert_self' AND c.relname = 'users'
  ) THEN
    EXECUTE 'CREATE POLICY users_insert_self ON users
      FOR INSERT
      WITH CHECK (supabase_user_id::text = auth.uid());';
  END IF;
END
$$;

-- Important: server-side operations (migrations, backfill, service workers) should use the
-- Supabase service_role key which bypasses RLS. Client requests will be subject to these policies.

NOTIFY pgrst, 'reload schema';
