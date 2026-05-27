-- Migration 007: Remove Notion columns
-- Notion removed. Replaced by custom web dashboard. (Updated 2026-05-27)

ALTER TABLE notes DROP COLUMN IF EXISTS notion_page_id;
ALTER TABLE notes DROP COLUMN IF EXISTS notion_block_id;
ALTER TABLE notes DROP COLUMN IF EXISTS notion_last_edited;

ALTER TABLE topics DROP COLUMN IF EXISTS notion_page_id;
