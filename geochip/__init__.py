"""
GeoChip: Interactive Geospatial Earth Observation Pipeline & Roboflow Ingestion.

Download multi-sensor satellite imagery (Sentinel-2, Landsat 8/9, Sentinel-1 SAR, MODIS, SRTM DEM),
generate customizable georeferenced chips, and upload annotation batches to Roboflow.
"""

__version__ = "2.0.0"

from .auth import init_earth_engine, login_flow, test_earth_engine_connection
from .datasets import DATASETS, COMPOSITE_METHODS
from .downloader import (
    load_aoi_geometry,
    interactive_download_workflow,
)
from .tiler import (
    create_single_raster_chips,
    interactive_chipping_workflow,
    CHIP_SIZES,
)
from .uploader import (
    upload_chips_to_roboflow,
    interactive_upload_flow,
)

__all__ = [
    "__version__",
    "init_earth_engine",
    "login_flow",
    "test_earth_engine_connection",
    "DATASETS",
    "COMPOSITE_METHODS",
    "load_aoi_geometry",
    "interactive_download_workflow",
    "create_single_raster_chips",
    "interactive_chipping_workflow",
    "CHIP_SIZES",
    "upload_chips_to_roboflow",
    "interactive_upload_flow",
]
