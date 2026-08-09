-- Add per-repo auto-sync (periodic polling) switch.
ALTER TABLE repositories ADD COLUMN IF NOT EXISTS auto_sync BOOLEAN NOT NULL DEFAULT FALSE;
