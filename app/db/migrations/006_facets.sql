-- Add JSONB column for structured facets (location, subject, category, etc.)
-- Enables grouping/browsing notes by facet values regardless of topic name

ALTER TABLE notes ADD COLUMN IF NOT EXISTS facets JSONB DEFAULT '{}'::jsonb;
