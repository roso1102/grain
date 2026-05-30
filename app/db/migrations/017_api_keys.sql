-- Migration 017: API Key authentication
-- Creates api_keys table for API key-based authentication

CREATE TABLE IF NOT EXISTS api_keys (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    key_hash TEXT NOT NULL UNIQUE,
    key_prefix TEXT NOT NULL,  -- First 8 chars for display/identification
    name TEXT DEFAULT 'Default API Key',
    created_at TIMESTAMPTZ DEFAULT timezone('utc'::text, now()) NOT NULL,
    last_used_at TIMESTAMPTZ,
    expires_at TIMESTAMPTZ,
    is_active BOOLEAN DEFAULT true NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_api_keys_user_id ON api_keys(user_id);
CREATE INDEX IF NOT EXISTS idx_api_keys_key_hash ON api_keys(key_hash);

-- Enable RLS
ALTER TABLE api_keys ENABLE ROW LEVEL SECURITY;

-- Users can manage their own API keys
CREATE POLICY "api_keys_select_own" ON api_keys
    FOR SELECT USING (auth.uid() = (SELECT supabase_user_id FROM users WHERE id = user_id));

CREATE POLICY "api_keys_insert_own" ON api_keys
    FOR INSERT WITH CHECK (auth.uid() = (SELECT supabase_user_id FROM users WHERE id = user_id));

CREATE POLICY "api_keys_update_own" ON api_keys
    FOR UPDATE USING (auth.uid() = (SELECT supabase_user_id FROM users WHERE id = user_id));

CREATE POLICY "api_keys_delete_own" ON api_keys
    FOR DELETE USING (auth.uid() = (SELECT supabase_user_id FROM users WHERE id = user_id));

NOTIFY pgrst, 'reload schema';
