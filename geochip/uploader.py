import os
import sys
import argparse
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()


def clean_roboflow_id(val):
    """Clean URL or whitespace string to obtain pure Roboflow slug ID."""
    if not val:
        return val
    val = val.strip()
    if "roboflow.com" in val:
        parts = [p for p in val.split("/") if p and p not in ["https:", "http:", "app.roboflow.com"]]
        if parts:
            return parts[-1]
    return val


def get_roboflow_credentials():
    """Extract Roboflow credentials from environment variables."""
    api_key = (os.getenv("ROBOFLOW_API_KEY") or "").strip()
    workspace_id = clean_roboflow_id(os.getenv("ROBOFLOW_WORKSPACE"))
    project_id = clean_roboflow_id(os.getenv("ROBOFLOW_PROJECT"))
    return api_key, workspace_id, project_id


def save_credentials_to_env(api_key, workspace_id, project_id):
    """Save provided credentials to local .env file."""
    env_lines = []
    if os.path.exists(".env"):
        with open(".env", "r") as f:
            for line in f:
                if not any(line.startswith(k) for k in ["ROBOFLOW_API_KEY=", "ROBOFLOW_WORKSPACE=", "ROBOFLOW_PROJECT="]):
                    env_lines.append(line.rstrip())

    env_lines.append(f"ROBOFLOW_API_KEY={api_key}")
    env_lines.append(f"ROBOFLOW_WORKSPACE={workspace_id}")
    env_lines.append(f"ROBOFLOW_PROJECT={project_id}")

    with open(".env", "w") as f:
        f.write("\n".join(env_lines) + "\n")
    print("[OK] Roboflow credentials saved to '.env'")


def upload_chips_to_roboflow(
    aoi_name="AOI-1",
    target_type="Sentinel",
    task_name="all",
    base_dir="data/chips",
    api_key=None,
    workspace_id=None,
    project_id=None
):
    """Upload task chip folders to Roboflow as organized Annotation Batches."""
    env_key, env_ws, env_proj = get_roboflow_credentials()
    api_key = api_key or env_key
    workspace_id = workspace_id or env_ws
    project_id = project_id or env_proj

    print("=" * 60)
    print("  ROBOFLOW BATCH UPLOADER")
    print("=" * 60)

    # Prompt if credentials missing
    if not api_key or not workspace_id or not project_id:
        print("\n[ATTENTION] Roboflow credentials are incomplete!")
        print("Please provide credentials (will be automatically saved to .env):\n")
        if not api_key:
            api_key = input("1. Enter Roboflow Private API Key: ").strip()
        if not workspace_id:
            workspace_id = input("2. Enter Roboflow Workspace ID: ").strip()
        if not project_id:
            project_id = input("3. Enter Roboflow Project/Dataset ID: ").strip()

        if api_key and workspace_id and project_id:
            save_credentials_to_env(api_key, workspace_id, project_id)
        else:
            print("[FAILED] Incomplete credentials provided. Aborting upload.")
            sys.exit(1)

    # Connect to Roboflow
    try:
        from roboflow import Roboflow
        rf = Roboflow(api_key=api_key)
        workspace = rf.workspace(workspace_id)
        project = workspace.project(project_id)
        print(f"[OK] Successfully connected to Roboflow: '{workspace_id}/{project_id}'")
    except Exception as e:
        print(f"[FAILED] Could not connect to Roboflow: {e}")
        print("\nTroubleshooting:")
        print("1. Verify your Private API Key (Roboflow > Settings > Workspaces > Roboflow API).")
        print("2. Ensure Workspace and Project exist on Roboflow.")
        sys.exit(1)

    # Resolve chips directory
    candidate_dirs = [
        Path(base_dir) / aoi_name / target_type,
        Path("Chips") / aoi_name / target_type,
    ]
    chips_dir = None
    for cd in candidate_dirs:
        if cd.exists():
            chips_dir = cd
            break

    if not chips_dir:
        print(f"[FAILED] Directory for '{aoi_name}/{target_type}' not found in '{base_dir}' or 'Chips'.")
        print("Please run the chipping step first: python -m geochip.tiler --aoi {aoi_name}")
        sys.exit(1)

    # Discover task folders
    if task_name == "all":
        task_folders = sorted([f for f in chips_dir.iterdir() if f.is_dir() and f.name.startswith("task")])
    else:
        target_folder = chips_dir / task_name
        if not target_folder.exists():
            print(f"[FAILED] Specified task folder '{target_folder}' does not exist.")
            sys.exit(1)
        task_folders = [target_folder]

    if not task_folders:
        print(f"[FAILED] No task directories found inside '{chips_dir}'.")
        sys.exit(1)

    print(f"\n[SCAN] Found {len(task_folders)} task folders to upload from: {chips_dir}")

    total_uploaded = 0
    total_skipped = 0

    for task_folder in task_folders:
        batch_name = task_folder.name
        img_files = sorted(list(task_folder.glob("*.png")) + list(task_folder.glob("*.jpg")))
        print(f"\n---> Uploading Batch '{batch_name}' ({len(img_files)} images)...")

        for img_path in img_files:
            try:
                project.upload(
                    image_path=str(img_path),
                    batch_name=batch_name,
                    num_retry_uploads=3
                )
                print(f"      [OK] Uploaded: {img_path.name}")
                total_uploaded += 1
            except Exception as e:
                err_msg = str(e)
                if "Duplicate image" in err_msg or "already exists" in err_msg.lower():
                    print(f"      [SKIP] Image already exists: {img_path.name}")
                    total_skipped += 1
                else:
                    print(f"      [WARN] Failed to upload {img_path.name}: {err_msg}")

    print("\n" + "=" * 60)
    print("  ROBOFLOW BATCH UPLOAD COMPLETED!")
    print(f"  Successfully Uploaded: {total_uploaded} images")
    print(f"  Skipped (Duplicates):  {total_skipped} images")
    print("  Go to your Roboflow dashboard > Annotate tab to assign batches!")
    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(description="Upload Chip Batches to Roboflow for Annotation")
    parser.add_argument("--aoi", type=str, default="AOI-1", help="Target AOI identifier (default: AOI-1)")
    parser.add_argument("--target-type", type=str, choices=["Sentinel", "GSE"], default="Sentinel", help="Target imagery set to upload: 'Sentinel' or 'GSE' (default: Sentinel)")
    parser.add_argument("--task", type=str, default="all", help="Target task folder or 'all' (default: all)")
    parser.add_argument("--base-dir", type=str, default="data/chips", help="Base directory containing chip data (default: data/chips)")
    parser.add_argument("--api-key", type=str, default=None, help="Roboflow Private API Key")
    parser.add_argument("--workspace", type=str, default=None, help="Roboflow Workspace ID")
    parser.add_argument("--project", type=str, default=None, help="Roboflow Project ID")
    args = parser.parse_args()

    upload_chips_to_roboflow(
        aoi_name=args.aoi,
        target_type=args.target_type,
        task_name=args.task,
        base_dir=args.base_dir,
        api_key=args.api_key,
        workspace_id=args.workspace,
        project_id=args.project
    )


if __name__ == "__main__":
    main()
