BEGIN;

ALTER TABLE site_selection.projects
    DROP CONSTRAINT IF EXISTS projects_project_type_check;

ALTER TABLE site_selection.projects
    ADD CONSTRAINT projects_project_type_check CHECK (
        project_type IN (
            'shopping_mall',
            'logistics_park',
            'coffee_shop',
            'convenience_store'
        )
    );

INSERT INTO site_selection.schema_migrations(version)
VALUES ('002_retail_project_types')
ON CONFLICT (version) DO NOTHING;

COMMIT;
