-- Add per-repo auto-sync polling interval in minutes (5 / 15 / 30 / 60).
ALTER TABLE repositories ADD COLUMN IF NOT EXISTS auto_sync_interval INTEGER NOT NULL DEFAULT 5;
