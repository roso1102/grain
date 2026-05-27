-- Migration 012: Multi-tenant support
-- Adds user_id columns, drops global uniqueness, adds per-user uniqueness,
-- updates match_notes RPC with p_user_id parameter.

-- ── 1. Add user_id to all data tables ──
ALTER TABLE notes ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES users(id) ON DELETE CASCADE;
ALTER TABLE topics ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES users(id) ON DELETE CASCADE;
ALTER TABLE entities ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES users(id) ON DELETE CASCADE;
ALTER TABLE note_entities ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES users(id) ON DELETE CASCADE;
ALTER TABLE relations ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES users(id) ON DELETE CASCADE;
ALTER TABLE enrichment_log ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES users(id) ON DELETE CASCADE;
ALTER TABLE agent_state ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES users(id) ON DELETE CASCADE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS supabase_user_id UUID;

-- ── 2. Drop global UNIQUE on topics.name and entities.name ──
ALTER TABLE topics DROP CONSTRAINT IF EXISTS topics_name_key;
ALTER TABLE entities DROP CONSTRAINT IF EXISTS entities_name_key;

-- ── 3. Per-user unique indexes ──
CREATE UNIQUE INDEX IF NOT EXISTS idx_topics_user_id_name ON topics(user_id, name) WHERE user_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_entities_user_id_name ON entities(user_id, name) WHERE user_id IS NOT NULL;
-- Keep global uniqueness for legacy rows without user_id
CREATE UNIQUE INDEX IF NOT EXISTS idx_topics_name_null ON topics(name) WHERE user_id IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_entities_name_null ON entities(name) WHERE user_id IS NULL;

-- ── 4. Backfill existing rows ──
DO $$
DECLARE
    first_user_id UUID;
BEGIN
    SELECT id INTO first_user_id FROM users ORDER BY created_at ASC LIMIT 1;
    IF first_user_id IS NOT NULL THEN
        UPDATE notes SET user_id = first_user_id WHERE user_id IS NULL;
        UPDATE topics SET user_id = first_user_id WHERE user_id IS NULL;
        UPDATE entities SET user_id = first_user_id WHERE user_id IS NULL;
        UPDATE note_entities SET user_id = first_user_id WHERE user_id IS NULL;
        UPDATE relations SET user_id = first_user_id WHERE user_id IS NULL;
        UPDATE enrichment_log SET user_id = first_user_id WHERE user_id IS NULL;
        UPDATE agent_state SET user_id = first_user_id WHERE user_id IS NULL;
    END IF;
END $$;

-- ── 5. Performance indexes ──
CREATE INDEX IF NOT EXISTS idx_notes_user_id ON notes(user_id);
CREATE INDEX IF NOT EXISTS idx_topics_user_id ON topics(user_id);
CREATE INDEX IF NOT EXISTS idx_entities_user_id ON entities(user_id);
CREATE INDEX IF NOT EXISTS idx_note_entities_user_id ON note_entities(user_id);
CREATE INDEX IF NOT EXISTS idx_relations_user_id ON relations(user_id);
CREATE INDEX IF NOT EXISTS idx_enrichment_log_user_id ON enrichment_log(user_id);

-- ── 6. Recreate match_notes with p_user_id ──
DROP FUNCTION IF EXISTS match_notes CASCADE;

CREATE OR REPLACE FUNCTION match_notes (
  query_embedding vector(3072),
  match_threshold float,
  match_count int,
  p_user_id UUID DEFAULT NULL
)
RETURNS TABLE (
  id UUID,
  raw_text TEXT,
  summary TEXT,
  source_url TEXT,
  source_type TEXT,
  personal_insight TEXT,
  topic_id UUID,
  topic_name TEXT,
  similarity float
)
LANGUAGE plpgsql
AS $$
BEGIN
  RETURN QUERY
  SELECT
    notes.id,
    notes.raw_text,
    notes.summary,
    notes.source_url,
    notes.source_type,
    notes.personal_insight,
    notes.topic_id,
    topics.name AS topic_name,
    (1 - (notes.embedding <=> query_embedding))::float AS similarity
  FROM notes
  LEFT JOIN topics ON notes.topic_id = topics.id
  WHERE notes.embedding IS NOT NULL
    AND 1 - (notes.embedding <=> query_embedding) > match_threshold
    AND (p_user_id IS NULL OR notes.user_id = p_user_id)
  ORDER BY notes.embedding <=> query_embedding
  LIMIT match_count;
END;
$$;

NOTIFY pgrst, 'reload schema';
