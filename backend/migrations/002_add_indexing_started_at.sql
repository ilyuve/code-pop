-- CodePop migration: add indexing_started_at to repositories for elapsed/ETA tracking

BEGIN;

ALTER TABLE repositories
    ADD COLUMN IF NOT EXISTS indexing_started_at TIMESTAMP WITHOUT TIME ZONE;

COMMIT;
