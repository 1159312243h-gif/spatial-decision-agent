"""Mandatory validation gates for spatial datasets."""

from .gateway import (
    MockSpatialDatasetGateway,
    SpatialDatasetGateway,
    SpatialDatasetNotFoundError,
    collect_gis_evidence,
)
from .validate import (
    SpatialValidationCode,
    SpatialValidationError,
    SpatialValidationResult,
    parse_crs,
    validate_spatial_dataset,
)

__all__ = [
    "MockSpatialDatasetGateway",
    "SpatialDatasetGateway",
    "SpatialDatasetNotFoundError",
    "SpatialValidationCode",
    "SpatialValidationError",
    "SpatialValidationResult",
    "collect_gis_evidence",
    "parse_crs",
    "validate_spatial_dataset",
]
