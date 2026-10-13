"""
GeoChip: Automated Pipeline for Satellite Imagery & Foundation Model Embeddings.

Scrape, tile, and upload paired Sentinel-2 mosaics and Google Satellite Embeddings
(AlphaEarth 64-D) to Roboflow for computer vision annotation workflows.
"""

__version__ = "0.1.0"

from .auth import init_earth_engine, test_earth_engine_connection
from .downloader import (
    load_aoi_geometry,
    process_sentinel2_mosaic,
    process_satellite_embeddings,
)
from .tiler import create_paired_chips, generate_gse_rgb
from .uploader import upload_chips_to_roboflow

__all__ = [
    "init_earth_engine",
    "test_earth_engine_connection",
    "load_aoi_geometry",
    "process_sentinel2_mosaic",
    "process_satellite_embeddings",
    "create_paired_chips",
    "generate_gse_rgb",
    "upload_chips_to_roboflow",
]
