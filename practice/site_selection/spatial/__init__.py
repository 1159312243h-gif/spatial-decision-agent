"""Mandatory validation gates for spatial datasets."""

from .analysis import (
    GISAnalysisBlockedError,
    SpatialMetrics,
    calculate_spatial_metrics,
    run_gis_analysis,
)
from .constraint_analysis import (
    ConstraintAnalysisBlockedError,
    run_spatial_constraint_analysis,
)
from .file_gateway import (
    SUPPORTED_SPATIAL_FILE_SUFFIXES,
    FileSpatialDatasetGateway,
)
from .gateway import (
    MockSpatialDatasetGateway,
    SpatialDatasetAccessError,
    SpatialDatasetGateway,
    SpatialDatasetNotFoundError,
    collect_gis_evidence,
)
from .postgis_gateway import PostGISSpatialDatasetGateway
from .validate import (
    SpatialValidationCode,
    SpatialValidationError,
    SpatialValidationResult,
    parse_crs,
    validate_spatial_dataset,
)

__all__ = [
    "ConstraintAnalysisBlockedError",
    "FileSpatialDatasetGateway",
    "GISAnalysisBlockedError",
    "MockSpatialDatasetGateway",
    "PostGISSpatialDatasetGateway",
    "SUPPORTED_SPATIAL_FILE_SUFFIXES",
    "SpatialDatasetAccessError",
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
    "run_spatial_constraint_analysis",
    "validate_spatial_dataset",
]
