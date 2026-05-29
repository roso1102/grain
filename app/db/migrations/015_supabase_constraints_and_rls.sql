-- Migration 015: Add uniqueness constraints, indexes, and RLS policies

-- 1) Uniqueness constraints and indexes
ALTER TABLE IF EXISTS users
  ADD CONSTRAINT IF NOT EXISTS uq_users_supabase_user_id UNIQUE (supabase_user_id);

ALTER TABLE IF EXISTS users
  ADD CONSTRAINT IF NOT EXISTS uq_users_telegram_chat_id UNIQUE (telegram_chat_id);

CREATE INDEX IF NOT EXISTS idx_users_supabase_user_id ON users(supabase_user_id);

-- 2) Row Level Security: restrict access so that a signed-in Supabase user can only select/update their row.
-- NOTE: Enabling RLS will block queries that do not present a valid JWT. Apply carefully and test.
ALTER TABLE IF EXISTS users ENABLE ROW LEVEL SECURITY;

CREATE POLICY IF NOT EXISTS users_select_own ON users
  FOR SELECT
  USING (supabase_user_id::text = auth.uid());

CREATE POLICY IF NOT EXISTS users_update_own ON users
  FOR UPDATE
  USING (supabase_user_id::text = auth.uid());

CREATE POLICY IF NOT EXISTS users_insert_self ON users
  FOR INSERT
  WITH CHECK (supabase_user_id::text = auth.uid());

-- Important: server-side operations (migrations, backfill, service workers) should use the
-- Supabase service_role key which bypasses RLS. Client requests will be subject to these policies.

NOTIFY pgrst, 'reload schema';
