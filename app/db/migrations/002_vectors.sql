-- Enable the pgvector extension to work with embeddings
CREATE EXTENSION IF NOT EXISTS vector;

-- Add embedding columns to topics and notes tables
-- Gemini text-embedding-004 produces vectors; we truncate to 384 dimensions
ALTER TABLE topics ADD COLUMN IF NOT EXISTS embedding vector(384);
ALTER TABLE notes ADD COLUMN IF NOT EXISTS embedding vector(384);
