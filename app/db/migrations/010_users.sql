-- Migration 010: Create users table
-- Phase 0 of multi-tenant migration: additive only, no breaking changes.

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    telegram_chat_id BIGINT UNIQUE,
    display_name TEXT,
    created_at TIMESTAMPTZ DEFAULT timezone('utc'::text, now()) NOT NULL
);

-- Seed from agent_state if that table exists (it may not on fresh projects)
DO $$
BEGIN
    IF EXISTS (
        SELECT FROM information_schema.tables
        WHERE table_name = 'agent_state'
    ) THEN
        INSERT INTO users (telegram_chat_id, display_name)
        SELECT DISTINCT chat_id, 'Telegram User'
        FROM agent_state
        WHERE chat_id IS NOT NULL
        ON CONFLICT (telegram_chat_id) DO NOTHING;
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_users_telegram_chat_id ON users(telegram_chat_id);
