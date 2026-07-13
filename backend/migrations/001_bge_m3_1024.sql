-- CodePop migration: switch embedding dimension to 1024 (BAAI/bge-m3)
-- Existing embeddings are incompatible with the new model, so we truncate and recreate.

BEGIN;

-- Vectors are model-specific, cannot be migrated. Truncate dependent tables.
TRUNCATE TABLE embeddings CASCADE;
TRUNCATE TABLE call_graph_edges CASCADE;
TRUNCATE TABLE symbols CASCADE;
TRUNCATE TABLE code_files CASCADE;

-- Reset repository status so they will be re-indexed with the new model.
UPDATE repositories
   SET status = 'pending',
       last_indexed_at = NULL,
       error_message = NULL;

-- pgvector stores dimension in the column type, must ALTER to resize.
ALTER TABLE embeddings ALTER COLUMN embedding TYPE vector(1024);

COMMIT;
