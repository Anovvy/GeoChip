import sys
import argparse
from pathlib import Path

from .auth import login_flow, test_earth_engine_connection
from .downloader import (
    load_aoi_geometry,
    process_sentinel2_mosaic,
    process_satellite_embeddings,
    init_earth_engine,
)
from .tiler import create_paired_chips
from .uploader import upload_chips_to_roboflow


def main():
    parser = argparse.ArgumentParser(
        prog="geochip",
        description="GeoChip CLI: Satellite Imagery & Embedding Ingestion, Chipping, and Annotation Pipeline",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")

    # 1. Auth subcommand
    auth_parser = subparsers.add_parser("auth", help="Manage Google Earth Engine authentication")
    auth_parser.add_argument("--login", action="store_true", help="Launch interactive browser OAuth login")
    auth_parser.add_argument("--project", type=str, default=None, help="Google Cloud Project ID")

    # 2. Download subcommand
    dl_parser = subparsers.add_parser("download", help="Download Sentinel-2 mosaics and Google Satellite Embeddings")
    dl_parser.add_argument("--aoi", type=str, default="data/aoi/AOI-1.shp", help="Path to AOI shapefile")
    dl_parser.add_argument("--mode", type=str, choices=["copernicus-q2", "annual", "window"], default="copernicus-q2", help="Sentinel-2 composite mode")
    dl_parser.add_argument("--year", type=int, default=2025, help="Target data year (default: 2025)")
    dl_parser.add_argument("--date", type=str, default="2025-04-01", help="Target date for window mode")
    dl_parser.add_argument("--window", type=int, default=15, help="Window days (default: 15)")
    dl_parser.add_argument("--output-dir", type=str, default="data/raw", help="Output directory")
    dl_parser.add_argument("--force", action="store_true", help="Force re-download all datasets")
    dl_parser.add_argument("--force-s2", action="store_true", help="Force re-download Sentinel-2")
    dl_parser.add_argument("--force-gse", action="store_true", help="Force re-download GSE")

    # 3. Chip subcommand
    chip_parser = subparsers.add_parser("chip", help="Slice rasters into paired 160x160 chips and PCA previews")
    chip_parser.add_argument("--aoi", type=str, default="AOI-1", help="AOI identifier name (e.g., AOI-1)")
    chip_parser.add_argument("--s2-path", type=str, default=None, help="Explicit Sentinel-2 raster path")
    chip_parser.add_argument("--gse-path", type=str, default=None, help="Explicit GSE raster path")
    chip_parser.add_argument("--output-base", type=str, default="data/chips", help="Output directory for chips")
    chip_parser.add_argument("--chip-size", type=int, default=160, help="Tile size in pixels (default: 160)")
    chip_parser.add_argument("--chips-per-task", type=int, default=5, help="Chips per annotation task batch (default: 5)")
    chip_parser.add_argument("--no-raw-npy", action="store_true", help="Disable saving 64-band GSE .npy files")

    # 4. Upload subcommand
    upload_parser = subparsers.add_parser("upload", help="Upload task chip batches to Roboflow")
    upload_parser.add_argument("--aoi", type=str, default="AOI-1", help="AOI identifier (default: AOI-1)")
    upload_parser.add_argument("--target-type", type=str, choices=["Sentinel", "GSE"], default="Sentinel", help="Target set (default: Sentinel)")
    upload_parser.add_argument("--task", type=str, default="all", help="Task batch folder or 'all' (default: all)")
    upload_parser.add_argument("--base-dir", type=str, default="data/chips", help="Base directory of chips")
    upload_parser.add_argument("--api-key", type=str, default=None, help="Roboflow Private API Key")
    upload_parser.add_argument("--workspace", type=str, default=None, help="Roboflow Workspace ID")
    upload_parser.add_argument("--project", type=str, default=None, help="Roboflow Project ID")

    # 5. Pipeline subcommand (end-to-end)
    pipe_parser = subparsers.add_parser("pipeline", help="Run end-to-end pipeline: download -> chip -> upload")
    pipe_parser.add_argument("--aoi-path", type=str, default="data/aoi/AOI-1.shp", help="Path to AOI shapefile")
    pipe_parser.add_argument("--year", type=int, default=2025, help="Target year")
    pipe_parser.add_argument("--upload", action="store_true", help="Also upload to Roboflow automatically upon completion")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    if args.command == "auth":
        if args.login:
            login_flow(project_id=args.project)
        else:
            test_earth_engine_connection()

    elif args.command == "download":
        out_dir = Path(args.output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        aoi_stem = Path(args.aoi).stem

        s2_path = out_dir / f"Sentinel2M-{args.year}-{aoi_stem}_TrueColor.tif"
        gse_path = out_dir / f"GSE-{args.year}-{aoi_stem}.tif"

        init_earth_engine()
        aoi_geom, _, aoi_bbox = load_aoi_geometry(args.aoi)

        process_sentinel2_mosaic(
            aoi_geom=aoi_geom,
            output_path=str(s2_path),
            mode=args.mode,
            target_year=args.year,
            target_date_str=args.date,
            window_days=args.window,
            force=(args.force or args.force_s2)
        )
        process_satellite_embeddings(
            aoi_geom=aoi_geom,
            output_path=str(gse_path),
            bbox=aoi_bbox,
            target_year=args.year,
            force=(args.force or args.force_gse)
        )

    elif args.command == "chip":
        create_paired_chips(
            aoi_name=args.aoi,
            s2_path=args.s2_path,
            gse_path=args.gse_path,
            output_base=args.output_base,
            chip_size=args.chip_size,
            chips_per_task=args.chips_per_task,
            save_raw_gse_npy=not args.no_raw_npy,
        )

    elif args.command == "upload":
        upload_chips_to_roboflow(
            aoi_name=args.aoi,
            target_type=args.target_type,
            task_name=args.task,
            base_dir=args.base_dir,
            api_key=args.api_key,
            workspace_id=args.workspace,
            project_id=args.project
        )

    elif args.command == "pipeline":
        aoi_stem = Path(args.aoi_path).stem
        print("=" * 60)
        print(f"  EXECUTING FULL GEOCHIP PIPELINE FOR {aoi_stem}")
        print("=" * 60)

        # 1. Download
        out_dir = Path("data/raw")
        out_dir.mkdir(parents=True, exist_ok=True)
        s2_path = out_dir / f"Sentinel2M-{args.year}-{aoi_stem}_TrueColor.tif"
        gse_path = out_dir / f"GSE-{args.year}-{aoi_stem}.tif"

        init_earth_engine()
        aoi_geom, _, aoi_bbox = load_aoi_geometry(args.aoi_path)
        process_sentinel2_mosaic(aoi_geom, str(s2_path), target_year=args.year)
        process_satellite_embeddings(aoi_geom, str(gse_path), bbox=aoi_bbox, target_year=args.year)

        # 2. Chip
        create_paired_chips(aoi_name=aoi_stem, s2_path=str(s2_path), gse_path=str(gse_path), output_base="data/chips")

        # 3. Optional Upload
        if args.upload:
            upload_chips_to_roboflow(aoi_name=aoi_stem, target_type="Sentinel", base_dir="data/chips")


if __name__ == "__main__":
    main()
