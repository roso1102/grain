-- Enable the pgvector extension to work with embeddings
CREATE EXTENSION IF NOT EXISTS vector;

-- Add embedding columns to topics and notes tables
-- Gemini text-embedding-004 produces 768-dimensional vectors
ALTER TABLE topics ADD COLUMN IF NOT EXISTS embedding vector(768);
ALTER TABLE notes ADD COLUMN IF NOT EXISTS embedding vector(768);
