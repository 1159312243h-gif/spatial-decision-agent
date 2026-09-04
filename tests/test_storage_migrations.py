from pathlib import Path


MIGRATION = (
    Path(__file__).parents[1]
    / "deploy"
    / "migrations"
    / "001_initial.sql"
)
RETAIL_MIGRATION = MIGRATION.with_name("002_retail_project_types.sql")
MEMORY_MIGRATION = MIGRATION.with_name("003_scenario_memory.sql")


def migration_sql() -> str:
    return MIGRATION.read_text(encoding="utf-8")


def test_initial_migration_defines_required_tables() -> None:
    sql = migration_sql()

    for table in ("projects", "spatial_layers", "spatial_features", "pois"):
        assert f"site_selection.{table}" in sql


def test_geometry_columns_have_explicit_srid_and_spatial_indexes() -> None:
    sql = migration_sql()

    assert "geometry geometry(Geometry, 4326)" in sql
    assert "geometry geometry(Point, 4326)" in sql
    assert "spatial_features USING GIST(geometry)" in sql
    assert "pois USING GIST(geometry)" in sql


def test_poi_identity_has_database_unique_constraint() -> None:
    assert "UNIQUE (source, source_id)" in migration_sql()


def test_retail_migration_expands_project_type_constraint() -> None:
    sql = RETAIL_MIGRATION.read_text(encoding="utf-8")

    assert "DROP CONSTRAINT IF EXISTS projects_project_type_check" in sql
    for project_type in (
        "shopping_mall",
        "logistics_park",
        "coffee_shop",
        "convenience_store",
    ):
        assert f"'{project_type}'" in sql
    assert "002_retail_project_types" in sql


def test_migration_runner_discovers_all_versions_in_order() -> None:
    from scripts.apply_postgis_migrations import migration_paths

    assert [path.name for path in migration_paths()] == [
        "001_initial.sql",
        "002_retail_project_types.sql",
        "003_scenario_memory.sql",
    ]


def test_memory_migration_defines_actor_scoped_preferences_and_episodes() -> None:
    sql = MEMORY_MIGRATION.read_text(encoding="utf-8")

    assert "site_selection.user_site_preferences" in sql
    assert "PRIMARY KEY (actor_id, project_type)" in sql
    assert "site_selection.scenario_memory_episodes" in sql
    assert "UNIQUE (actor_id, version_id)" in sql
    assert "003_scenario_memory" in sql
