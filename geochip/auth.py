"""
Google Earth Engine & Roboflow Authentication and Credentials Management.
Provides interactive login and credential setup for Earth Engine and Roboflow.
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

from .ui import (
    select,
    prompt_input,
    prompt_confirm,
    print_step,
    print_success,
    print_error,
    print_warning,
    print_info,
)


def get_ee_project_id():
    """Retrieve Earth Engine GCP project ID from environment variables."""
    return os.getenv("EE_PROJECT_ID", "").strip() or None


def save_env_variable(key, value):
    """Save or update an environment variable in the local .env file."""
    env_lines = []
    if os.path.exists(".env"):
        with open(".env", "r") as f:
            for line in f:
                if not line.startswith(f"{key}="):
                    env_lines.append(line.rstrip())

    env_lines.append(f"{key}={value}")
    with open(".env", "w") as f:
        f.write("\n".join(env_lines) + "\n")
    os.environ[key] = str(value)


def init_earth_engine(project_id=None):
    """
    Initialize Google Earth Engine connection using user browser OAuth credentials.
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
    """Trigger browser OAuth authentication flow for Google Earth Engine."""
    import ee

    print("=" * 60)
    print("  GOOGLE EARTH ENGINE (GEE) - BROWSER OAUTH LOGIN")
    print("=" * 60)

    try:
        print("\nOpening web browser for Google authentication...")
        ee.Authenticate()
        print("\n[OK] Authentication token successfully saved to local credentials cache.")

        if not project_id:
            project_id = get_ee_project_id()
        if not project_id:
            print("\nPlease enter the Google Cloud Project ID associated with your GEE account.")
            project_id = input("GCP Project ID (e.g., my-gee-project-123): ").strip()

        if project_id:
            save_env_variable("EE_PROJECT_ID", project_id)
            print_success(f"Project ID '{project_id}' saved to .env")

        print("\nVerifying initialization...")
        if project_id:
            ee.Initialize(project=project_id)
        else:
            ee.Initialize()

        print_success("Google Earth Engine initialized and ready to use!")
        return True

    except Exception as e:
        print_error(f"Login failed: {e}")
        return False


def setup_roboflow_credentials():
    """Interactive Roboflow API credentials setup."""
    print_step("Roboflow Credentials Setup")

    current_key = os.getenv("ROBOFLOW_API_KEY", "").strip()
    current_ws = os.getenv("ROBOFLOW_WORKSPACE", "").strip()
    current_proj = os.getenv("ROBOFLOW_PROJECT", "").strip()

    print_info("Configuring Roboflow Private API Key and Project Workspace.")
    print_info("Keys will be safely saved to your local .env file (gitignored).\n")

    api_key = prompt_input("Roboflow Private API Key", default=current_key if current_key else None)
    workspace = prompt_input("Roboflow Workspace ID / Slug", default=current_ws if current_ws else None)
    project = prompt_input("Target Roboflow Project ID", default=current_proj if current_proj else None)

    if api_key:
        save_env_variable("ROBOFLOW_API_KEY", api_key)
    if workspace:
        save_env_variable("ROBOFLOW_WORKSPACE", workspace)
    if project:
        save_env_variable("ROBOFLOW_PROJECT", project)

    print_success("Roboflow credentials successfully saved to .env!")

    # Test connection
    if prompt_confirm("Would you like to test the Roboflow connection now?", default=True):
        try:
            from roboflow import Roboflow
            rf = Roboflow(api_key=api_key)
            ws_obj = rf.workspace(workspace)
            proj_obj = ws_obj.project(project)
            print_success(f"Successfully connected to Roboflow project: '{workspace}/{project}'")
        except Exception as e:
            print_error(f"Could not connect to Roboflow: {e}")
            print_warning("Please verify your API key and workspace/project slug.")


def test_all_connections():
    """Diagnostic tool to test Earth Engine and Roboflow connectivity."""
    print_step("Diagnostic Connection Test")

    # 1. Earth Engine Check
    print_info("Testing Google Earth Engine...")
    ee_ok = init_earth_engine()
    if ee_ok:
        try:
            import ee
            test_val = ee.Number(42).getInfo()
            print_success(f"Earth Engine API compute test passed (Result: {test_val})")
        except Exception as e:
            print_error(f"Earth Engine compute failed: {e}")
            ee_ok = False
    else:
        print_error("Earth Engine connection failed. Please run GEE Login.")

    # 2. Roboflow Check
    print("\n" + "-" * 40)
    print_info("Testing Roboflow credentials...")
    rf_key = os.getenv("ROBOFLOW_API_KEY", "").strip()
    rf_ws = os.getenv("ROBOFLOW_WORKSPACE", "").strip()
    rf_proj = os.getenv("ROBOFLOW_PROJECT", "").strip()

    if not rf_key or not rf_ws or not rf_proj:
        print_warning("Roboflow credentials are incomplete in .env. Run Setup Roboflow Credentials.")
    else:
        try:
            from roboflow import Roboflow
            rf = Roboflow(api_key=rf_key)
            proj = rf.workspace(rf_ws).project(rf_proj)
            print_success(f"Roboflow connection verified: '{rf_ws}/{rf_proj}'")
        except Exception as e:
            print_error(f"Roboflow check failed: {e}")

    print("\n" + "=" * 60)


# Backward compatibility alias
test_earth_engine_connection = test_all_connections


def interactive_auth_menu():
    """Interactive authentication management submenu."""
    print_step("Credentials & Authentication Setup")

    auth_choices = [
        {
            "name": "🌐 Google Earth Engine Login (Browser OAuth)",
            "desc": "Authenticate with your Google account via browser and set GCP Project ID",
            "action": "gee",
        },
        {
            "name": "🤖 Setup Roboflow API Credentials",
            "desc": "Configure Private API Key, Workspace Slug, and Target Project ID",
            "action": "roboflow",
        },
        {
            "name": "🔍 Test Connections & Diagnostic Status",
            "desc": "Verify live API connectivity to Earth Engine and Roboflow",
            "action": "test",
        },
        {
            "name": "⬅️  Back to Main Menu",
            "desc": "Return to the main GeoChip workflow selector",
            "action": "back",
        },
    ]

    while True:
        idx = select("Select Authentication / Credential Action:", auth_choices, default_index=0)
        action = auth_choices[idx]["action"]

        if action == "gee":
            login_flow()
        elif action == "roboflow":
            setup_roboflow_credentials()
        elif action == "test":
            test_all_connections()
        elif action == "back":
            break
        print("\n")


def main():
    parser = argparse.ArgumentParser(description="Google Earth Engine & Roboflow Authentication Setup")
    parser.add_argument("--login", action="store_true", help="Launch interactive browser login for Earth Engine")
    parser.add_argument("--project", type=str, default=None, help="Google Cloud Project ID")
    parser.add_argument("--roboflow", action="store_true", help="Configure Roboflow credentials")
    args = parser.parse_args()

    if args.roboflow:
        setup_roboflow_credentials()
    elif args.login:
        login_flow(project_id=args.project)
    else:
        interactive_auth_menu()


if __name__ == "__main__":
    main()
