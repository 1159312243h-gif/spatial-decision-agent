from pathlib import Path


MIGRATION = (
    Path(__file__).parents[1]
    / "deploy"
    / "migrations"
    / "001_initial.sql"
)


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
