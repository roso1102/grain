-- Migration 013: Row Level Security
-- Enables RLS on all data tables and creates per-user policies.
-- Backend uses service_role key (bypasses RLS). Policies apply to dashboard users.

-- ── Enable RLS ──────────────────────────────────────────────────────────
ALTER TABLE notes ENABLE ROW LEVEL SECURITY;
ALTER TABLE topics ENABLE ROW LEVEL SECURITY;
ALTER TABLE entities ENABLE ROW LEVEL SECURITY;
ALTER TABLE note_entities ENABLE ROW LEVEL SECURITY;
ALTER TABLE relations ENABLE ROW LEVEL SECURITY;
ALTER TABLE enrichment_log ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent_state ENABLE ROW LEVEL SECURITY;
ALTER TABLE users ENABLE ROW LEVEL SECURITY;

-- ── Users table policies ────────────────────────────────────────────────
-- Users can read their own row, update their own row
CREATE POLICY "users_select_own" ON users
    FOR SELECT USING (auth.uid() = supabase_user_id);

CREATE POLICY "users_update_own" ON users
    FOR UPDATE USING (auth.uid() = supabase_user_id);

-- ── Notes table policies ────────────────────────────────────────────────
CREATE POLICY "notes_select_own" ON notes
    FOR SELECT USING (auth.uid() = user_id);

CREATE POLICY "notes_insert_own" ON notes
    FOR INSERT WITH CHECK (auth.uid() = user_id);

CREATE POLICY "notes_update_own" ON notes
    FOR UPDATE USING (auth.uid() = user_id);

CREATE POLICY "notes_delete_own" ON notes
    FOR DELETE USING (auth.uid() = user_id);

-- ── Topics table policies ───────────────────────────────────────────────
CREATE POLICY "topics_select_own" ON topics
    FOR SELECT USING (auth.uid() = user_id);

CREATE POLICY "topics_insert_own" ON topics
    FOR INSERT WITH CHECK (auth.uid() = user_id);

CREATE POLICY "topics_update_own" ON topics
    FOR UPDATE USING (auth.uid() = user_id);

CREATE POLICY "topics_delete_own" ON topics
    FOR DELETE USING (auth.uid() = user_id);

-- ── Entities table policies ─────────────────────────────────────────────
CREATE POLICY "entities_select_own" ON entities
    FOR SELECT USING (auth.uid() = user_id);

CREATE POLICY "entities_insert_own" ON entities
    FOR INSERT WITH CHECK (auth.uid() = user_id);

CREATE POLICY "entities_update_own" ON entities
    FOR UPDATE USING (auth.uid() = user_id);

CREATE POLICY "entities_delete_own" ON entities
    FOR DELETE USING (auth.uid() = user_id);

-- ── note_entities table policies ────────────────────────────────────────
CREATE POLICY "note_entities_select_own" ON note_entities
    FOR SELECT USING (auth.uid() = user_id);

CREATE POLICY "note_entities_insert_own" ON note_entities
    FOR INSERT WITH CHECK (auth.uid() = user_id);

CREATE POLICY "note_entities_delete_own" ON note_entities
    FOR DELETE USING (auth.uid() = user_id);

-- ── Relations table policies ────────────────────────────────────────────
CREATE POLICY "relations_select_own" ON relations
    FOR SELECT USING (auth.uid() = user_id);

CREATE POLICY "relations_insert_own" ON relations
    FOR INSERT WITH CHECK (auth.uid() = user_id);

CREATE POLICY "relations_delete_own" ON relations
    FOR DELETE USING (auth.uid() = user_id);

-- ── enrichment_log table policies ───────────────────────────────────────
CREATE POLICY "enrichment_log_select_own" ON enrichment_log
    FOR SELECT USING (auth.uid() = user_id);

CREATE POLICY "enrichment_log_insert_own" ON enrichment_log
    FOR INSERT WITH CHECK (auth.uid() = user_id);

-- ── Drop backward-compat NULL indexes ───────────────────────────────────
-- These indexes from migration 012 allowed NULL user_id for legacy rows.
-- With RLS + service_role backend, legacy rows now have assigned user_id.
DROP INDEX IF EXISTS idx_topics_name_null;
DROP INDEX IF EXISTS idx_entities_name_null;

-- ── Reload schema for PostgREST ─────────────────────────────────────────
NOTIFY pgrst, 'reload schema';
