-- Migration 009: Agent state for pending actions and onboarding tracking
CREATE TABLE IF NOT EXISTS agent_state (
    chat_id BIGINT PRIMARY KEY,
    pending_action TEXT,
    pending_shortcode TEXT,
    note_count INT DEFAULT 0
);
