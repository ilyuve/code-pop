-- CodePop migration: add branch support for repository and core data tables

BEGIN;

-- Repository-level branch metadata
ALTER TABLE repositories
    ADD COLUMN IF NOT EXISTS default_branch VARCHAR(128) NOT NULL DEFAULT 'main',
    ADD COLUMN IF NOT EXISTS active_branches TEXT,
    ADD COLUMN IF NOT EXISTS branch_commits TEXT NOT NULL DEFAULT '{}',
    ADD COLUMN IF NOT EXISTS branch_deleted_files TEXT NOT NULL DEFAULT '{}',
    ADD COLUMN IF NOT EXISTS sync_mode VARCHAR(32) NOT NULL DEFAULT 'auto';

-- Add branch column to core data tables
ALTER TABLE code_files
    ADD COLUMN IF NOT EXISTS branch VARCHAR(128) NOT NULL DEFAULT 'main';

ALTER TABLE symbols
    ADD COLUMN IF NOT EXISTS branch VARCHAR(128) NOT NULL DEFAULT 'main';

ALTER TABLE embeddings
    ADD COLUMN IF NOT EXISTS branch VARCHAR(128) NOT NULL DEFAULT 'main';

ALTER TABLE call_graph_edges
    ADD COLUMN IF NOT EXISTS branch VARCHAR(128) NOT NULL DEFAULT 'main';

ALTER TABLE framework_routes
    ADD COLUMN IF NOT EXISTS branch VARCHAR(128) NOT NULL DEFAULT 'main';

-- Change CodeFile unique constraint from (repo_id, path) to (repo_id, branch, path)
ALTER TABLE code_files
    DROP CONSTRAINT IF EXISTS uix_file_repo_path;

ALTER TABLE code_files
    ADD CONSTRAINT uix_file_repo_branch_path UNIQUE (repo_id, branch, path);

-- Backfill existing rows (defensive; default should already have done this)
UPDATE code_files SET branch = 'main' WHERE branch IS NULL;
UPDATE symbols SET branch = 'main' WHERE branch IS NULL;
UPDATE embeddings SET branch = 'main' WHERE branch IS NULL;
UPDATE call_graph_edges SET branch = 'main' WHERE branch IS NULL;
UPDATE framework_routes SET branch = 'main' WHERE branch IS NULL;

-- Initialize active_branches for existing repositories
UPDATE repositories
   SET active_branches = '["main"]'
 WHERE active_branches IS NULL;

COMMIT;
