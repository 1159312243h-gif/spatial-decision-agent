"""Mandatory validation gates for spatial datasets."""

from .validate import (
    SpatialValidationCode,
    SpatialValidationError,
    SpatialValidationResult,
    parse_crs,
    validate_spatial_dataset,
)

__all__ = [
    "SpatialValidationCode",
    "SpatialValidationError",
    "SpatialValidationResult",
    "parse_crs",
    "validate_spatial_dataset",
]
