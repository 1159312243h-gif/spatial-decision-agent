BEGIN;

CREATE TABLE IF NOT EXISTS site_selection.user_site_preferences (
    actor_id text NOT NULL CHECK (
        actor_id ~ '^[A-Za-z0-9._-]{1,120}$'
    ),
    project_type text NOT NULL CHECK (
        project_type IN (
            'shopping_mall',
            'logistics_park',
            'coffee_shop',
            'convenience_store'
        )
    ),
    discovery_radius_km double precision NOT NULL CHECK (
        discovery_radius_km > 0 AND discovery_radius_km <= 7
    ),
    max_candidates integer NOT NULL CHECK (
        max_candidates BETWEEN 3 AND 20
    ),
    minimum_separation_m integer NOT NULL CHECK (
        minimum_separation_m BETWEEN 100 AND 5000
    ),
    fallback_mode text NOT NULL CHECK (
        fallback_mode IN ('strict', 'commercial_land_proxy', 'market_exploration')
    ),
    source_session_id text NOT NULL CHECK (btrim(source_session_id) <> ''),
    source_version_id text NOT NULL CHECK (btrim(source_version_id) <> ''),
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    PRIMARY KEY (actor_id, project_type)
);

CREATE TABLE IF NOT EXISTS site_selection.scenario_memory_episodes (
    episode_id text PRIMARY KEY CHECK (btrim(episode_id) <> ''),
    actor_id text NOT NULL CHECK (
        actor_id ~ '^[A-Za-z0-9._-]{1,120}$'
    ),
    project_type text NOT NULL CHECK (
        project_type IN (
            'shopping_mall',
            'logistics_park',
            'coffee_shop',
            'convenience_store'
        )
    ),
    session_id text NOT NULL CHECK (btrim(session_id) <> ''),
    scenario_id text NOT NULL CHECK (btrim(scenario_id) <> ''),
    version_id text NOT NULL CHECK (btrim(version_id) <> ''),
    region_text text,
    summary text NOT NULL CHECK (btrim(summary) <> ''),
    scenario jsonb NOT NULL CHECK (jsonb_typeof(scenario) = 'object'),
    confirmed_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL,
    UNIQUE (actor_id, version_id)
);

CREATE INDEX IF NOT EXISTS scenario_memory_episodes_actor_project_idx
    ON site_selection.scenario_memory_episodes (
        actor_id, project_type, confirmed_at DESC
    );

INSERT INTO site_selection.schema_migrations(version)
VALUES ('003_scenario_memory')
ON CONFLICT (version) DO NOTHING;

COMMIT;
