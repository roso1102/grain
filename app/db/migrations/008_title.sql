-- Migration 008: Add title column to notes table
ALTER TABLE notes ADD COLUMN IF NOT EXISTS title TEXT;
