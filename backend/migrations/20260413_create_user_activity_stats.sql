-- Track how many practice interviews and mock tests each user has completed.
CREATE TABLE IF NOT EXISTS user_activity_stats (
    user_id UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    practice_interviews INTEGER NOT NULL DEFAULT 0 CHECK (practice_interviews >= 0),
    mock_tests INTEGER NOT NULL DEFAULT 0 CHECK (mock_tests >= 0),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_user_activity_stats_updated_at
    ON user_activity_stats (updated_at DESC);
