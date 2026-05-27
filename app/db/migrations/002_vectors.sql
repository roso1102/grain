-- Enable the pgvector extension to work with embeddings
CREATE EXTENSION IF NOT EXISTS vector;

-- Add embedding columns to topics and notes tables
-- Gemini gemini-embedding-001 produces 3072-dimensional vectors
ALTER TABLE topics ADD COLUMN IF NOT EXISTS embedding vector(3072);
ALTER TABLE notes ADD COLUMN IF NOT EXISTS embedding vector(3072);
