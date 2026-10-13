"""
Google Earth Engine Authentication & Diagnostics.
Standardized to Option A (Interactive Browser OAuth Login) only.
"""

import os
import sys
import argparse
from pathlib import Path
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    if os.path.exists(".env"):
        with open(".env", "r") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    k, v = k.strip(), v.strip().strip("'\"")
                    if k and k not in os.environ:
                        os.environ[k] = v


def get_ee_project_id():
    """Retrieve Earth Engine GCP project ID from environment variables."""
    return os.getenv("EE_PROJECT_ID", "").strip() or None


def save_project_id_to_env(project_id):
    """Save Google Cloud Project ID to local .env file."""
    env_lines = []
    if os.path.exists(".env"):
        with open(".env", "r") as f:
            for line in f:
                if not line.startswith("EE_PROJECT_ID="):
                    env_lines.append(line.rstrip())

    env_lines.append(f"EE_PROJECT_ID={project_id}")
    with open(".env", "w") as f:
        f.write("\n".join(env_lines) + "\n")
    print(f"[AUTH] Project ID '{project_id}' successfully saved to .env")


def init_earth_engine(project_id=None):
    """
    Initialize Google Earth Engine connection using User OAuth credentials (Option A).
    Returns True if successful, False otherwise.
    """
    import ee

    project_id = project_id or get_ee_project_id()

    try:
        if project_id:
            ee.Initialize(project=project_id)
            print(f"[AUTH] Successfully initialized Earth Engine (Project: {project_id})")
        else:
            ee.Initialize()
            print("[AUTH] Successfully initialized Earth Engine (Default Project)")
        return True
    except Exception as e:
        err_msg = str(e)
        print(f"\n[AUTH FAILED] Google Earth Engine is not authenticated: {err_msg}")
        return False


def login_flow(project_id=None):
    """Trigger browser-based OAuth authentication flow for Google Earth Engine (Option A)."""
    import ee

    print("=" * 60)
    print("  GOOGLE EARTH ENGINE (GEE) - BROWSER OAUTH LOGIN (OPTION A)")
    print("=" * 60)

    try:
        print("\nOpening web browser for Google authentication...")
        ee.Authenticate()
        print("\n[OK] Authentication token successfully saved to local credentials cache.")

        if not project_id:
            project_id = get_ee_project_id()
        if not project_id:
            print("\nSilakan masukkan Google Cloud Project ID yang terhubung dengan GEE.")
            project_id = input("GCP Project ID (contoh: my-gee-project-123): ").strip()

        if project_id:
            save_project_id_to_env(project_id)

        print("\nVerifying initialization...")
        if project_id:
            ee.Initialize(project=project_id)
        else:
            ee.Initialize()

        print("\n[SUCCESS] Google Earth Engine initialized and ready to use!")
        return True

    except Exception as e:
        print(f"\n[ERROR] Login failed: {e}")
        return False


def test_earth_engine_connection():
    """Diagnostic tool to test Earth Engine connectivity and API access."""
    import ee

    print("=" * 60)
    print("  GOOGLE EARTH ENGINE (GEE) - DIAGNOSTIC CHECK")
    print("=" * 60)

    project_id = get_ee_project_id()
    if not init_earth_engine(project_id=project_id):
        print("\n[FAILED] Earth Engine initialization failed.")
        print("Please run interactive login:")
        print("  python auth_setup.py --login")
        return False

    print("\n[1/2] Verifying Earth Engine compute API...")
    try:
        test_val = ee.Number(42).getInfo()
        print(f"      [OK] Compute test succeeded (Result: {test_val})")
    except Exception as e:
        print(f"      [FAILED] Earth Engine compute failed: {e}")
        return False

    print("\n[2/2] Checking Sentinel-2 & Landsat catalog accessibility...")
    try:
        s2 = ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED").limit(1).getInfo()
        print("      [OK] Sentinel-2 Harmonized catalog is accessible")
    except Exception as e:
        print(f"      [WARN] Sentinel-2 catalog check: {e}")

    try:
        l9 = ee.ImageCollection("LANDSAT/LC09/C02/T1_L2").limit(1).getInfo()
        print("      [OK] Landsat 9 catalog is accessible")
    except Exception as e:
        print(f"      [WARN] Landsat 9 catalog check: {e}")

    print("\n" + "=" * 60)
    print("  STATUS: GOOGLE EARTH ENGINE READY!")
    print("=" * 60)
    return True


def main():
    parser = argparse.ArgumentParser(description="Google Earth Engine OAuth Setup & Diagnostic Tool")
    parser.add_argument("--login", action="store_true", help="Launch interactive browser login (OAuth Option A)")
    parser.add_argument("--project", type=str, default=None, help="Google Cloud Project ID")
    args = parser.parse_args()

    if args.login:
        login_flow(project_id=args.project)
    else:
        test_earth_engine_connection()


if __name__ == "__main__":
    main()
