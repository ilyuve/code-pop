-- Add per-repo webhook token column for repo-level webhook binding.
ALTER TABLE repositories ADD COLUMN IF NOT EXISTS webhook_token VARCHAR(128);
