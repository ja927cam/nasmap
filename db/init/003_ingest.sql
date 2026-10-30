-- Server/NAS-side bulk ingestion uses the existing import job queue with a new
-- job type. This migration is idempotent for existing deployments.
ALTER TABLE imports.import_jobs
    DROP CONSTRAINT IF EXISTS import_jobs_job_type_check;

ALTER TABLE imports.import_jobs
    ADD CONSTRAINT import_jobs_job_type_check
    CHECK (job_type IN ('upload', 'url', 'tessera', 'raster', 'osm', 'export', 'ingest'));
