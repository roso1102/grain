-- Enable the pgvector extension to work with embeddings
CREATE EXTENSION IF NOT EXISTS vector;

-- Add embedding columns to topics and notes tables
-- BAAI/bge-small-en-v1.5 produces vectors of size 384
ALTER TABLE topics ADD COLUMN IF NOT EXISTS embedding vector(384);
ALTER TABLE notes ADD COLUMN IF NOT EXISTS embedding vector(384);
