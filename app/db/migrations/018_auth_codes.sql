-- Migration 018: One-time login codes for Telegram-based auth
-- Stores short-lived codes sent via Telegram bot for dashboard login

CREATE TABLE IF NOT EXISTS auth_codes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    code TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT timezone('utc'::text, now()) NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    used_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_auth_codes_user_code ON auth_codes(user_id, code);
CREATE INDEX IF NOT EXISTS idx_auth_codes_expires ON auth_codes(expires_at);

-- Enable RLS (backend uses service_role, but keep consistent)
ALTER TABLE auth_codes ENABLE ROW LEVEL SECURITY;

NOTIFY pgrst, 'reload schema';
