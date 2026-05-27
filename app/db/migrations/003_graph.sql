-- Create entities table
CREATE TABLE IF NOT EXISTS entities (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT UNIQUE NOT NULL,
    type TEXT NOT NULL, -- 'concept' | 'project' | 'technology' | 'person'
    embedding vector(768)
);

-- Create note_entities junction table
CREATE TABLE IF NOT EXISTS note_entities (
    note_id UUID REFERENCES notes(id) ON DELETE CASCADE,
    entity_id UUID REFERENCES entities(id) ON DELETE CASCADE,
    confidence FLOAT,
    PRIMARY KEY (note_id, entity_id)
);

-- Create relations table for knowledge graph edges
CREATE TABLE IF NOT EXISTS relations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_note_id UUID REFERENCES notes(id) ON DELETE CASCADE,
    target_note_id UUID REFERENCES notes(id) ON DELETE CASCADE,
    relation_type TEXT NOT NULL, -- 'related_to' | 'extends' | 'contradicts' | 'depends_on'
    score FLOAT DEFAULT 1.0
);

-- Create enrichment_log table for tracking node merging
CREATE TABLE IF NOT EXISTS enrichment_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_note_id UUID REFERENCES notes(id) ON DELETE CASCADE,
    merged_at TIMESTAMPTZ DEFAULT timezone('utc'::text, now()) NOT NULL,
    old_summary TEXT,
    new_summary TEXT
);
