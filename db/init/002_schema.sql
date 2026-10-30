-- NasMap core schema. This file is idempotent so it can be applied both by the
-- Postgres entrypoint and by `python -m app.migrate`.

CREATE TABLE IF NOT EXISTS app.schema_migrations (
    filename    text PRIMARY KEY,
    applied_at  timestamptz NOT NULL DEFAULT now()
);

CREATE OR REPLACE FUNCTION app.set_updated_at() RETURNS trigger AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- ---------------------------------------------------------------------------
-- Users, sessions, API keys
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS app.users (
    id                    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    email                 citext NOT NULL UNIQUE,
    password_hash         text,
    display_name          text NOT NULL DEFAULT '',
    role                  text NOT NULL DEFAULT 'viewer'
                          CHECK (role IN ('admin', 'editor', 'viewer')),
    is_active             boolean NOT NULL DEFAULT true,
    osm_user_id           bigint UNIQUE,
    osm_username          text,
    osm_access_token_enc  text,
    osm_refresh_token_enc text,
    osm_token_expires_at  timestamptz,
    created_at            timestamptz NOT NULL DEFAULT now(),
    updated_at            timestamptz NOT NULL DEFAULT now(),
    last_login_at         timestamptz
);
CREATE INDEX IF NOT EXISTS users_role_idx ON app.users(role);
CREATE INDEX IF NOT EXISTS users_email_trgm_idx ON app.users USING gin ((email::text) gin_trgm_ops);

DROP TRIGGER IF EXISTS users_updated_at ON app.users;
CREATE TRIGGER users_updated_at BEFORE UPDATE ON app.users
    FOR EACH ROW EXECUTE FUNCTION app.set_updated_at();

CREATE TABLE IF NOT EXISTS app.sessions (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id      uuid NOT NULL REFERENCES app.users(id) ON DELETE CASCADE,
    token_hash   text NOT NULL UNIQUE,
    user_agent   text,
    ip_address   inet,
    expires_at   timestamptz NOT NULL,
    revoked_at   timestamptz,
    created_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS sessions_user_idx ON app.sessions(user_id);
CREATE INDEX IF NOT EXISTS sessions_expiry_idx ON app.sessions(expires_at);

CREATE TABLE IF NOT EXISTS app.api_keys (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id      uuid NOT NULL REFERENCES app.users(id) ON DELETE CASCADE,
    name         text NOT NULL,
    key_prefix   text NOT NULL,
    key_hash     text NOT NULL UNIQUE,
    scopes       text[] NOT NULL DEFAULT ARRAY['read'],
    expires_at   timestamptz,
    last_used_at timestamptz,
    revoked_at   timestamptz,
    created_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS api_keys_user_idx ON app.api_keys(user_id);

-- ---------------------------------------------------------------------------
-- Layers and features
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS app.layers (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id      uuid NOT NULL REFERENCES app.users(id) ON DELETE RESTRICT,
    name          text NOT NULL,
    description   text NOT NULL DEFAULT '',
    visibility    text NOT NULL DEFAULT 'private'
                  CHECK (visibility IN ('private', 'organisation', 'public')),
    geometry_type text NOT NULL DEFAULT 'geometry'
                  CHECK (geometry_type IN ('point', 'line', 'polygon', 'geometry', 'raster', 'table')),
    source_type   text NOT NULL DEFAULT 'manual'
                  CHECK (source_type IN ('upload', 'url', 'tessera', 'osm', 'api', 'manual')),
    style         jsonb NOT NULL DEFAULT '{}'::jsonb,
    metadata      jsonb NOT NULL DEFAULT '{}'::jsonb,
    attribution   text NOT NULL DEFAULT '',
    licence       text NOT NULL DEFAULT '',
    feature_count integer NOT NULL DEFAULT 0,
    deleted_at    timestamptz,
    created_at    timestamptz NOT NULL DEFAULT now(),
    updated_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS layers_owner_idx ON app.layers(owner_id);
CREATE INDEX IF NOT EXISTS layers_visibility_idx ON app.layers(visibility) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS layers_updated_idx ON app.layers(updated_at DESC) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS layers_name_trgm_idx ON app.layers USING gin (name gin_trgm_ops);
CREATE INDEX IF NOT EXISTS layers_metadata_idx ON app.layers USING gin (metadata jsonb_path_ops);

DROP TRIGGER IF EXISTS layers_updated_at ON app.layers;
CREATE TRIGGER layers_updated_at BEFORE UPDATE ON app.layers
    FOR EACH ROW EXECUTE FUNCTION app.set_updated_at();

CREATE TABLE IF NOT EXISTS app.layer_permissions (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    layer_id   uuid NOT NULL REFERENCES app.layers(id) ON DELETE CASCADE,
    user_id    uuid NOT NULL REFERENCES app.users(id) ON DELETE CASCADE,
    role       text NOT NULL CHECK (role IN ('editor', 'viewer')),
    created_by uuid REFERENCES app.users(id) ON DELETE SET NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (layer_id, user_id)
);
CREATE INDEX IF NOT EXISTS layer_permissions_user_idx ON app.layer_permissions(user_id);

CREATE TABLE IF NOT EXISTS app.features (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    layer_id    uuid NOT NULL REFERENCES app.layers(id) ON DELETE CASCADE,
    properties  jsonb NOT NULL DEFAULT '{}'::jsonb,
    geometry    geometry(Geometry, 4326),
    created_by  uuid REFERENCES app.users(id) ON DELETE SET NULL,
    updated_by  uuid REFERENCES app.users(id) ON DELETE SET NULL,
    version     integer NOT NULL DEFAULT 1,
    valid_from  timestamptz,
    valid_to    timestamptz,
    deleted_at  timestamptz,
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS features_layer_idx ON app.features(layer_id) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS features_geom_idx ON app.features USING gist (geometry);
CREATE INDEX IF NOT EXISTS features_props_idx ON app.features USING gin (properties jsonb_path_ops);
CREATE INDEX IF NOT EXISTS features_props_trgm_idx ON app.features USING gin ((properties::text) gin_trgm_ops);
CREATE INDEX IF NOT EXISTS features_updated_idx ON app.features(updated_at DESC);

DROP TRIGGER IF EXISTS features_updated_at ON app.features;
CREATE TRIGGER features_updated_at BEFORE UPDATE ON app.features
    FOR EACH ROW EXECUTE FUNCTION app.set_updated_at();

CREATE TABLE IF NOT EXISTS app.feature_versions (
    id          bigserial PRIMARY KEY,
    feature_id  uuid NOT NULL REFERENCES app.features(id) ON DELETE CASCADE,
    version     integer NOT NULL,
    properties  jsonb NOT NULL DEFAULT '{}'::jsonb,
    geometry    geometry(Geometry, 4326),
    changed_by  uuid REFERENCES app.users(id) ON DELETE SET NULL,
    change_type text NOT NULL CHECK (change_type IN ('insert', 'update', 'delete')),
    created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS feature_versions_feature_idx ON app.feature_versions(feature_id, version DESC);
CREATE INDEX IF NOT EXISTS feature_versions_geom_idx ON app.feature_versions USING gist (geometry);

CREATE OR REPLACE FUNCTION app.feature_version_before() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'UPDATE' AND NEW.version = OLD.version THEN
        NEW.version := OLD.version + 1;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION app.feature_version_after() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        INSERT INTO app.feature_versions(feature_id, version, properties, geometry, changed_by, change_type)
        VALUES (NEW.id, NEW.version, NEW.properties, NEW.geometry, NEW.created_by, 'insert');
        RETURN NEW;
    ELSIF TG_OP = 'UPDATE' THEN
        INSERT INTO app.feature_versions(feature_id, version, properties, geometry, changed_by, change_type)
        VALUES (OLD.id, OLD.version, OLD.properties, OLD.geometry, NEW.updated_by,
                CASE WHEN NEW.deleted_at IS NOT NULL AND OLD.deleted_at IS NULL THEN 'delete' ELSE 'update' END);
        RETURN NEW;
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS features_version ON app.features;
DROP TRIGGER IF EXISTS features_version_before ON app.features;
DROP TRIGGER IF EXISTS features_version_after ON app.features;
CREATE TRIGGER features_version_before BEFORE INSERT OR UPDATE ON app.features
    FOR EACH ROW EXECUTE FUNCTION app.feature_version_before();
CREATE TRIGGER features_version_after AFTER INSERT OR UPDATE ON app.features
    FOR EACH ROW EXECUTE FUNCTION app.feature_version_after();

CREATE OR REPLACE FUNCTION app.sync_feature_count() RETURNS trigger AS $$
DECLARE
    target_layer uuid;
BEGIN
    IF TG_OP = 'DELETE' THEN
        target_layer := OLD.layer_id;
    ELSE
        target_layer := NEW.layer_id;
    END IF;
    UPDATE app.layers l
       SET feature_count = (SELECT count(*) FROM app.features f
                             WHERE f.layer_id = target_layer AND f.deleted_at IS NULL)
     WHERE l.id = target_layer;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS features_count ON app.features;
CREATE TRIGGER features_count AFTER INSERT OR DELETE ON app.features
    FOR EACH ROW EXECUTE FUNCTION app.sync_feature_count();

DROP TRIGGER IF EXISTS features_count_update ON app.features;
CREATE TRIGGER features_count_update AFTER UPDATE OF deleted_at, layer_id ON app.features
    FOR EACH ROW EXECUTE FUNCTION app.sync_feature_count();

CREATE TABLE IF NOT EXISTS app.attachments (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    layer_id     uuid REFERENCES app.layers(id) ON DELETE CASCADE,
    feature_id   uuid REFERENCES app.features(id) ON DELETE CASCADE,
    filename     text NOT NULL,
    content_type text NOT NULL DEFAULT 'application/octet-stream',
    size_bytes   bigint NOT NULL DEFAULT 0,
    storage_path text NOT NULL,
    checksum     text,
    created_by   uuid REFERENCES app.users(id) ON DELETE SET NULL,
    created_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS attachments_layer_idx ON app.attachments(layer_id);
CREATE INDEX IF NOT EXISTS attachments_feature_idx ON app.attachments(feature_id);

-- ---------------------------------------------------------------------------
-- Imports, external sources, Tessera, audit
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS imports.import_jobs (
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id          uuid NOT NULL REFERENCES app.users(id) ON DELETE CASCADE,
    layer_id         uuid REFERENCES app.layers(id) ON DELETE SET NULL,
    job_type         text NOT NULL CHECK (job_type IN ('upload', 'url', 'tessera', 'raster', 'osm', 'export', 'ingest')),
    status           text NOT NULL DEFAULT 'queued'
                     CHECK (status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')),
    progress         integer NOT NULL DEFAULT 0 CHECK (progress BETWEEN 0 AND 100),
    message          text NOT NULL DEFAULT '',
    error            text,
    source_url       text,
    source_path      text,
    options          jsonb NOT NULL DEFAULT '{}'::jsonb,
    result           jsonb NOT NULL DEFAULT '{}'::jsonb,
    cancel_requested boolean NOT NULL DEFAULT false,
    attempts         integer NOT NULL DEFAULT 0,
    created_at       timestamptz NOT NULL DEFAULT now(),
    started_at       timestamptz,
    finished_at      timestamptz,
    updated_at       timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS import_jobs_user_idx ON imports.import_jobs(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS import_jobs_status_idx ON imports.import_jobs(status);
CREATE INDEX IF NOT EXISTS import_jobs_layer_idx ON imports.import_jobs(layer_id);

DROP TRIGGER IF EXISTS import_jobs_updated_at ON imports.import_jobs;
CREATE TRIGGER import_jobs_updated_at BEFORE UPDATE ON imports.import_jobs
    FOR EACH ROW EXECUTE FUNCTION app.set_updated_at();

CREATE TABLE IF NOT EXISTS imports.external_sources (
    id                      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id                 uuid NOT NULL REFERENCES app.users(id) ON DELETE CASCADE,
    layer_id                uuid REFERENCES app.layers(id) ON DELETE SET NULL,
    kind                    text NOT NULL
                            CHECK (kind IN ('geojson', 'gpkg', 'cog', 'wms', 'wfs', 'arcgis', 'stac', 'url', 'tessera')),
    url                     text NOT NULL,
    licence                 text NOT NULL DEFAULT '',
    attribution             text NOT NULL DEFAULT '',
    checksum                text,
    retrieved_at            timestamptz,
    last_import_at          timestamptz,
    refresh_interval_seconds integer,
    next_refresh_at         timestamptz,
    enabled                 boolean NOT NULL DEFAULT true,
    metadata                jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at              timestamptz NOT NULL DEFAULT now(),
    updated_at              timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS external_sources_user_idx ON imports.external_sources(user_id);
CREATE INDEX IF NOT EXISTS external_sources_refresh_idx ON imports.external_sources(next_refresh_at)
    WHERE enabled AND refresh_interval_seconds IS NOT NULL;

DROP TRIGGER IF EXISTS external_sources_updated_at ON imports.external_sources;
CREATE TRIGGER external_sources_updated_at BEFORE UPDATE ON imports.external_sources
    FOR EACH ROW EXECUTE FUNCTION app.set_updated_at();

CREATE TABLE IF NOT EXISTS app.tessera_datasets (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    layer_id     uuid NOT NULL REFERENCES app.layers(id) ON DELETE CASCADE,
    bbox         geometry(Polygon, 4326) NOT NULL,
    year         integer NOT NULL,
    variant      text NOT NULL DEFAULT '',
    tile_ids     jsonb NOT NULL DEFAULT '[]'::jsonb,
    band_count   integer,
    resolution   double precision,
    crs          text,
    licence      text NOT NULL DEFAULT '',
    attribution  text NOT NULL DEFAULT '',
    cache_path   text,
    created_by   uuid REFERENCES app.users(id) ON DELETE SET NULL,
    created_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS tessera_datasets_layer_idx ON app.tessera_datasets(layer_id);
CREATE INDEX IF NOT EXISTS tessera_datasets_bbox_idx ON app.tessera_datasets USING gist (bbox);

CREATE TABLE IF NOT EXISTS app.audit_log (
    id          bigserial PRIMARY KEY,
    user_id     uuid REFERENCES app.users(id) ON DELETE SET NULL,
    action      text NOT NULL,
    entity_type text NOT NULL,
    entity_id   text,
    details     jsonb NOT NULL DEFAULT '{}'::jsonb,
    ip_address  inet,
    created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS audit_log_created_idx ON app.audit_log(created_at DESC);
CREATE INDEX IF NOT EXISTS audit_log_entity_idx ON app.audit_log(entity_type, entity_id);
CREATE INDEX IF NOT EXISTS audit_log_user_idx ON app.audit_log(user_id);

CREATE TABLE IF NOT EXISTS app.oauth_states (
    state       text PRIMARY KEY,
    user_id     uuid NOT NULL REFERENCES app.users(id) ON DELETE CASCADE,
    provider    text NOT NULL DEFAULT 'osm',
    redirect_to text,
    created_at  timestamptz NOT NULL DEFAULT now(),
    expires_at  timestamptz NOT NULL
);

CREATE TABLE IF NOT EXISTS app.osm_publications (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id       uuid NOT NULL REFERENCES app.users(id) ON DELETE CASCADE,
    feature_id    uuid REFERENCES app.features(id) ON DELETE SET NULL,
    layer_id      uuid REFERENCES app.layers(id) ON DELETE SET NULL,
    changeset_id  bigint,
    osm_type      text,
    osm_id        bigint,
    status        text NOT NULL DEFAULT 'preview'
                  CHECK (status IN ('preview', 'dry_run', 'published', 'failed')),
    comment       text NOT NULL DEFAULT '',
    diff_xml      text,
    response      jsonb NOT NULL DEFAULT '{}'::jsonb,
    error         text,
    created_at    timestamptz NOT NULL DEFAULT now(),
    finished_at   timestamptz
);
CREATE INDEX IF NOT EXISTS osm_publications_user_idx ON app.osm_publications(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS osm_publications_feature_idx ON app.osm_publications(feature_id);

CREATE TABLE IF NOT EXISTS imports.staging_features (
    id         bigserial PRIMARY KEY,
    job_id     uuid NOT NULL REFERENCES imports.import_jobs(id) ON DELETE CASCADE,
    properties jsonb NOT NULL DEFAULT '{}'::jsonb,
    geometry   geometry(Geometry, 4326),
    valid      boolean NOT NULL DEFAULT true,
    error      text
);
CREATE INDEX IF NOT EXISTS staging_features_job_idx ON imports.staging_features(job_id);
CREATE INDEX IF NOT EXISTS staging_features_geom_idx ON imports.staging_features USING gist (geometry);
