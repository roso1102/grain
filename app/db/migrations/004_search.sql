-- Create match_notes function for pgvector similarity search
CREATE OR REPLACE FUNCTION match_notes (
  query_embedding vector(768),
  match_threshold float,
  match_count int
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
  WHERE notes.embedding IS NOT NULL AND 1 - (notes.embedding <=> query_embedding) > match_threshold
  ORDER BY notes.embedding <=> query_embedding
  LIMIT match_count;
END;
$$;
