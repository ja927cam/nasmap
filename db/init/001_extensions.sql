-- Extensions required by NasMap.
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS postgis_raster;
CREATE EXTENSION IF NOT EXISTS hstore;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS citext;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE SCHEMA IF NOT EXISTS app;
CREATE SCHEMA IF NOT EXISTS imports;
CREATE SCHEMA IF NOT EXISTS osm;

COMMENT ON SCHEMA app IS 'Private application data owned by NasMap users.';
COMMENT ON SCHEMA imports IS 'Import jobs, staging and external source metadata.';
COMMENT ON SCHEMA osm IS 'Reserved for osm2pgsql-imported OpenStreetMap data.';
