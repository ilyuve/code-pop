-- CodePop migration: add repository description column (fetched from remote API)

BEGIN;

ALTER TABLE repositories
    ADD COLUMN IF NOT EXISTS description VARCHAR(512);

COMMIT;
