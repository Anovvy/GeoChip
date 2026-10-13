import os
import sys
import json
import argparse
from pathlib import Path
import numpy as np
import rasterio
from PIL import Image
from sklearn.decomposition import PCA


def generate_gse_rgb(gse_data, valid_mask):
    """
    Convert 64-dimensional Google Satellite Embeddings into a 3-channel RGB image
    using Principal Component Analysis (PCA) and 2-98% percentile contrast stretching.
    """
    C, H, W = gse_data.shape
    finite_mask = valid_mask & np.isfinite(gse_data).all(axis=0)

    # Extract valid pixel vectors
    X_valid = gse_data[:, finite_mask].T  # Shape: (N_valid, 64)

    # Fit 3-component PCA
    pca = PCA(n_components=3)
    pca_features = pca.fit_transform(X_valid)

    # Normalize each component to 0 - 255 (uint8) using 2nd - 98th percentile stretch
    gse_rgb = np.zeros((H, W, 3), dtype=np.uint8)
    for b in range(3):
        comp = pca_features[:, b]
        p2, p98 = np.percentile(comp, (2, 98))
        norm = np.clip((comp - p2) / (p98 - p2 + 1e-6) * 255.0, 0, 255).astype(np.uint8)
        gse_rgb[finite_mask, b] = norm

    return gse_rgb, pca


def locate_input_rasters(aoi_name, s2_path=None, gse_path=None):
    """Locate Sentinel-2 and GSE GeoTIFFs across standard directories."""
    # Look for Sentinel-2
    if s2_path is None or not os.path.exists(s2_path):
        candidate_s2 = [
            f"data/raw/Sentinel2M-2025-{aoi_name}_TrueColor.tif",
            f"RAW Data/Sentinel2M-2025-{aoi_name}_TrueColor.tif",
            f"data/raw/Sentinel2M-2025-{aoi_name}.tif",
            f"RAW Data/Sentinel2M-2025-{aoi_name}.tif",
        ]
        for c in candidate_s2:
            if os.path.exists(c):
                s2_path = c
                break

    # Look for GSE
    if gse_path is None or not os.path.exists(gse_path):
        candidate_gse = [
            f"data/raw/GSE-2025-{aoi_name}.tif",
            f"RAW Data/GSE-2025-{aoi_name}.tif",
        ]
        for c in candidate_gse:
            if os.path.exists(c):
                gse_path = c
                break

    if not s2_path or not os.path.exists(s2_path):
        raise FileNotFoundError(f"Sentinel-2 GeoTIFF for '{aoi_name}' not found. Please run the download step first.")

    if not gse_path or not os.path.exists(gse_path):
        raise FileNotFoundError(f"Google Satellite Embeddings GeoTIFF for '{aoi_name}' not found. Please run the download step first.")

    return s2_path, gse_path


def create_paired_chips(
    aoi_name="AOI-1",
    s2_path=None,
    gse_path=None,
    output_base="data/chips",
    chip_size=160,
    chips_per_task=5,
    save_raw_gse_npy=True,
    min_valid_ratio=0.70
):
    """
    Generate paired chips (160x160 px) from Sentinel-2 and GSE rasters,
    grouped into task batches (e.g. 5 chips per task) with georeferenced manifest.json.
    """
    s2_path, gse_path = locate_input_rasters(aoi_name, s2_path, gse_path)

    print("=" * 60)
    print(f"  PAIRED CHIPPING ENGINE ({aoi_name})")
    print(f"  Chip Size: {chip_size}x{chip_size} px | Chips per Task: {chips_per_task}")
    print(f"  Sentinel: {s2_path}")
    print(f"  GSE:      {gse_path}")
    print("=" * 60)

    print(f"[LOAD] Reading Sentinel-2 raster: {s2_path}")
    with rasterio.open(s2_path) as src_s2:
        s2_transform = src_s2.transform
        s2_crs = src_s2.crs
        s2_data = src_s2.read()  # Shape: (C, H, W)

    print(f"[LOAD] Reading GSE raster:        {gse_path}")
    with rasterio.open(gse_path) as src_gse:
        gse_data = src_gse.read()  # Shape: (64, H, W)

    # Format Sentinel-2 RGB array (uint8)
    if s2_data.shape[0] == 3 and s2_data.dtype == np.uint8:
        s2_rgb = np.transpose(s2_data, (1, 2, 0))  # Shape: (H, W, 3)
    elif s2_data.shape[0] >= 3:
        r = s2_data[2].astype(np.float32)
        g = s2_data[1].astype(np.float32)
        b = s2_data[0].astype(np.float32)

        def stretch(band):
            return np.clip((band / 2500.0) * 255.0, 0, 255).astype(np.uint8)

        s2_rgb = np.stack([stretch(r), stretch(g), stretch(b)], axis=-1)
    else:
        raise ValueError("Unsupported Sentinel-2 raster channel format!")

    H, W, _ = s2_rgb.shape
    s2_valid = np.any(s2_rgb > 0, axis=-1)
    gse_valid = np.isfinite(gse_data).all(axis=0)
    valid_both = s2_valid & gse_valid

    print("[GSE] Computing 3-component PCA for visual GSE preview...")
    gse_rgb, pca = generate_gse_rgb(gse_data, valid_both)

    n_rows = H // chip_size
    n_cols = W // chip_size
    total_grid_cells = n_rows * n_cols
    print(f"[GRID] Image grid: {n_rows} rows x {n_cols} columns ({total_grid_cells} potential chips).")

    out_aoi_dir = Path(output_base) / aoi_name
    out_aoi_dir.mkdir(parents=True, exist_ok=True)

    sentinel_base = out_aoi_dir / "Sentinel"
    gse_base = out_aoi_dir / "GSE"

    manifest = []
    chip_counter = 0

    for r in range(n_rows):
        for c in range(n_cols):
            r_start = r * chip_size
            r_end = r_start + chip_size
            c_start = c * chip_size
            c_end = c_start + chip_size

            # Check valid pixel coverage ratio
            cell_valid = valid_both[r_start:r_end, c_start:c_end]
            if np.mean(cell_valid) < min_valid_ratio:
                continue

            chip_counter += 1
            task_num = (chip_counter - 1) // chips_per_task + 1
            task_name = f"task{task_num}-{aoi_name}"
            chip_name = f"chip_{chip_counter:03d}.png"

            # Task output directories
            task_s2_dir = sentinel_base / task_name
            task_gse_dir = gse_base / task_name
            task_s2_dir.mkdir(parents=True, exist_ok=True)
            task_gse_dir.mkdir(parents=True, exist_ok=True)

            # Crop Sentinel-2 chip and save PNG
            s2_chip = s2_rgb[r_start:r_end, c_start:c_end]
            Image.fromarray(s2_chip).save(task_s2_dir / chip_name)

            # Crop GSE PCA RGB chip and save PNG
            gse_chip_rgb = gse_rgb[r_start:r_end, c_start:c_end]
            Image.fromarray(gse_chip_rgb).save(task_gse_dir / chip_name)

            # Save raw 64-band embedding as .npy if requested
            if save_raw_gse_npy:
                gse_chip_raw = gse_data[:, r_start:r_end, c_start:c_end]
                np.save(task_gse_dir / f"chip_{chip_counter:03d}.npy", gse_chip_raw)

            # Compute geographic bounding box coordinates
            top_left_x, top_left_y = s2_transform * (c_start, r_start)
            bottom_right_x, bottom_right_y = s2_transform * (c_end, r_end)

            manifest_item = {
                "chip_id": chip_counter,
                "chip_name": chip_name,
                "task_name": task_name,
                "aoi": aoi_name,
                "row_start": int(r_start),
                "col_start": int(c_start),
                "chip_size": int(chip_size),
                "bbox_geo": [
                    float(min(top_left_x, bottom_right_x)),
                    float(min(top_left_y, bottom_right_y)),
                    float(max(top_left_x, bottom_right_x)),
                    float(max(top_left_y, bottom_right_y)),
                ],
                "sentinel_path": str((Path(aoi_name) / "Sentinel" / task_name / chip_name)),
                "gse_path": str((Path(aoi_name) / "GSE" / task_name / chip_name)),
            }
            manifest.append(manifest_item)

    # Save manifest.json
    manifest_path = out_aoi_dir / "manifest.json"
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)

    total_tasks = (chip_counter + chips_per_task - 1) // chips_per_task
    print("\n" + "=" * 60)
    print("  CHIPPING STAGE COMPLETED!")
    print(f"  Valid Chips Generated: {chip_counter}")
    print(f"  Total Task Batches:   {total_tasks}")
    print(f"  Output Directory:     {out_aoi_dir}")
    print(f"  Manifest Metadata:    {manifest_path}")
    print("=" * 60)

    return manifest


def main():
    parser = argparse.ArgumentParser(description="Create Paired Chips for Sentinel-2 & GSE")
    parser.add_argument("--aoi", type=str, default="AOI-1", help="AOI identifier name (e.g. AOI-1, AOI-2)")
    parser.add_argument("--s2-path", type=str, default=None, help="Explicit path to Sentinel-2 True Color GeoTIFF")
    parser.add_argument("--gse-path", type=str, default=None, help="Explicit path to GSE GeoTIFF")
    parser.add_argument("--output-base", type=str, default="data/chips", help="Root directory for chips (default: data/chips)")
    parser.add_argument("--chip-size", type=int, default=160, help="Tile dimensions in pixels (default: 160)")
    parser.add_argument("--chips-per-task", type=int, default=5, help="Number of chips per task batch (default: 5)")
    parser.add_argument("--no-raw-npy", action="store_true", help="Disable saving raw 64-band GSE .npy arrays")
    args = parser.parse_args()

    create_paired_chips(
        aoi_name=args.aoi,
        s2_path=args.s2_path,
        gse_path=args.gse_path,
        output_base=args.output_base,
        chip_size=args.chip_size,
        chips_per_task=args.chips_per_task,
        save_raw_gse_npy=not args.no_raw_npy,
    )


if __name__ == "__main__":
    main()
