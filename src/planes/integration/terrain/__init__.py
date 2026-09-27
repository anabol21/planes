"""Integration-owned acquisition of local terrain artifacts."""

from planes.integration.terrain.opentopography import (
    COP30_DATASET,
    SurveyBounds,
    TerrainAcquisitionError,
    acquire_terrain_for_area,
    bbox_from_geojson,
)

__all__ = [
    "COP30_DATASET",
    "SurveyBounds",
    "TerrainAcquisitionError",
    "acquire_terrain_for_area",
    "bbox_from_geojson",
]
