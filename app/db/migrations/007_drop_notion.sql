-- Migration 007: Remove Notion columns
-- Notion is replaced by Obsidian for the presentation layer.

ALTER TABLE notes DROP COLUMN IF EXISTS notion_page_id;
ALTER TABLE notes DROP COLUMN IF EXISTS notion_block_id;
ALTER TABLE notes DROP COLUMN IF EXISTS notion_last_edited;

ALTER TABLE topics DROP COLUMN IF EXISTS notion_page_id;
