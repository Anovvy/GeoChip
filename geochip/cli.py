"""
GeoChip Unified CLI Controller.
Provides interactive menu interface (Antigravity/Claude Code style)
and standard command-line argument execution.
"""

import sys
import argparse
from pathlib import Path

from .ui import (
    print_banner,
    select,
    print_info,
    print_success,
    print_warning,
    print_error,
)
from .auth import login_flow, test_earth_engine_connection
from .downloader import interactive_download_workflow
from .tiler import interactive_chipping_workflow, create_single_raster_chips
from .uploader import interactive_upload_flow, upload_chips_to_roboflow


def interactive_main_menu():
    """Main interactive terminal loop."""
    print_banner()

    main_menu_choices = [
        {
            "name": "📥 Workflow 1: Download Data Satelit (Earth Engine)",
            "desc": "Pilih AOI, Dataset, Rentang Tanggal, Filter Awan, List Scene, Single/Composite",
            "action": "download",
        },
        {
            "name": "✂️  Workflow 2: Chipping & Upload ke Roboflow",
            "desc": "Pilih Raw Raster, Ukuran Clip (160/320/640/1280 px), Batch Task, Roboflow Upload",
            "action": "chip",
        },
        {
            "name": "🔑 Setup Autentikasi GEE (OAuth Browser Option A)",
            "desc": "Login ke Google Earth Engine menggunakan akun Google via browser",
            "action": "auth",
        },
        {
            "name": "❌ Keluar",
            "desc": "Tutup aplikasi GeoChip",
            "action": "exit",
        },
    ]

    while True:
        idx = select(
            "Pilih Workflow yang Ingin Dijalankan:",
            main_menu_choices,
            default_index=0
        )
        action = main_menu_choices[idx]["action"]

        if action == "download":
            try:
                interactive_download_workflow()
            except KeyboardInterrupt:
                print_warning("\nWorkflow Download dibatalkan oleh pengguna.")
            except Exception as e:
                print_error(f"\nTerjadi kesalahan saat download: {e}")

        elif action == "chip":
            try:
                interactive_chipping_workflow()
            except KeyboardInterrupt:
                print_warning("\nWorkflow Chipping dibatalkan oleh pengguna.")
            except Exception as e:
                print_error(f"\nTerjadi kesalahan saat chipping: {e}")

        elif action == "auth":
            try:
                login_flow()
            except KeyboardInterrupt:
                print_warning("\nProses autentikasi dibatalkan.")
            except Exception as e:
                print_error(f"\nTerjadi kesalahan saat autentikasi: {e}")

        elif action == "exit":
            print_info("Terima kasih telah menggunakan GeoChip. Sampai jumpa!")
            sys.exit(0)

        print("\n" + "-" * 60)


def main():
    """Main CLI entry point supporting both arguments and interactive mode."""
    parser = argparse.ArgumentParser(
        prog="geochip",
        description="GeoChip CLI: Geospatial Satellite Imagery Ingestion, Chipping, and Annotation Pipeline",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")

    # 1. Auth subcommand
    auth_parser = subparsers.add_parser("auth", help="Google Earth Engine OAuth setup & diagnostics")
    auth_parser.add_argument("--login", action="store_true", help="Launch interactive browser OAuth login")
    auth_parser.add_argument("--project", type=str, default=None, help="Google Cloud Project ID")

    # 2. Download subcommand
    dl_parser = subparsers.add_parser("download", help="Download satellite rasters from GEE")
    dl_parser.add_argument("--interactive", action="store_true", help="Launch interactive download UI")
    dl_parser.add_argument("--aoi", type=str, default=None, help="Path to AOI shapefile")

    # 3. Chip subcommand
    chip_parser = subparsers.add_parser("chip", help="Slice raster into chip tiles & manifest")
    chip_parser.add_argument("--raster", type=str, default=None, help="Path to input GeoTIFF raster")
    chip_parser.add_argument("--chip-size", type=int, default=640, choices=[160, 320, 640, 1280], help="Chip tile size")
    chip_parser.add_argument("--chips-per-task", type=int, default=5, help="Number of chips per task batch")

    # 4. Upload subcommand
    upload_parser = subparsers.add_parser("upload", help="Upload task batches to Roboflow")
    upload_parser.add_argument("--chips-dir", type=str, default=None, help="Chips directory")
    upload_parser.add_argument("--api-key", type=str, default=None, help="Roboflow API Key")
    upload_parser.add_argument("--workspace", type=str, default=None, help="Roboflow Workspace")
    upload_parser.add_argument("--project", type=str, default=None, help="Roboflow Project")
    upload_parser.add_argument("--task", type=str, default="all", help="Task name or 'all'")

    args = parser.parse_args()

    # If no arguments provided, launch interactive Antigravity/Claude Code menu
    if not args.command:
        interactive_main_menu()
        return

    if args.command == "auth":
        if args.login:
            login_flow(project_id=args.project)
        else:
            test_earth_engine_connection()

    elif args.command == "download":
        interactive_download_workflow()

    elif args.command == "chip":
        if args.raster:
            create_single_raster_chips(
                raster_path=args.raster,
                chip_size=args.chip_size,
                chips_per_task=args.chips_per_task
            )
        else:
            interactive_chipping_workflow()

    elif args.command == "upload":
        if args.chips_dir:
            upload_chips_to_roboflow(
                chips_dir=args.chips_dir,
                api_key=args.api_key,
                workspace_id=args.workspace,
                project_id=args.project,
                task_name=args.task
            )
        else:
            interactive_upload_flow()


if __name__ == "__main__":
    main()
