-- Indexes added after the initial schema for existing installations.
CREATE INDEX IF NOT EXISTS features_props_trgm_idx
    ON app.features USING gin ((properties::text) gin_trgm_ops);
CREATE INDEX IF NOT EXISTS attachments_feature_idx
    ON app.attachments(feature_id);
