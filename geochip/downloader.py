import os
import sys
import json
import shutil
import argparse
import datetime
from pathlib import Path
from dotenv import load_dotenv
import requests
from tqdm import tqdm
import numpy as np
import rasterio
import shapefile

from .auth import init_earth_engine

# Load environment variables
load_dotenv()


def load_aoi_geometry(shp_path):
    """
    Read an ESRI Shapefile and convert its boundary polygon to ee.Geometry.Polygon.
    Returns:
        ee_polygon: Earth Engine geometry instance.
        points: List of [x, y] coordinates.
        bbox: Bounding box [xmin, ymin, xmax, ymax].
    """
    import ee

    if not os.path.exists(shp_path):
        # Fallback check for alternative standard directories
        alt_paths = [
            Path("data/aoi") / Path(shp_path).name,
            Path("AOI") / Path(shp_path).name,
        ]
        found = None
        for p in alt_paths:
            if p.exists():
                shp_path = str(p)
                found = True
                break
        if not found:
            raise FileNotFoundError(f"Shapefile '{shp_path}' not found!")

    sf = shapefile.Reader(shp_path)
    shapes = sf.shapes()
    if len(shapes) == 0:
        raise ValueError(f"Shapefile '{shp_path}' contains no geometry!")

    shape = shapes[0]
    points = [list(pt) for pt in shape.points]

    ee_polygon = ee.Geometry.Polygon([points])
    bbox = sf.bbox  # [xmin, ymin, xmax, ymax]

    print(f"[AOI] Loaded: {shp_path}")
    print(f"      Bounding Box: min({bbox[0]:.4f}, {bbox[1]:.4f}) -> max({bbox[2]:.4f}, {bbox[3]:.4f})")
    print(f"      Boundary Points: {len(points)}")

    return ee_polygon, points, bbox


def download_file(url, target_path, desc="Downloading"):
    """Download a file stream with a live progress bar."""
    response = requests.get(url, stream=True, timeout=600)
    response.raise_for_status()

    total_size = int(response.headers.get("content-length", 0))
    with open(target_path, "wb") as f, tqdm(
        desc=desc,
        total=total_size,
        unit="B",
        unit_scale=True,
        unit_divisor=1024,
    ) as bar:
        for chunk in response.iter_content(chunk_size=32768):
            if chunk:
                f.write(chunk)
                bar.update(len(chunk))


def mask_s2_clouds(image):
    """Cloud and cirrus masking function for Sentinel-2 Level-2A surface reflectance."""
    import ee

    qa = image.select("QA60")
    cloud_bit_mask = 1 << 10
    cirrus_bit_mask = 1 << 11
    mask = (
        qa.bitwiseAnd(cloud_bit_mask).eq(0)
        .And(qa.bitwiseAnd(cirrus_bit_mask).eq(0))
    )

    scl = image.select("SCL")
    # SCL flags: 1=defective, 3=shadow, 8=cloud med, 9=cloud high, 10=cirrus, 11=snow
    scl_mask = (
        scl.neq(1)
        .And(scl.neq(3))
        .And(scl.neq(8))
        .And(scl.neq(9))
        .And(scl.neq(10))
        .And(scl.neq(11))
    )

    return image.updateMask(mask).updateMask(scl_mask)


def process_sentinel2_mosaic(
    aoi_geom,
    output_path,
    mode="copernicus-q2",
    target_year=2025,
    target_date_str="2025-04-01",
    window_days=15,
    force=False
):
    """
    Generate Sentinel-2 True Color (Red B4, Green B3, Blue B2) directly from GEE:
    - 'copernicus-q2' : Official Copernicus Quarterly Mosaic algorithm (Q2: Apr-Jun, 25th percentile reducer)
    - 'annual'        : Full-year median composite
    - 'window'        : Target date range composite
    Exports an optimized UInt8 Byte GeoTIFF image (~1-3 MB).
    """
    import ee

    if not force and os.path.exists(output_path) and os.path.getsize(output_path) > 0:
        print(f"\n[S2] Output file '{output_path}' already exists ({os.path.getsize(output_path)/(1024*1024):.2f} MB). Skipping (Use --force to overwrite).")
        return

    print("\n" + "=" * 60)
    if mode in ["copernicus-q2", "quarterly"]:
        print(f"  PROCESSING SENTINEL-2 TRUE COLOR (COPERNICUS Q2: {target_year})")
        print("  Algorithm: 25th Percentile (First Quartile) - Identical to Copernicus Browser")
    elif mode == "annual":
        print(f"  PROCESSING SENTINEL-2 TRUE COLOR (ANNUAL FULL YEAR: {target_year})")
    else:
        print(f"  PROCESSING SENTINEL-2 TRUE COLOR ({target_date_str})")
    print("=" * 60)

    if mode in ["copernicus-q2", "quarterly"]:
        start_date_str = f"{target_year}-04-01"
        end_date_str = f"{target_year}-07-01"
        print(f"[S2] Mode: Copernicus Q2 ({start_date_str} to {end_date_str})...")
        s2_col = (
            ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
            .filterBounds(aoi_geom)
            .filterDate(start_date_str, end_date_str)
            .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", 70))
        )
    elif mode == "annual":
        start_date_str = f"{target_year}-01-01"
        end_date_str = f"{target_year + 1}-01-01"
        print(f"[S2] Mode: Annual ({start_date_str} to {end_date_str})...")
        s2_col = (
            ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
            .filterBounds(aoi_geom)
            .filterDate(start_date_str, end_date_str)
            .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", 70))
        )
    else:
        target_dt = datetime.datetime.strptime(target_date_str, "%Y-%m-%d")
        start_dt = target_dt - datetime.timedelta(days=window_days)
        end_dt = target_dt + datetime.timedelta(days=window_days)
        start_date_str = start_dt.strftime("%Y-%m-%d")
        end_date_str = end_dt.strftime("%Y-%m-%d")
        print(f"[S2] Mode: Date Window ({start_date_str} to {end_date_str}, ±{window_days} days)...")
        s2_col = (
            ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
            .filterBounds(aoi_geom)
            .filterDate(start_date_str, end_date_str)
            .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", 40))
        )

    count = s2_col.size().getInfo()
    print(f"[S2] Found {count} matching Sentinel-2 scenes.")

    if count == 0:
        print("[S2] Warning: No scenes met cloud cover filter. Expanding search without cloud filter...")
        s2_col = (
            ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
            .filterBounds(aoi_geom)
            .filterDate(start_date_str, end_date_str)
        )
        count = s2_col.size().getInfo()
        print(f"[S2] Found {count} scenes after relaxing cloud filter.")

    if count == 0:
        raise RuntimeError(f"No Sentinel-2 scenes found for date range {start_date_str} - {end_date_str}")

    rgb_bands = ["B4", "B3", "B2"]

    # Reducer: 25th percentile for Copernicus Q2, median for other modes
    if mode in ["copernicus-q2", "quarterly"]:
        composite = (
            s2_col.map(mask_s2_clouds)
            .select(rgb_bands)
            .reduce(ee.Reducer.percentile([25]))
            .rename(rgb_bands)
            .clip(aoi_geom)
        )
    else:
        composite = (
            s2_col.map(mask_s2_clouds)
            .select(rgb_bands)
            .median()
            .clip(aoi_geom)
        )

    # Apply standard Copernicus visual contrast stretch (0 - 2500 to 0 - 255 Byte) directly in GEE
    true_color_byte = (
        composite.select(rgb_bands)
        .divide(2500.0)
        .multiply(255.0)
        .clamp(0, 255)
        .toByte()
    )

    print("[S2] Generating direct download URL (B4/B3/B2, Scale: 10m)...")
    coords = aoi_geom.coordinates().getInfo()

    download_params = {
        "scale": 10,
        "crs": "EPSG:4326",
        "region": coords,
        "format": "GEO_TIFF"
    }

    url = true_color_byte.getDownloadURL(download_params)
    print(f"[S2] Download URL ready. Saving True Color GeoTIFF to: {output_path}...")
    download_file(url, output_path, desc=f"Sentinel-2 True Color {target_year} ({mode})")

    # Set band descriptions
    try:
        with rasterio.open(output_path, "r+") as dst:
            dst.set_band_description(1, "Red (B4)")
            dst.set_band_description(2, "Green (B3)")
            dst.set_band_description(3, "Blue (B2)")
    except Exception:
        pass

    print(f"[S2] [SUCCESS] Sentinel-2 True Color saved to: {output_path}")


def process_satellite_embeddings(aoi_geom, output_path, bbox=None, target_year=2025, force=False):
    """
    Download Google Satellite Embeddings (AlphaEarth 64-dimensional, 10m)
    using Float32 casting and adaptive band-chunking to bypass GEE 48MB quota limit.
    """
    import ee

    if not force and os.path.exists(output_path) and os.path.getsize(output_path) > 0:
        print(f"\n[GSE] Output file '{output_path}' already exists ({os.path.getsize(output_path)/(1024*1024):.2f} MB). Skipping (Use --force to overwrite).")
        return

    print("\n" + "=" * 60)
    print("  PROCESSING GOOGLE SATELLITE EMBEDDINGS (GSE)")
    print("=" * 60)

    dataset = ee.ImageCollection("GOOGLE/SATELLITE_EMBEDDING/V1/ANNUAL").filterBounds(aoi_geom)

    # Check availability of requested year
    filter_start = f"{target_year}-01-01"
    filter_end = f"{target_year + 1}-01-01"
    year_col = dataset.filterDate(filter_start, filter_end)
    year_count = year_col.size().getInfo()

    if year_count > 0:
        # Cast to Float32 to cut memory bandwidth in half compared to internal Double (Float64)
        gse_img = year_col.first().clip(aoi_geom).toFloat()
        actual_year = target_year
        print(f"[GSE] Using dataset for year {actual_year}.")
    else:
        print(f"[GSE] Note: Year {target_year} not yet published in annual GEE catalog.")
        latest_img = dataset.sort("system:time_start", False).first()
        gse_img = latest_img.clip(aoi_geom).toFloat()
        time_ms = latest_img.get("system:time_start").getInfo()
        if time_ms:
            actual_year = datetime.datetime.fromtimestamp(time_ms / 1000, tz=datetime.timezone.utc).year
        else:
            actual_year = "Latest Available"
        print(f"[GSE] Using latest available embedding dataset (Year: {actual_year}).")

    all_bands = gse_img.bandNames().getInfo()
    print(f"[GSE] Identified {len(all_bands)} bands: {all_bands[0]} through {all_bands[-1]}")
    coords = aoi_geom.coordinates().getInfo()

    # Estimate raster dimensions to determine adaptive chunk size
    if bbox:
        min_lon, min_lat, max_lon, max_lat = bbox
        width_deg = abs(max_lon - min_lon)
        height_deg = abs(max_lat - min_lat)
        mid_lat = (min_lat + max_lat) / 2.0
        width_px = int((width_deg * 111320.0 * np.cos(np.radians(mid_lat))) / 10.0)
        height_px = int((height_deg * 110574.0) / 10.0)
        est_pixels = max(1, width_px * height_px)
    else:
        width_px, height_px = 1500, 1500
        est_pixels = 2_250_000

    # 1 band float32 = 4 bytes. GEE hard download quota is 50,331,648 bytes (~48 MB).
    # Use a conservative target limit of 22 MB per chunk request
    bytes_per_band = est_pixels * 4
    safe_target_bytes = 22 * 1024 * 1024
    chunk_size = max(1, min(8, int(safe_target_bytes / max(1, bytes_per_band))))

    chunk_ranges = [all_bands[i : i + chunk_size] for i in range(0, len(all_bands), chunk_size)]
    num_chunks = len(chunk_ranges)

    temp_dir = Path(output_path).parent / ".temp_gse_chunks"
    temp_dir.mkdir(parents=True, exist_ok=True)

    print(f"[GSE] Estimated raster dimensions: ~{height_px} x {width_px} pixels (~{est_pixels:,} total pixels).")
    print(f"[GSE] Downloading {len(all_bands)} bands across {num_chunks} chunks ({chunk_size} bands/chunk, ~{chunk_size * bytes_per_band / (1024*1024):.1f} MB/chunk)...")

    chunk_files = []
    try:
        for idx, chunk_band_names in enumerate(chunk_ranges):
            chunk_filename = temp_dir / f"chunk_{idx:03d}.tif"
            chunk_files.append(chunk_filename)

            if chunk_filename.exists() and chunk_filename.stat().st_size > 0:
                print(f"[GSE] Chunk {idx+1}/{num_chunks} ({chunk_band_names[0]}-{chunk_band_names[-1]}) retrieved from cache.")
                continue

            sub_img = gse_img.select(chunk_band_names)
            download_params = {
                "scale": 10,
                "crs": "EPSG:4326",
                "region": coords,
                "format": "GEO_TIFF"
            }
            try:
                url = sub_img.getDownloadURL(download_params)
                download_file(url, str(chunk_filename), desc=f"GSE Chunk {idx+1}/{num_chunks}")
            except Exception as e:
                # Automatic single-band fallback if request exceeds quota limit
                if "must be less than or equal to" in str(e) and len(chunk_band_names) > 1:
                    print(f"\n[GSE] Warning: Chunk {idx+1} exceeded quota limit ({e}). Falling back to 1 band per download...")
                    sub_files = []
                    for b_name in chunk_band_names:
                        single_img = gse_img.select([b_name])
                        single_url = single_img.getDownloadURL(download_params)
                        sub_file = temp_dir / f"sub_{b_name}.tif"
                        download_file(single_url, str(sub_file), desc=f"GSE {b_name}")
                        sub_files.append(sub_file)

                    sub_arrays = []
                    sub_profile = None
                    for sf in sub_files:
                        with rasterio.open(sf) as s_src:
                            if sub_profile is None:
                                sub_profile = s_src.profile.copy()
                            sub_arrays.append(s_src.read())
                        try:
                            sf.unlink(missing_ok=True)
                        except Exception:
                            pass
                    sub_merged = np.concatenate(sub_arrays, axis=0)
                    sub_profile.update(count=len(chunk_band_names), dtype="float32", compress="lzw")
                    with rasterio.open(chunk_filename, "w", **sub_profile) as s_dst:
                        s_dst.write(sub_merged)
                else:
                    raise e

        print(f"\n[GSE] All chunks downloaded. Merging {len(all_bands)} bands into unified GeoTIFF with LZW compression...")

        profile = None
        arrays = []
        for cf in chunk_files:
            with rasterio.open(cf) as src:
                if profile is None:
                    profile = src.profile.copy()
                arrays.append(src.read())

        full_data = np.concatenate(arrays, axis=0)  # Shape: (bands, Height, Width)

        profile.update(
            count=len(all_bands),
            dtype="float32",
            driver="GTiff",
            compress="lzw",
            nodata=None
        )

        with rasterio.open(output_path, "w", **profile) as dst:
            dst.write(full_data)
            for b_idx in range(len(all_bands)):
                dst.set_band_description(b_idx + 1, all_bands[b_idx])

        print(f"[GSE] [SUCCESS] Google Satellite Embeddings saved to: {output_path}")
        print(f"      Dimensions: {full_data.shape[1]} x {full_data.shape[2]} pixels, {len(all_bands)} bands (Float32)")

    finally:
        # Clean temporary chunk cache
        if temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)
            print("[GSE] Temporary chunk cache cleaned.")


def main():
    parser = argparse.ArgumentParser(description="Download Sentinel-2 Mosaic & Google Satellite Embeddings via GEE")
    parser.add_argument("--aoi", type=str, default="data/aoi/AOI-1.shp", help="Path to AOI shapefile (e.g. data/aoi/AOI-1.shp)")
    parser.add_argument("--mode", type=str, choices=["copernicus-q2", "annual", "window"], default="copernicus-q2", help="Sentinel-2 composite mode: 'copernicus-q2' (default), 'annual', or 'window'")
    parser.add_argument("--year", type=int, default=2025, help="Target data year (default: 2025)")
    parser.add_argument("--date", type=str, default="2025-04-01", help="Target date for window mode (YYYY-MM-DD)")
    parser.add_argument("--window", type=int, default=15, help="Day window around target date (default: 15)")
    parser.add_argument("--output-dir", type=str, default="data/raw", help="Target directory for downloaded rasters (default: data/raw)")
    parser.add_argument("--s2-name", type=str, default=None, help="Custom filename for Sentinel-2 True Color GeoTIFF")
    parser.add_argument("--gse-name", type=str, default=None, help="Custom filename for GSE GeoTIFF")
    parser.add_argument("--force", action="store_true", help="Force re-download of both datasets")
    parser.add_argument("--force-s2", action="store_true", help="Force re-download of Sentinel-2 only")
    parser.add_argument("--force-gse", action="store_true", help="Force re-download of GSE only")
    args = parser.parse_args()

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    aoi_stem = Path(args.aoi).stem  # e.g., 'AOI-1'

    # Determine output filenames
    if args.s2_name:
        s2_base = args.s2_name[:-4] if args.s2_name.endswith(".tif") else args.s2_name
        s2_name = f"{s2_base}.tif" if s2_base.endswith("_TrueColor") else f"{s2_base}_TrueColor.tif"
    else:
        s2_name = f"Sentinel2M-{args.year}-{aoi_stem}_TrueColor.tif"

    if args.gse_name:
        gse_base = args.gse_name[:-4] if args.gse_name.endswith(".tif") else args.gse_name
        gse_name = f"{gse_base}.tif"
    else:
        gse_name = f"GSE-{args.year}-{aoi_stem}.tif"

    s2_output_path = out_dir / s2_name
    gse_output_path = out_dir / gse_name

    # Initialize GEE
    init_earth_engine()

    # Load AOI boundary geometry
    aoi_geom, _, aoi_bbox = load_aoi_geometry(args.aoi)

    # 1. Download Sentinel-2
    process_sentinel2_mosaic(
        aoi_geom=aoi_geom,
        output_path=str(s2_output_path),
        mode=args.mode,
        target_year=args.year,
        target_date_str=args.date,
        window_days=args.window,
        force=(args.force or args.force_s2)
    )

    # 2. Download Google Satellite Embeddings
    process_satellite_embeddings(
        aoi_geom=aoi_geom,
        output_path=str(gse_output_path),
        bbox=aoi_bbox,
        target_year=args.year,
        force=(args.force or args.force_gse)
    )

    print("\n" + "=" * 60)
    print("  DOWNLOAD STAGE COMPLETED SUCCESSFULLY!")
    print(f"  1. Sentinel-2: {s2_output_path}")
    print(f"  2. GSE:        {gse_output_path}")
    print("=" * 60)


if __name__ == "__main__":
    main()
