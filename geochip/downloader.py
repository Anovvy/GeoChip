"""
GeoChip Satellite Downloader Engine.
Interactive search, cloud filtering, scene listing, compositing, and downloading from Google Earth Engine.
"""

import os
import sys
import datetime
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from .auth import init_earth_engine, login_flow
from .datasets import DATASETS, COMPOSITE_METHODS, mask_clouds, prepare_visual_image
from .ui import (
    select,
    prompt_input,
    prompt_number,
    print_step,
    print_success,
    print_error,
    print_warning,
    print_info,
)


def list_available_aois(aoi_dir="data/aoi"):
    """Scan and list all ESRI Shapefiles in the AOI directory."""
    dir_path = Path(aoi_dir)
    if not dir_path.exists():
        dir_path.mkdir(parents=True, exist_ok=True)
        return []
    return sorted(list(dir_path.glob("*.shp")))


def load_aoi_geometry(shp_path):
    """
    Read an ESRI Shapefile and convert its boundary polygon to ee.Geometry.Polygon.
    Returns:
        ee_polygon: Earth Engine geometry instance.
        points: List of [x, y] coordinates.
        bbox: Bounding box [xmin, ymin, xmax, ymax].
    """
    import ee
    import shapefile

    shp_path = str(shp_path)
    if not os.path.exists(shp_path):
        raise FileNotFoundError(f"Shapefile '{shp_path}' not found!")

    sf = shapefile.Reader(shp_path)
    shapes = sf.shapes()
    if len(shapes) == 0:
        raise ValueError(f"Shapefile '{shp_path}' contains no geometry!")

    shape = shapes[0]
    points = [list(pt) for pt in shape.points]

    ee_polygon = ee.Geometry.Polygon([points])
    bbox = sf.bbox  # [xmin, ymin, xmax, ymax]
    return ee_polygon, points, bbox


def download_stream(url, target_path, desc="Downloading Raster"):
    """Stream download a file with live progress bar."""
    import requests
    from tqdm import tqdm

    response = requests.get(url, stream=True, timeout=900)
    response.raise_for_status()

    total_size = int(response.headers.get("content-length", 0))
    with open(target_path, "wb") as f, tqdm(
        desc=desc,
        total=total_size,
        unit="B",
        unit_scale=True,
        unit_divisor=1024,
    ) as bar:
        for chunk in response.iter_content(chunk_size=65536):
            if chunk:
                f.write(chunk)
                bar.update(len(chunk))


def fetch_scenes_list(collection_id, aoi_geom, start_date, end_date, cloud_prop=None, max_cloud=100):
    """
    Query Earth Engine ImageCollection and return a list of matching scenes metadata.
    """
    import ee

    col = (
        ee.ImageCollection(collection_id)
        .filterBounds(aoi_geom)
        .filterDate(start_date, end_date)
    )

    if cloud_prop:
        col = col.filter(ee.Filter.lte(cloud_prop, max_cloud))

    # Fetch metadata (id, date, cloud)
    count = col.size().getInfo()
    if count == 0:
        return col, []

    # Limit metadata fetch to first 50 scenes to keep CLI responsive
    sample_col = col.sort("system:time_start", False).limit(50)
    features = sample_col.getInfo().get("features", [])

    scenes = []
    for f in features:
        props = f.get("properties", {})
        scene_id = f.get("id", "Unknown")
        time_millis = props.get("system:time_start")
        if time_millis:
            date_str = datetime.datetime.fromtimestamp(time_millis / 1000.0, tz=datetime.timezone.utc).strftime("%Y-%m-%d %H:%M")
        else:
            date_str = "N/A"

        cloud_val = props.get(cloud_prop) if cloud_prop else None
        scenes.append({
            "id": scene_id,
            "short_id": scene_id.split("/")[-1],
            "date": date_str,
            "cloud": f"{cloud_val:.1f}%" if cloud_val is not None else "N/A",
            "cloud_num": cloud_val if cloud_val is not None else 0.0,
        })

    return col, scenes


def interactive_download_workflow():
    """
    Interactive Step 1: Download Satellite Imagery from Google Earth Engine.
    """
    print_step("Step 1: Download Satellite Imagery (Earth Engine)")

    # 1. Check Authentication
    if not init_earth_engine():
        print_warning("Earth Engine is not authenticated. Initiating login...")
        if not login_flow():
            print_error("Authentication failed. Please run 'python auth_setup.py --login'")
            return None

    import ee

    # 2. Select AOI
    print_info("Scanning AOI shapefiles in 'data/aoi'...")
    aoi_files = list_available_aois()
    if not aoi_files:
        print_error("No ESRI Shapefiles (.shp) found in 'data/aoi/'!")
        print_info("Please place your AOI shapefile in 'data/aoi/' before proceeding.")
        return None

    aoi_choices = [{"name": f.name, "desc": f"Size: {f.stat().st_size} bytes"} for f in aoi_files]
    aoi_idx = select("Select Area of Interest (AOI):", aoi_choices)
    selected_aoi_path = aoi_files[aoi_idx]
    aoi_name = selected_aoi_path.stem

    print_info(f"Loading geometry from {selected_aoi_path.name}...")
    aoi_geom, _, bbox = load_aoi_geometry(selected_aoi_path)
    print_success(f"AOI '{aoi_name}' successfully loaded (BBox: {bbox[0]:.4f}, {bbox[1]:.4f} to {bbox[2]:.4f}, {bbox[3]:.4f})")

    # 3. Select Dataset
    ds_keys = list(DATASETS.keys())
    ds_choices = [
        {"name": f"{DATASETS[k]['name']}", "desc": DATASETS[k]["desc"]}
        for k in ds_keys
    ]
    ds_idx = select("Select Satellite / Earth Observation Dataset:", ds_choices)
    dataset_key = ds_keys[ds_idx]
    ds_info = DATASETS[dataset_key]
    print_success(f"Selected dataset: {ds_info['name']}")

    # 4. Date Range
    today = datetime.date.today()
    default_end = today.strftime("%Y-%m-%d")
    default_start = (today - datetime.timedelta(days=90)).strftime("%Y-%m-%d")

    start_date = prompt_input("Enter Start Date (YYYY-MM-DD)", default=default_start)
    end_date = prompt_input("Enter End Date (YYYY-MM-DD)", default=default_end)

    # 5. Cloud Cover Percentage Filter
    max_cloud = 100.0
    if ds_info["type"] == "optical" and ds_info["cloud_prop"]:
        max_cloud = prompt_number(
            "Maximum Cloud Cover Percentage Threshold (%) [0 - 100]",
            default=20.0,
            min_val=0.0,
            max_val=100.0,
            is_float=True
        )
        print_info(f"Filtering optical scenes with cloud cover <= {max_cloud}%")
    elif ds_info["type"] == "radar":
        print_info("Radar satellites (Sentinel-1 SAR) operate day/night and penetrate clouds. Cloud filter skipped.")
    elif ds_info["type"] == "dem":
        print_info("Digital Elevation Model (DEM) is a static global elevation dataset. Cloud filter skipped.")

    # 6. Query Earth Engine Catalog
    print_info(f"Querying Earth Engine catalog ({ds_info['id']})...")
    try:
        col, scenes = fetch_scenes_list(
            collection_id=ds_info["id"],
            aoi_geom=aoi_geom,
            start_date=start_date,
            end_date=end_date,
            cloud_prop=ds_info["cloud_prop"],
            max_cloud=max_cloud,
        )
    except Exception as e:
        print_error(f"Failed to query Earth Engine: {e}")
        return None

    total_scenes = len(scenes)
    if total_scenes == 0:
        print_warning("No scenes found matching the specified date range and cloud filter in this AOI.")
        print_info("Tip: Expand the date range or increase the cloud cover percentage threshold.")
        return None

    print_success(f"Found {total_scenes} matching scene(s)!\n")

    # 7. Scene Listing & Ingestion Mode Selection
    menu_choices = []
    menu_choices.append({
        "name": f"✨ COMPOSITE ALL SCENES ({total_scenes} acquisitions merged)",
        "desc": "Merge all scenes with a reducer to generate a clean cloud-free mosaic",
        "action": "composite"
    })
    for idx, s in enumerate(scenes):
        cloud_label = f" | Cloud: {s['cloud']}" if s['cloud'] != "N/A" else ""
        menu_choices.append({
            "name": f"📷 Scene #{idx+1}: {s['short_id']} ({s['date']}{cloud_label})",
            "desc": f"Full ID: {s['id']}",
            "action": "single",
            "scene": s
        })

    choice_idx = select(
        "Select Ingestion Mode (Single Scene or Full Composite):",
        menu_choices,
        default_index=0
    )
    chosen_item = menu_choices[choice_idx]

    # 8. Process Image
    out_dir = Path("data/raw")
    out_dir.mkdir(parents=True, exist_ok=True)

    if chosen_item["action"] == "composite":
        comp_idx = select(
            "Select Compositing Reducer Method:",
            [{"name": m["name"], "desc": m["desc"]} for m in COMPOSITE_METHODS],
            default_index=0
        )
        comp_method = COMPOSITE_METHODS[comp_idx]["id"]
        print_info(f"Compositing with method: {COMPOSITE_METHODS[comp_idx]['name']}...")

        # Apply cloud mask on collection
        masked_col = col.map(lambda img: mask_clouds(img, dataset_key))

        if comp_method == "median":
            final_img = masked_col.median()
        elif comp_method == "q25":
            final_img = masked_col.reduce(ee.Reducer.percentile([25]))
        elif comp_method == "mean":
            final_img = masked_col.mean()
        elif comp_method == "min_cloud" and ds_info["cloud_prop"]:
            final_img = col.sort(ds_info["cloud_prop"]).first()
        else:
            final_img = masked_col.median()

        output_filename = f"{dataset_key}_{aoi_name}_{start_date}_{end_date}_{comp_method}.tif"

    else:
        # Download Single Scene
        chosen_scene = chosen_item["scene"]
        scene_id = chosen_scene["id"]
        print_info(f"Processing single scene: {scene_id}...")
        single_img = ee.Image(scene_id)
        final_img = mask_clouds(single_img, dataset_key)
        date_clean = chosen_scene['date'].split(" ")[0].replace("-", "")
        output_filename = f"{dataset_key}_{aoi_name}_{date_clean}_{chosen_scene['short_id']}.tif"

    output_path = out_dir / output_filename

    # 9. Format visualization UInt8 GeoTIFF
    print_info("Preparing True Color UInt8 GeoTIFF visualization...")
    vis_img = prepare_visual_image(final_img, dataset_key).clip(aoi_geom)

    # 10. Generate Download URL & Stream
    print_info("Generating direct download URL from Earth Engine...")
    try:
        url = vis_img.getDownloadURL({
            "scale": ds_info["scale"],
            "crs": "EPSG:4326",
            "region": aoi_geom,
            "format": "GEO_TIFF",
        })
    except Exception as e:
        print_error(f"Failed to generate download URL from Earth Engine: {e}")
        print_warning("The requested raster may exceed the 48 MB direct download quota. Consider a smaller AOI.")
        return None

    print_info(f"Saving file to: {output_path}")
    download_stream(url, str(output_path), desc=f"Downloading {output_filename}")

    print_success(f"Successfully downloaded raster! Saved to: {output_path}")
    print_info(f"File size: {output_path.stat().st_size / (1024 * 1024):.2f} MB")

    return str(output_path)


def main():
    """CLI entry point for downloader."""
    import argparse
    parser = argparse.ArgumentParser(description="GeoChip Satellite Downloader")
    parser.add_argument("--interactive", action="store_true", help="Launch interactive UI mode")
    parser.add_argument("--aoi", type=str, default=None, help="Path to AOI shapefile")
    args = parser.parse_args()

    # Always default to interactive if no specific args given
    interactive_download_workflow()


if __name__ == "__main__":
    main()
