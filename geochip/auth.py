import os
import sys
import json
import argparse
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env if present
load_dotenv()


def get_auth_config():
    """Retrieve authentication configuration from environment variables or local files."""
    project_id = os.getenv("EE_PROJECT_ID")
    service_account_key = os.getenv("EE_SERVICE_ACCOUNT_KEY", "credentials.json")

    # Check for credentials.json or fallback to service_account.json
    if not os.path.exists(service_account_key):
        if os.path.exists("service_account.json"):
            service_account_key = "service_account.json"
        else:
            service_account_key = None

    return project_id, service_account_key


def init_earth_engine(project_id=None, service_account_key=None):
    """
    Initialize Google Earth Engine (GEE) connection.
    Attempts service account key first, then falls back to user OAuth credentials.
    """
    import ee

    env_project_id, env_service_account_key = get_auth_config()
    project_id = project_id or env_project_id
    service_account_key = service_account_key or env_service_account_key

    # 1. Try Service Account Key if file exists
    if service_account_key and os.path.exists(service_account_key):
        try:
            with open(service_account_key, "r") as f:
                key_data = json.load(f)
            client_email = key_data.get("client_email")
            key_project = key_data.get("project_id", project_id)

            credentials = ee.ServiceAccountCredentials(client_email, service_account_key)
            ee.Initialize(credentials, project=key_project)
            print(f"[AUTH] Successfully initialized via Service Account ({client_email}) | Project: {key_project}")
            return True
        except Exception as e:
            print(f"[WARN] Failed initializing Service Account '{service_account_key}': {e}")
            print("[WARN] Attempting OAuth fallback...")

    # 2. Try User OAuth Credentials
    try:
        if project_id:
            ee.Initialize(project=project_id)
            print(f"[AUTH] Successfully initialized via OAuth credentials | Project: {project_id}")
        else:
            ee.Initialize()
            print("[AUTH] Successfully initialized via default OAuth credentials")
        return True
    except Exception as e:
        print(f"[ERROR] Failed to initialize Google Earth Engine: {e}")
        print("\nPlease authenticate by running:")
        print("  python auth_setup.py --login --project <YOUR_PROJECT_ID>")
        print("or place a valid 'credentials.json' service account file in the project root.")
        return False


def test_earth_engine_connection():
    """Test GEE connectivity and access permissions to required datasets."""
    import ee

    project_id, service_account_key = get_auth_config()

    print("=" * 60)
    print("  GOOGLE EARTH ENGINE (GEE) - AUTHENTICATION & DIAGNOSTIC TEST")
    print("=" * 60)

    initialized = init_earth_engine(project_id=project_id, service_account_key=service_account_key)
    if not initialized:
        print("\n[FAILED] Could not establish connection to Earth Engine.")
        sys.exit(1)

    print("\n[2/3] Verifying Earth Engine API access...")
    try:
        test_val = ee.Number(42).getInfo()
        print(f"      [OK] Earth Engine API computation test passed (Result: {test_val})")
    except Exception as e:
        print(f"      [FAILED] Earth Engine API computation failed: {e}")
        sys.exit(1)

    print("\n[3/3] Checking dataset catalog access...")
    # Check Sentinel-2 Harmonized
    try:
        s2 = ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED").limit(1).getInfo()
        print("      [OK] Sentinel-2 Harmonized dataset (COPERNICUS/S2_SR_HARMONIZED) is accessible!")
    except Exception as e:
        print(f"      [FAILED] Access denied or error loading Sentinel-2: {e}")

    # Check Google Satellite Embeddings
    try:
        gse = ee.ImageCollection("GOOGLE/SATELLITE_EMBEDDING/V1/ANNUAL").limit(1).getInfo()
        print("      [OK] Google Satellite Embeddings (GOOGLE/SATELLITE_EMBEDDING/V1/ANNUAL) is accessible!")
    except Exception as e:
        print(f"      [FAILED] Access denied or error loading Google Satellite Embeddings: {e}")

    print("\n" + "=" * 60)
    print("  STATUS: ALL EARTH ENGINE SYSTEMS READY!")
    print("=" * 60)


def login_flow(project_id=None):
    """Trigger browser-based OAuth authentication flow for Google Earth Engine."""
    import ee

    print("=" * 60)
    print("  GOOGLE EARTH ENGINE (GEE) - BROWSER OAUTH LOGIN")
    print("=" * 60)

    try:
        print("\nOpening web browser for authentication...")
        ee.Authenticate()
        print("\n[OK] Authentication token successfully saved to local credentials cache.")

        if project_id:
            # Save project ID to .env if provided
            env_lines = []
            if os.path.exists(".env"):
                with open(".env", "r") as f:
                    for line in f:
                        if not line.startswith("EE_PROJECT_ID="):
                            env_lines.append(line.rstrip())
            env_lines.append(f"EE_PROJECT_ID={project_id}")
            with open(".env", "w") as f:
                f.write("\n".join(env_lines) + "\n")
            print(f"[OK] Project ID '{project_id}' saved to '.env'")

        print("\nVerifying initialization...")
        if project_id:
            ee.Initialize(project=project_id)
        else:
            ee.Initialize()
        print("[SUCCESS] Successfully logged in and initialized Google Earth Engine!")

    except Exception as e:
        print(f"\n[ERROR] Login failed: {e}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Google Earth Engine Authentication & Diagnostic Tool")
    parser.add_argument("--login", action="store_true", help="Launch interactive browser login (OAuth)")
    parser.add_argument("--project", type=str, default=None, help="Google Cloud Project ID associated with GEE")
    args = parser.parse_args()

    if args.login:
        login_flow(project_id=args.project)
    else:
        test_earth_engine_connection()


if __name__ == "__main__":
    main()
