"""
Google Earth Engine & Roboflow Authentication and Credentials Management.
Provides interactive login and credential setup for Earth Engine and Roboflow.
"""

import os
import sys
import argparse
from pathlib import Path

from pathlib import Path


def extract_roboflow_slug(val):
    """Clean a full URL or path into a bare Roboflow identifier/slug."""
    if not val:
        return ""
    val = val.strip().rstrip("/")
    if "roboflow.com/" in val:
        val = val.split("roboflow.com/")[-1]
    if "/" in val:
        val = val.split("/")[-1]
    return val.strip()


def get_env_file_path():
    """Resolve the environment file path.
    Prefers 'data/.env' inside container (mounted via ./data) or root '.env'.
    """
    data_env = Path("data/.env")
    root_env = Path(".env")
    if root_env.is_file():
        return root_env
    if data_env.parent.is_dir():
        return data_env
    return root_env


def load_app_env():
    """Load environment variables safely from data/.env or .env."""
    for p in [Path("data/.env"), Path(".env")]:
        if p.is_file():
            try:
                from dotenv import load_dotenv
                load_dotenv(str(p), override=False)
            except ImportError:
                pass
            try:
                with open(p, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            k, v = line.split("=", 1)
                            k, v = k.strip(), v.strip().strip("'\"")
                            if k and k not in os.environ:
                                os.environ[k] = v
            except Exception:
                pass


load_app_env()

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


DUMMY_PLACEHOLDERS = {
    "your_gcp_project_id",
    "your_private_api_key_here",
    "your_workspace_id",
    "your_project_id",
    "none",
    "null",
}


def is_valid_credential_val(val):
    """Check if value is a real credential and not an example placeholder."""
    if not val:
        return False
    val_clean = str(val).strip().lower()
    return val_clean not in DUMMY_PLACEHOLDERS and not val_clean.startswith("your_")


def get_ee_project_id():
    """Retrieve Earth Engine GCP project ID from environment variables."""
    val = os.getenv("EE_PROJECT_ID", "").strip()
    return val if is_valid_credential_val(val) else None


def save_env_variable(key, value):
    """Save or update an environment variable in both data/.env and .env if writable."""
    targets = []
    data_env = Path("data/.env")
    root_env = Path(".env")

    # Prefer data/.env as it is inside the permanently mounted ./data volume
    if data_env.parent.is_dir():
        targets.append(data_env)
    if root_env.is_file() and root_env not in targets:
        targets.append(root_env)

    if not targets:
        targets.append(data_env)

    for env_file in targets:
        try:
            env_file.parent.mkdir(parents=True, exist_ok=True)
            env_lines = []
            if env_file.is_file():
                with open(env_file, "r", encoding="utf-8") as f:
                    for line in f:
                        if not line.startswith(f"{key}="):
                            env_lines.append(line.rstrip())
            env_lines.append(f"{key}={value}")
            with open(env_file, "w", encoding="utf-8") as f:
                f.write("\n".join(env_lines) + "\n")
        except Exception:
            pass

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
        # In Docker containers / headless environments, auth_mode='notebook' provides a verification code
        # web flow without requiring the heavy Google Cloud SDK (gcloud) installation.
        try:
            ee.Authenticate(auth_mode="notebook")
        except TypeError:
            ee.Authenticate()
        print("\n[OK] Authentication token successfully saved to local credentials cache.")

        current_proj = project_id if is_valid_credential_val(project_id) else get_ee_project_id()
        print_info("\nPlease enter the Google Cloud Project ID associated with your GEE account.")
        print_info("To check or find your GCP Project ID, visit:")
        print_info("  🔗 Google Cloud Console   : https://console.cloud.google.com/welcome")
        print_info("  🔗 Earth Engine Projects  : https://code.earthengine.google.com/\n")
        project_id = prompt_input("GCP Project ID (e.g., my-gee-project-123)", default=current_proj).strip()

        if project_id:
            save_env_variable("EE_PROJECT_ID", project_id)
            print_success(f"Project ID '{project_id}' saved to configuration")

        print("\nVerifying initialization...")
        try:
            if project_id:
                ee.Initialize(project=project_id)
            else:
                ee.Initialize()
            print_success("Google Earth Engine initialized and ready to use!")
            return True
        except Exception as init_err:
            print_error(f"Initialization check failed: {init_err}")
            err_str = str(init_err)
            if "not registered" in err_str.lower():
                print_warning(f"\nYour GCP project '{project_id}' is not yet registered for Earth Engine access:")
                print_info(f"  🔗 1. Open Configuration : https://console.cloud.google.com/earth-engine/configuration?project={project_id}")
                print_info("  🔗 2. Select Project Usage : Choose 'Unpaid / Noncommercial' (or appropriate tier).")
                print_info("  🔗 3. Select Project Type  : Choose 'Personal / Student / Research / Open Source' and click Confirm.")
                print_info("  🔗 4. Return to GeoChip and select 'Test Connections' or re-run GEE Login.\n")
            else:
                print_warning("\nPlease verify Earth Engine API enablement and registration for your GCP project:")
                print_info(f"  🔗 Enable API       : https://console.cloud.google.com/apis/library/earthengine.googleapis.com?project={project_id or ''}")
                print_info(f"  🔗 Register Project : https://console.cloud.google.com/earth-engine/configuration?project={project_id or ''}\n")
            return False

    except Exception as e:
        print_error(f"Login failed: {e}")
        return False


def setup_roboflow_credentials():
    """Interactive Roboflow API credentials setup."""
    print_step("Roboflow Credentials Setup")

    current_key = os.getenv("ROBOFLOW_API_KEY", "").strip()
    current_ws = os.getenv("ROBOFLOW_WORKSPACE", "").strip()
    current_proj = os.getenv("ROBOFLOW_PROJECT", "").strip()

    current_key = current_key if is_valid_credential_val(current_key) else None
    current_ws = current_ws if is_valid_credential_val(current_ws) else None
    current_proj = current_proj if is_valid_credential_val(current_proj) else None

    print_info("Configuring Roboflow Private API Key and Project Workspace.")
    print_info("Credentials will be safely saved to your environment configuration.\n")
    print_info("How to obtain your Roboflow credentials:")
    print_info("  1. Private API Key : Login to app.roboflow.com -> Settings -> Roboflow API -> Private API Key")
    print_info("  2. Workspace ID    : Found in the workspace URL -> app.roboflow.com/<workspace-slug>")
    print_info("  3. Target Project  : Found in project URL -> app.roboflow.com/<workspace-slug>/<project-id>\n")

    raw_api_key = prompt_input("Roboflow Private API Key", default=current_key if current_key else None)
    raw_workspace = prompt_input("Roboflow Workspace ID / Slug", default=current_ws if current_ws else None)
    raw_project = prompt_input("Target Roboflow Project ID", default=current_proj if current_proj else None)

    api_key = raw_api_key.strip()
    workspace = extract_roboflow_slug(raw_workspace)
    project = extract_roboflow_slug(raw_project)

    if raw_workspace and raw_workspace.strip() != workspace:
        print_info(f"Cleaned Workspace URL to slug: '{workspace}'")
    if raw_project and raw_project.strip() != project:
        print_info(f"Cleaned Project URL to slug: '{project}'")

    if api_key:
        save_env_variable("ROBOFLOW_API_KEY", api_key)
    if workspace:
        save_env_variable("ROBOFLOW_WORKSPACE", workspace)
    if project:
        save_env_variable("ROBOFLOW_PROJECT", project)

    print_success("Roboflow credentials successfully saved!")

    # Test connection
    if prompt_confirm("Would you like to test the Roboflow connection now?", default=True):
        try:
            from roboflow import Roboflow
            rf = Roboflow(api_key=api_key)
            ws_obj = rf.workspace(workspace)
            proj_obj = ws_obj.project(project)
            print_success(f"Successfully connected to Roboflow project: '{workspace}/{project}' (Name: '{proj_obj.name}')")
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
    rf_ws = extract_roboflow_slug(os.getenv("ROBOFLOW_WORKSPACE", "").strip())
    rf_proj = extract_roboflow_slug(os.getenv("ROBOFLOW_PROJECT", "").strip())

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
            "name": "⬅️ Back to Main Menu",
            "desc": "Return to the main GeoChip menu",
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
