BEGIN;

CREATE EXTENSION IF NOT EXISTS postgis;
CREATE SCHEMA IF NOT EXISTS site_selection;

CREATE TABLE IF NOT EXISTS site_selection.schema_migrations (
    version text PRIMARY KEY,
    applied_at timestamptz NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS site_selection.projects (
    project_id text PRIMARY KEY,
    project_type text NOT NULL CHECK (
        project_type IN ('shopping_mall', 'logistics_park')
    ),
    name text NOT NULL CHECK (btrim(name) <> ''),
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL
);

CREATE TABLE IF NOT EXISTS site_selection.spatial_layers (
    layer_id text PRIMARY KEY,
    project_id text REFERENCES site_selection.projects(project_id)
        ON DELETE CASCADE,
    name text NOT NULL CHECK (btrim(name) <> ''),
    layer_type text NOT NULL CHECK (btrim(layer_type) <> ''),
    source text NOT NULL CHECK (source IN ('api', 'postgis', 'file')),
    source_crs text NOT NULL CHECK (btrim(source_crs) <> ''),
    normalized_crs text NOT NULL DEFAULT 'EPSG:4326'
        CHECK (normalized_crs = 'EPSG:4326'),
    version text NOT NULL CHECK (btrim(version) <> ''),
    data_hash char(64) NOT NULL CHECK (data_hash ~ '^[0-9a-f]{64}$'),
    required_fields jsonb NOT NULL CHECK (
        jsonb_typeof(required_fields) = 'array'
    ),
    updated_at timestamptz NOT NULL,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (
        jsonb_typeof(metadata) = 'object'
    )
);

CREATE TABLE IF NOT EXISTS site_selection.spatial_features (
    feature_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    layer_id text NOT NULL REFERENCES site_selection.spatial_layers(layer_id)
        ON DELETE CASCADE,
    source_feature_id text NOT NULL CHECK (btrim(source_feature_id) <> ''),
    geometry geometry(Geometry, 4326) NOT NULL,
    properties jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (
        jsonb_typeof(properties) = 'object'
    ),
    UNIQUE (layer_id, source_feature_id)
);

CREATE TABLE IF NOT EXISTS site_selection.pois (
    poi_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source text NOT NULL CHECK (btrim(source) <> ''),
    source_id text NOT NULL CHECK (btrim(source_id) <> ''),
    name text NOT NULL CHECK (btrim(name) <> ''),
    category text NOT NULL CHECK (btrim(category) <> ''),
    source_crs text NOT NULL CHECK (btrim(source_crs) <> ''),
    normalized_crs text NOT NULL DEFAULT 'EPSG:4326'
        CHECK (normalized_crs = 'EPSG:4326'),
    geometry geometry(Point, 4326) NOT NULL,
    address text,
    fetched_at timestamptz NOT NULL,
    raw_payload jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (
        jsonb_typeof(raw_payload) = 'object'
    ),
    created_at timestamptz NOT NULL DEFAULT NOW(),
    updated_at timestamptz NOT NULL DEFAULT NOW(),
    UNIQUE (source, source_id)
);

CREATE INDEX IF NOT EXISTS spatial_layers_project_id_idx
    ON site_selection.spatial_layers(project_id);
CREATE INDEX IF NOT EXISTS spatial_features_layer_id_idx
    ON site_selection.spatial_features(layer_id);
CREATE INDEX IF NOT EXISTS spatial_features_geometry_gix
    ON site_selection.spatial_features USING GIST(geometry);
CREATE INDEX IF NOT EXISTS pois_geometry_gix
    ON site_selection.pois USING GIST(geometry);
CREATE INDEX IF NOT EXISTS pois_category_idx
    ON site_selection.pois(category);

INSERT INTO site_selection.schema_migrations(version)
VALUES ('001_initial')
ON CONFLICT (version) DO NOTHING;

COMMIT;
