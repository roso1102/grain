-- Enable UUID generation if needed (gen_random_uuid() is built-in under Postgres 13+)
-- Create topics table
CREATE TABLE IF NOT EXISTS topics (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT UNIQUE NOT NULL,
    parent_id UUID REFERENCES topics(id) ON DELETE SET NULL,
    description TEXT,
    notion_page_id TEXT
);

-- Create notes table
CREATE TABLE IF NOT EXISTS notes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    raw_text TEXT NOT NULL,
    summary TEXT,
    source_url TEXT,
    source_type TEXT,
    personal_insight TEXT,
    topic_id UUID REFERENCES topics(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ DEFAULT timezone('utc'::text, now()) NOT NULL
);
