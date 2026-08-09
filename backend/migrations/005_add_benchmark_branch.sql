-- Add branch column to benchmark_runs for per-(query, branch) benchmark cases.
ALTER TABLE benchmark_runs ADD COLUMN IF NOT EXISTS branch VARCHAR(128) NOT NULL DEFAULT 'main';
