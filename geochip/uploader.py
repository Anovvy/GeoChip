"""
GeoChip Roboflow Batch Annotation Uploader.
Uploads task chip folders as distinct annotation batches into Roboflow projects.
"""

import os
import sys
import argparse
from pathlib import Path
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

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
    print_success("Kredensial Roboflow berhasil disimpan ke '.env'")


def upload_chips_to_roboflow(
    chips_dir,
    api_key=None,
    workspace_id=None,
    project_id=None,
    task_name="all"
):
    """Core upload engine that pushes batch folders to Roboflow project."""
    chips_dir = Path(chips_dir)
    if not chips_dir.exists():
        print_error(f"Direktori chip '{chips_dir}' tidak ditemukan!")
        return False

    env_key, env_ws, env_proj = get_roboflow_credentials()
    api_key = api_key or env_key
    workspace_id = workspace_id or env_ws
    project_id = project_id or env_proj

    if not api_key or not workspace_id or not project_id:
        print_error("Kredensial Roboflow tidak lengkap!")
        return False

    print_info(f"Menghubungkan ke Roboflow ({workspace_id}/{project_id})...")
    try:
        from roboflow import Roboflow
        rf = Roboflow(api_key=api_key)
        workspace = rf.workspace(workspace_id)
        project = workspace.project(project_id)
        print_success(f"Berhasil tersambung ke project Roboflow: '{project_id}'")
    except Exception as e:
        print_error(f"Gagal menghubungkan ke Roboflow: {e}")
        return False

    # Find task folders
    if task_name == "all":
        task_folders = sorted([f for f in chips_dir.iterdir() if f.is_dir() and f.name.startswith("task")])
    else:
        target_folder = chips_dir / task_name
        if not target_folder.exists():
            print_error(f"Folder task '{target_folder}' tidak ditemukan.")
            return False
        task_folders = [target_folder]

    if not task_folders:
        print_warning(f"Tidak ada folder task batch di dalam '{chips_dir}'.")
        return False

    print_info(f"Ditemukan {len(task_folders)} folder batch task yang siap di-upload.\n")

    total_uploaded = 0
    total_skipped = 0

    for task_folder in task_folders:
        batch_name = task_folder.name
        img_files = sorted(list(task_folder.glob("*.png")) + list(task_folder.glob("*.jpg")))
        print(f"\n---> Mengunggah Batch: {batch_name} ({len(img_files)} citra)...")

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
                if "duplicate" in err_msg.lower() or "already exists" in err_msg.lower():
                    print(f"      [SKIP] {img_path.name} (sudah pernah di-upload sebelumnya)")
                    total_skipped += 1
                else:
                    print(f"      [ERROR] Gagal mengunggah {img_path.name}: {err_msg}")

    print_success(f"\nSelesai! Berhasil mengunggah {total_uploaded} citra (Dilewati: {total_skipped}).")
    print_info(f"Buka https://app.roboflow.com/{workspace_id}/{project_id}/annotate untuk mulai anotasi.")
    return True


def interactive_upload_flow(chips_dir_path=None):
    """Interactive Roboflow upload flow."""
    print_step("Roboflow Batch Uploader")

    # 1. Resolve chips folder
    if not chips_dir_path:
        base_chips = Path("data/chips")
        if not base_chips.exists() or not any(base_chips.iterdir()):
            print_error("Tidak ada direktori chip di 'data/chips/'!")
            return
        candidate_dirs = sorted([d for d in base_chips.iterdir() if d.is_dir()])
        if not candidate_dirs:
            print_error("Tidak ada folder chip yang ditemukan.")
            return

        choices = [{"name": d.name, "desc": f"Path: {d}"} for d in candidate_dirs]
        idx = select("Pilih Folder Dataset Chip yang Ingin Di-upload:", choices)
        chips_dir_path = candidate_dirs[idx]

    chips_dir = Path(chips_dir_path)
    print_info(f"Folder target: {chips_dir}")

    # 2. Check / input credentials
    api_key, workspace_id, project_id = get_roboflow_credentials()

    if not api_key:
        print_info("Roboflow Private API Key belum tersimpan di .env.")
        api_key = prompt_input("Masukkan Roboflow Private API Key")
    if not workspace_id:
        workspace_id = prompt_input("Masukkan Roboflow Workspace Slug/ID")
    if not project_id:
        project_id = prompt_input("Masukkan Target Roboflow Project ID")

    # Ask if user wants to change target project
    print_info(f"Konfigurasi aktif: Workspace='{workspace_id}' | Project='{project_id}'")
    if prompt_confirm("Gunakan target project ini?", default=True):
        target_project = project_id
    else:
        target_project = prompt_input("Masukkan nama/ID project Roboflow alternatif", default=project_id)

    # Save to .env
    save_credentials_to_env(api_key, workspace_id, target_project)

    # 3. Task choice (all or specific)
    task_options = [
        {"name": "📦 Upload Semua Batch Task Sekaligus", "action": "all"},
        {"name": "🎯 Pilih Satu Batch Task Spesifik", "action": "specific"},
    ]
    t_idx = select("Pilih Lingkup Upload:", task_options)
    task_mode = task_options[t_idx]["action"]

    if task_mode == "specific":
        sub_tasks = sorted([f.name for f in chips_dir.iterdir() if f.is_dir() and f.name.startswith("task")])
        if not sub_tasks:
            print_error(f"Tidak ada subfolder task di {chips_dir}")
            return
        st_idx = select("Pilih Task Batch:", sub_tasks)
        task_name = sub_tasks[st_idx]
    else:
        task_name = "all"

    # 4. Execute upload
    upload_chips_to_roboflow(
        chips_dir=chips_dir,
        api_key=api_key,
        workspace_id=workspace_id,
        project_id=target_project,
        task_name=task_name
    )


def main():
    parser = argparse.ArgumentParser(description="GeoChip Roboflow Uploader")
    parser.add_argument("--chips-dir", type=str, default=None, help="Directory containing chip tasks")
    parser.add_argument("--api-key", type=str, default=None, help="Roboflow API Key")
    parser.add_argument("--workspace", type=str, default=None, help="Roboflow Workspace")
    parser.add_argument("--project", type=str, default=None, help="Roboflow Project")
    parser.add_argument("--task", type=str, default="all", help="Task name or 'all'")
    args = parser.parse_args()

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
