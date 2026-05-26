-- Add Notion sync tracking columns to notes table
ALTER TABLE notes ADD COLUMN IF NOT EXISTS notion_page_id TEXT;
ALTER TABLE notes ADD COLUMN IF NOT EXISTS notion_block_id TEXT;
ALTER TABLE notes ADD COLUMN IF NOT EXISTS notion_last_edited TIMESTAMPTZ;
