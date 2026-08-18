"""Mandatory validation gates for spatial datasets."""

from .analysis import (
    GISAnalysisBlockedError,
    SpatialMetrics,
    calculate_spatial_metrics,
    run_gis_analysis,
)
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
    "GISAnalysisBlockedError",
    "MockSpatialDatasetGateway",
    "SpatialDatasetGateway",
    "SpatialDatasetNotFoundError",
    "SpatialMetrics",
    "SpatialValidationCode",
    "SpatialValidationError",
    "SpatialValidationResult",
    "collect_gis_evidence",
    "calculate_spatial_metrics",
    "parse_crs",
    "run_gis_analysis",
    "validate_spatial_dataset",
]
