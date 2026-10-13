"""
GeoChip Tiling & Chipping Engine.
Slices single raw satellite GeoTIFF rasters into configurable tiles (160, 320, 640, 1280 px),
organizes into task batches, generates georeferenced manifest.json, and connects to Roboflow.
"""

import os
import sys
import json
from pathlib import Path
import numpy as np

from .ui import (
    select,
    prompt_number,
    prompt_confirm,
    print_step,
    print_success,
    print_error,
    print_warning,
    print_info,
)


CHIP_SIZES = [
    {"name": "160 x 160 px", "size": 160, "desc": "Ukuran standar deteksi objek kecil (Sentinel-2 10m / drone)"},
    {"name": "320 x 320 px", "size": 320, "desc": "Ukuran ideal resolusi menengah (YOLOv8 / Faster-RCNN)"},
    {"name": "640 x 640 px", "size": 640, "desc": "Ukuran standar Roboflow & YOLO default (Area cakupan luas)"},
    {"name": "1280 x 1280 px", "size": 1280, "desc": "Ukuran resolusi tinggi / konteks spasial sangat luas"},
]


def list_available_raw_rasters(raw_dir="data/raw"):
    """List all GeoTIFF files available in data/raw."""
    dir_path = Path(raw_dir)
    if not dir_path.exists():
        dir_path.mkdir(parents=True, exist_ok=True)
        return []
    return sorted(list(dir_path.glob("*.tif")) + list(dir_path.glob("*.tiff")))


def format_raster_to_rgb(data):
    """
    Convert raw raster array (C, H, W) to (H, W, 3) uint8 RGB image.
    Handles 3-band, multi-band, or single-band (SAR / DEM).
    """
    C, H, W = data.shape
    if C >= 3:
        # If already uint8
        if data.dtype == np.uint8:
            return np.transpose(data[:3], (1, 2, 0))
        # If float or uint16, stretch each channel to 0-255
        rgb = np.zeros((H, W, 3), dtype=np.uint8)
        for i in range(3):
            band = data[i].astype(np.float32)
            finite_mask = np.isfinite(band)
            if not np.any(finite_mask):
                continue
            p2, p98 = np.percentile(band[finite_mask], (2, 98))
            if p98 > p2:
                norm = np.clip((band - p2) / (p98 - p2) * 255.0, 0, 255).astype(np.uint8)
            else:
                norm = np.clip(band, 0, 255).astype(np.uint8)
            rgb[:, :, i] = norm
        return rgb

    elif C == 1:
        # Single band: duplicate to 3 channels (grayscale)
        band = data[0].astype(np.float32)
        if data.dtype == np.uint8:
            norm = data[0]
        else:
            finite_mask = np.isfinite(band)
            if np.any(finite_mask):
                p2, p98 = np.percentile(band[finite_mask], (2, 98))
                if p98 > p2:
                    norm = np.clip((band - p2) / (p98 - p2) * 255.0, 0, 255).astype(np.uint8)
                else:
                    norm = np.clip(band, 0, 255).astype(np.uint8)
            else:
                norm = np.zeros((H, W), dtype=np.uint8)
        return np.stack([norm, norm, norm], axis=-1)

    elif C == 2:
        # 2 bands (e.g. SAR VV & VH)
        b1 = data[0].astype(np.float32)
        b2 = data[1].astype(np.float32)
        b3 = (b1 + b2) / 2.0
        stacked = np.stack([b1, b2, b3], axis=0)
        return format_raster_to_rgb(stacked)

    raise ValueError(f"Dimensi raster tidak didukung: {data.shape}")


def create_single_raster_chips(
    raster_path,
    output_base="data/chips",
    chip_size=640,
    chips_per_task=5,
    min_valid_ratio=0.70
):
    """
    Slice single satellite raster GeoTIFF into chip tiles,
    grouped into task batches with georeferenced manifest.json.
    """
    raster_path = Path(raster_path)
    if not raster_path.exists():
        raise FileNotFoundError(f"File raster '{raster_path}' tidak ditemukan!")

    try:
        import rasterio
        from PIL import Image
    except ImportError as e:
        print_error(f"Dependensi yang diperlukan belum terpasang: {e}")
        print_info("Silakan jalankan: pip install -r requirements.txt")
        return None, 0

    raster_stem = raster_path.stem
    out_dir = Path(output_base) / raster_stem
    out_dir.mkdir(parents=True, exist_ok=True)

    print_info(f"Membuka file raster: {raster_path.name}")
    with rasterio.open(str(raster_path)) as src:
        transform = src.transform
        crs = src.crs
        width = src.width
        height = src.height
        count = src.count

        print_info(f"Dimensi raster: {width} x {height} px ({count} band) | CRS: {crs}")
        raw_data = src.read()

    # Convert to RGB image for chip generation
    print_info("Mengonversi data raster ke format visual RGB...")
    rgb_data = format_raster_to_rgb(raw_data)
    H, W, _ = rgb_data.shape

    # Calculate grid
    n_rows = H // chip_size
    n_cols = W // chip_size
    total_grid = n_rows * n_cols

    if total_grid == 0:
        print_error(f"Ukuran raster ({W}x{H} px) lebih kecil daripada ukuran chip ({chip_size}x{chip_size} px)!")
        return None, 0

    print_info(f"Grid pemotongan: {n_rows} baris x {n_cols} kolom ({total_grid} potensi chip)")

    manifest = []
    chip_counter = 0

    for r in range(n_rows):
        for c in range(n_cols):
            r_start = r * chip_size
            r_end = r_start + chip_size
            c_start = c * chip_size
            c_end = c_start + chip_size

            chip_crop = rgb_data[r_start:r_end, c_start:c_end, :]

            # Valid pixel coverage check (skip mostly black/empty borders)
            valid_pixels = np.any(chip_crop > 0, axis=-1)
            valid_ratio = np.mean(valid_pixels)
            if valid_ratio < min_valid_ratio:
                continue

            chip_counter += 1
            task_num = ((chip_counter - 1) // chips_per_task) + 1
            task_name = f"task{task_num}-{raster_stem}"
            task_dir = out_dir / task_name
            task_dir.mkdir(parents=True, exist_ok=True)

            chip_filename = f"chip_{chip_counter:04d}.png"
            chip_filepath = task_dir / chip_filename

            # Save PNG chip
            img = Image.fromarray(chip_crop)
            img.save(str(chip_filepath), optimize=True)

            # Calculate Geographic Coordinates (WGS84 lon, lat)
            top_left_x, top_left_y = transform * (c_start, r_start)
            bot_right_x, bot_right_y = transform * (c_end, r_end)

            min_lon = min(top_left_x, bot_right_x)
            max_lon = max(top_left_x, bot_right_x)
            min_lat = min(top_left_y, bot_right_y)
            max_lat = max(top_left_y, bot_right_y)

            manifest.append({
                "chip_id": f"chip_{chip_counter:04d}",
                "task": task_name,
                "relative_path": str(Path(task_name) / chip_filename).replace("\\", "/"),
                "pixel_bbox": [c_start, r_start, c_end, r_end],
                "geo_bbox": [min_lon, min_lat, max_lon, max_lat],
                "dimensions": [chip_size, chip_size],
                "valid_coverage": round(float(valid_ratio), 4),
            })

    # Save manifest.json
    manifest_path = out_dir / "manifest.json"
    manifest_data = {
        "source_raster": str(raster_path.name),
        "crs": str(crs),
        "chip_size": chip_size,
        "chips_per_task": chips_per_task,
        "total_chips": chip_counter,
        "total_tasks": ((chip_counter - 1) // chips_per_task) + 1 if chip_counter > 0 else 0,
        "chips": manifest,
    }
    with open(str(manifest_path), "w") as f:
        json.dump(manifest_data, f, indent=2)

    print_success(f"Pemotongan selesai! Berhasil membuat {chip_counter} chip.")
    print_info(f"Folder output: {out_dir}")
    print_info(f"File manifest tersimpan di: {manifest_path}")

    return str(out_dir), chip_counter


def interactive_chipping_workflow():
    """
    Interactive Workflow 2: Chipping & Upload ke Roboflow.
    """
    print_step("Workflow 2: Chipping & Upload ke Roboflow")

    # 1. Pilih Raster dari data/raw
    raw_files = list_available_raw_rasters()
    if not raw_files:
        print_error("Tidak ada file raster GeoTIFF (.tif) di 'data/raw/'!")
        print_info("Silakan jalankan Workflow 1 (Download Data) terlebih dahulu, atau masukkan file .tif ke 'data/raw/'.")
        return

    raster_choices = [
        {"name": f.name, "desc": f"Ukuran: {f.stat().st_size / (1024*1024):.2f} MB"}
        for f in raw_files
    ]
    raster_idx = select("Pilih File Raw Raster yang Ingin Dipotong (Chip):", raster_choices)
    selected_raster = raw_files[raster_idx]
    print_success(f"Raster terpilih: {selected_raster.name}")

    # 2. Pilih Ukuran Clip
    size_choices = [
        {"name": s["name"], "desc": s["desc"]}
        for s in CHIP_SIZES
    ]
    size_idx = select("Pilih Ukuran Potongan Clip (Pixel Size):", size_choices, default_index=2)
    selected_chip_size = CHIP_SIZES[size_idx]["size"]
    print_success(f"Ukuran clip: {selected_chip_size} x {selected_chip_size} px")

    # 3. Tentukan Batch Task (Chips per Task)
    chips_per_task = prompt_number(
        "Tentukan Jumlah Chip dalam Tiap Batch Task",
        default=5,
        min_val=1,
        max_val=500
    )
    print_info(f"Batch task: {chips_per_task} chips per task folder")

    # 4. Jalankan Pemotongan
    chips_dir, count = create_single_raster_chips(
        raster_path=selected_raster,
        output_base="data/chips",
        chip_size=selected_chip_size,
        chips_per_task=chips_per_task
    )

    if count == 0 or not chips_dir:
        print_warning("Tidak ada chip yang berhasil dihasilkan (mungkin citra kosong atau ukuran tidak cocok).")
        return

    # 5. Pilihan Upload ke Roboflow
    print_step("Pilihan Upload ke Roboflow")
    upload_options = [
        {
            "name": "🚀 Ya, Upload Batch Chip ke Roboflow Sekarang",
            "desc": "Kirim task folders langsung ke Roboflow sebagai Annotation Batches",
            "action": "upload"
        },
        {
            "name": "💾 Simpan Lokal Saja (Lewati Upload)",
            "desc": "Selesaikan proses dan simpan chip di folder lokal data/chips/",
            "action": "skip"
        }
    ]
    up_idx = select("Apakah Anda ingin meng-upload chip ke Roboflow?", upload_options, default_index=0)

    if upload_options[up_idx]["action"] == "upload":
        from .uploader import interactive_upload_flow
        interactive_upload_flow(chips_dir_path=chips_dir)
    else:
        print_success("Proses selesai! Seluruh chip tersimpan secara lokal dan siap digunakan.")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="GeoChip Tiling Engine")
    parser.add_argument("--raster", type=str, default=None, help="Path to input GeoTIFF raster")
    parser.add_argument("--chip-size", type=int, default=640, help="Chip tile size in pixels")
    parser.add_argument("--chips-per-task", type=int, default=5, help="Number of chips per task batch")
    args = parser.parse_args()

    if args.raster:
        create_single_raster_chips(
            raster_path=args.raster,
            chip_size=args.chip_size,
            chips_per_task=args.chips_per_task
        )
    else:
        interactive_chipping_workflow()


if __name__ == "__main__":
    main()
