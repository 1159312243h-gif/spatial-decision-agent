from __future__ import annotations

from pathlib import Path

import geopandas as gpd

from ..domain import DatasetManifest, DatasetSource
from .gateway import SpatialDatasetAccessError, SpatialDatasetNotFoundError


SUPPORTED_SPATIAL_FILE_SUFFIXES = frozenset(
    {".geojson", ".json", ".gpkg", ".shp"}
)


class FileSpatialDatasetGateway:
    """Load manifested spatial files from one explicitly bounded root."""

    def __init__(self, root: str | Path) -> None:
        root_path = Path(root).resolve()
        if not root_path.is_dir():
            raise ValueError("空间文件根目录不存在或不是目录")
        self._root = root_path

    @property
    def root(self) -> Path:
        return self._root

    def load(self, manifest: DatasetManifest) -> gpd.GeoDataFrame:
        path = self._resolve_manifest_path(manifest)
        if not path.is_file():
            raise SpatialDatasetNotFoundError(
                f"空间数据文件不存在：{manifest.dataset_id}"
            )
        try:
            frame = gpd.read_file(path)
        except Exception as exc:
            raise SpatialDatasetAccessError(
                "read_failed: "
                f"dataset_id={manifest.dataset_id}, "
                f"error_type={type(exc).__name__}"
            ) from exc
        return frame.copy(deep=True)

    def _resolve_manifest_path(self, manifest: DatasetManifest) -> Path:
        if manifest.source is not DatasetSource.FILE:
            raise SpatialDatasetAccessError(
                f"unsupported_source: dataset_id={manifest.dataset_id}"
            )

        location = Path(manifest.location)
        if location.is_absolute():
            raise SpatialDatasetAccessError(
                f"absolute_location: dataset_id={manifest.dataset_id}"
            )
        try:
            resolved = (self._root / location).resolve()
            resolved.relative_to(self._root)
        except (OSError, ValueError) as exc:
            raise SpatialDatasetAccessError(
                f"location_outside_root: dataset_id={manifest.dataset_id}"
            ) from exc

        if resolved.suffix.lower() not in SUPPORTED_SPATIAL_FILE_SUFFIXES:
            raise SpatialDatasetAccessError(
                f"unsupported_format: dataset_id={manifest.dataset_id}"
            )
        return resolved
