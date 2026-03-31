-- Add the job preference column to capture the user's desired role.
ALTER TABLE users
    ADD COLUMN IF NOT EXISTS job_preference TEXT CHECK (char_length(job_preference) <= 64);
