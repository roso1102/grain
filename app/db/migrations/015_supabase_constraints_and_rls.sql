-- Migration 015: Add uniqueness constraints and missing RLS policies
-- Note: users_select_own, users_update_own are already in migration 013.

-- 1) Uniqueness constraints and indexes
CREATE UNIQUE INDEX IF NOT EXISTS uq_users_supabase_user_id_idx ON users (supabase_user_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_users_telegram_chat_id_idx ON users (telegram_chat_id);

CREATE INDEX IF NOT EXISTS idx_users_supabase_user_id ON users(supabase_user_id);

-- 2) Missing RLS policies (INSERT and DELETE for users — 013 only has SELECT/UPDATE)
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_catalog.pg_policy p
    JOIN pg_catalog.pg_class c ON p.polrelid = c.oid
    WHERE p.polname = 'users_insert_self' AND c.relname = 'users'
  ) THEN
    EXECUTE 'CREATE POLICY users_insert_self ON users
      FOR INSERT
      WITH CHECK (auth.uid() = supabase_user_id)';
  END IF;
END
$$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_catalog.pg_policy p
    JOIN pg_catalog.pg_class c ON p.polrelid = c.oid
    WHERE p.polname = 'users_delete_own' AND c.relname = 'users'
  ) THEN
    EXECUTE 'CREATE POLICY users_delete_own ON users
      FOR DELETE
      USING (auth.uid() = supabase_user_id)';
  END IF;
END
$$;

NOTIFY pgrst, 'reload schema';
