"""
GeoChip Earth Observation Datasets Registry.
Contains dataset definitions, band configurations, cloud masking functions,
and visualization settings for Google Earth Engine.
"""

# Available Earth Observation Datasets
DATASETS = {
    "sentinel-2": {
        "id": "COPERNICUS/S2_SR_HARMONIZED",
        "name": "Copernicus Sentinel-2 L2A (10m)",
        "desc": "Optical Multispectral, 10m Ground Resolution, Global Coverage",
        "type": "optical",
        "cloud_prop": "CLOUDY_PIXEL_PERCENTAGE",
        "default_bands": ["B4", "B3", "B2"],  # Red, Green, Blue
        "scale": 10,
        "max_val": 3000.0,
    },
    "landsat-9": {
        "id": "LANDSAT/LC09/C02/T1_L2",
        "name": "USGS Landsat 9 OLI-2 / TIRS-2 C2 L2 (30m)",
        "desc": "Optical Multispectral, 30m Ground Resolution, Launch 2021-Present",
        "type": "optical",
        "cloud_prop": "CLOUD_COVER",
        "default_bands": ["SR_B4", "SR_B3", "SR_B2"],  # Red, Green, Blue
        "scale": 30,
        "max_val": 0.3,
    },
    "landsat-8": {
        "id": "LANDSAT/LC08/C02/T1_L2",
        "name": "USGS Landsat 8 OLI / TIRS C2 L2 (30m)",
        "desc": "Optical Multispectral, 30m Ground Resolution, Archive 2013-Present",
        "type": "optical",
        "cloud_prop": "CLOUD_COVER",
        "default_bands": ["SR_B4", "SR_B3", "SR_B2"],  # Red, Green, Blue
        "scale": 30,
        "max_val": 0.3,
    },
    "sentinel-1": {
        "id": "COPERNICUS/S1_GRD",
        "name": "Copernicus Sentinel-1 SAR GRD (10m C-Band Radar)",
        "desc": "All-Weather, Day & Night, Cloud-Proof Radar (VV / VH)",
        "type": "radar",
        "cloud_prop": None,
        "default_bands": ["VV", "VH"],
        "scale": 10,
        "max_val": 1.0,
    },
    "modis": {
        "id": "MODIS/061/MOD09GA",
        "name": "MODIS Terra Daily Surface Reflectance (250m/500m)",
        "desc": "High Temporal Frequency (Daily Revisitation), Large Scale Overview",
        "type": "optical",
        "cloud_prop": None,
        "default_bands": ["sur_refl_b01", "sur_refl_b04", "sur_refl_b03"],  # Red, Green, Blue
        "scale": 250,
        "max_val": 3000.0,
    },
    "dem-srtm": {
        "id": "USGS/SRTMGL1_003",
        "name": "NASA SRTM Digital Elevation Model (30m)",
        "desc": "Topography & Elevation Map, Global 1 Arc-Second (30m)",
        "type": "dem",
        "cloud_prop": None,
        "default_bands": ["elevation"],
        "scale": 30,
        "max_val": 4000.0,
    },
}

COMPOSITE_METHODS = [
    {
        "id": "median",
        "name": "Median Composite (Standard De-clouding)",
        "desc": "Reduces per-pixel median values to eliminate transient clouds and shadows",
    },
    {
        "id": "q25",
        "name": "First Quartile / 25th Percentile (Copernicus Browser Style)",
        "desc": "Official Copernicus Quarterly Mosaic algorithm (first quartile) for clean, haze-free imagery",
    },
    {
        "id": "mean",
        "name": "Mean Average Composite",
        "desc": "Calculates average pixel values across all acquired scenes in time range",
    },
    {
        "id": "min_cloud",
        "name": "Mosaic by Lowest Cloud Cover",
        "desc": "Orders collection by lowest cloud cover and layers top pixels (mosaic)",
    },
]


def mask_clouds(image, dataset_key):
    """Apply satellite-specific cloud and shadow masking."""
    import ee

    if dataset_key == "sentinel-2":
        # QA60 cloud bit mask & SCL surface classification
        qa = image.select("QA60")
        cloud_bit_mask = 1 << 10
        cirrus_bit_mask = 1 << 11
        mask = (
            qa.bitwiseAnd(cloud_bit_mask).eq(0)
            .And(qa.bitwiseAnd(cirrus_bit_mask).eq(0))
        )
        # SCL (Scene Classification Layer) cloud/shadow mask
        scl = image.select("SCL")
        # 1: defective, 3: cloud shadow, 8: cloud med, 9: cloud high, 10: cirrus, 11: snow
        scl_mask = (
            scl.neq(1)
            .And(scl.neq(3))
            .And(scl.neq(8))
            .And(scl.neq(9))
            .And(scl.neq(10))
            .And(scl.neq(11))
        )
        return image.updateMask(mask).updateMask(scl_mask)

    elif dataset_key in ("landsat-8", "landsat-9"):
        # Landsat Collection 2 QA_PIXEL mask
        qa = image.select("QA_PIXEL")
        # Bit 3 = Cloud, Bit 4 = Cloud Shadow, Bit 1 = Dilated Cloud
        dilated_cloud = 1 << 1
        cloud = 1 << 3
        cloud_shadow = 1 << 4
        mask = (
            qa.bitwiseAnd(dilated_cloud).eq(0)
            .And(qa.bitwiseAnd(cloud).eq(0))
            .And(qa.bitwiseAnd(cloud_shadow).eq(0))
        )
        # Scale factors for Landsat SR
        optical_bands = image.select("SR_B.").multiply(0.0000275).add(-0.2)
        return image.addBands(optical_bands, overwrite=True).updateMask(mask)

    return image


def prepare_visual_image(ee_image, dataset_key):
    """
    Format and scale Earth Engine image into a clean UInt8 (0-255) 3-band RGB image
    ready for export as standard GeoTIFF.
    """
    import ee

    ds_info = DATASETS[dataset_key]
    bands = ds_info["default_bands"]

    if dataset_key == "sentinel-2":
        # Scale 0 - 2500 (surface reflectance) to 0 - 255 UInt8
        rgb = ee_image.select(bands)
        scaled = rgb.divide(2500.0).multiply(255.0).clamp(0, 255).toByte()
        return scaled

    elif dataset_key in ("landsat-8", "landsat-9"):
        # Scale 0.0 - 0.3 surface reflectance to 0 - 255 UInt8
        rgb = ee_image.select(bands)
        scaled = rgb.divide(0.3).multiply(255.0).clamp(0, 255).toByte()
        return scaled

    elif dataset_key == "sentinel-1":
        # S1 SAR: bands VV and VH in dB (typically -25 to 0)
        # Create RGB false color composite: R = VV, G = VH, B = VV/VH ratio
        vv = ee_image.select("VV")
        vh = ee_image.select("VH")
        # Convert to linear power if in dB or clamp
        # Normalize VV (-25 to 0 dB) -> 0 to 255
        r = vv.add(25).divide(25).multiply(255).clamp(0, 255).toByte()
        g = vh.add(30).divide(30).multiply(255).clamp(0, 255).toByte()
        ratio = vv.subtract(vh).add(10).divide(20).multiply(255).clamp(0, 255).toByte()
        return ee.Image.cat([r, g, ratio]).rename(["B1", "B2", "B3"])

    elif dataset_key == "modis":
        rgb = ee_image.select(bands)
        scaled = rgb.divide(3000.0).multiply(255.0).clamp(0, 255).toByte()
        return scaled

    elif dataset_key == "dem-srtm":
        # Normalize elevation (0 to 3000m) to 0 - 255 grayscale (duplicated to 3 channels)
        elev = ee_image.select("elevation")
        scaled = elev.divide(3000.0).multiply(255.0).clamp(0, 255).toByte()
        return ee.Image.cat([scaled, scaled, scaled]).rename(["B1", "B2", "B3"])

    else:
        # Generic fallback
        selected = ee_image.select(bands[:3])
        return selected.clamp(0, 255).toByte()
