"""
GeoChip Main Entry Point.
Runs GeoChip inside a production-ready Docker container across Windows, macOS, and Linux.
Automatically launches Docker Desktop / daemon if closed and prepares host mount paths.
"""

import os
import sys
import time
import shutil
import platform
import subprocess
from pathlib import Path


def ensure_cross_platform_path():
    """Ensure standard Docker and Homebrew binary paths are included in PATH on Unix."""
    if platform.system().lower() != "windows":
        extra_paths = [
            "/usr/local/bin",
            "/opt/homebrew/bin",              # Apple Silicon Homebrew
            os.path.expanduser("~/.docker/bin"),  # Docker Desktop on macOS/Linux
            "/usr/bin",
            "/bin",
        ]
        current_path = os.environ.get("PATH", "")
        paths = current_path.split(":") if current_path else []
        for p in extra_paths:
            if os.path.exists(p) and p not in paths:
                paths.insert(0, p)
        os.environ["PATH"] = ":".join(paths)


ensure_cross_platform_path()


def is_running_in_container():
    """Detect if execution is already within a Docker container or local override."""
    return (
        os.environ.get("GEOCHIP_DOCKER") == "1"
        or os.path.exists("/.dockerenv")
        or os.environ.get("GEOCHIP_LOCAL") == "1"
    )


def print_msg(prefix, text, color="\033[94m"):
    """Format and print console message with ANSI styling."""
    reset = "\033[0m"
    bold = "\033[1m"
    print(f"{bold}{color}{prefix}{reset} {text}")


def is_docker_installed():
    """Verify if Docker CLI exists in system PATH."""
    ensure_cross_platform_path()
    return shutil.which("docker") is not None


def is_docker_daemon_running():
    """Check if the Docker daemon / engine is responsive."""
    try:
        res = subprocess.run(
            ["docker", "info"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
        return res.returncode == 0
    except Exception:
        return False


def is_image_available(image_name="geochip:latest"):
    """Check if the local Docker image is already built and available."""
    try:
        res = subprocess.run(
            ["docker", "image", "inspect", image_name],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
        return res.returncode == 0
    except Exception:
        return False


def attempt_start_docker_desktop():
    """Attempt to launch Docker Desktop / daemon according to the host operating system."""
    system = platform.system().lower()

    if "windows" in system:
        candidates = []
        docker_cli = shutil.which("docker")
        if docker_cli:
            p = Path(docker_cli)
            if len(p.parents) > 2:
                candidates.append(str(p.parents[2] / "Docker Desktop.exe"))
            if len(p.parents) > 1:
                candidates.append(str(p.parents[1] / "Docker Desktop.exe"))

        candidates.extend([
            os.path.expandvars(r"%LOCALAPPDATA%\Programs\DockerDesktop\Docker Desktop.exe"),
            os.path.expandvars(r"%LOCALAPPDATA%\Programs\Docker\Docker\Docker Desktop.exe"),
            os.path.expandvars(r"%ProgramFiles%\Docker\Docker\Docker Desktop.exe"),
            os.path.expandvars(r"%ProgramFiles(x86)%\Docker\Docker\Docker Desktop.exe"),
            os.path.expandvars(r"%APPDATA%\Microsoft\Windows\Start Menu\Programs\Docker Desktop.lnk"),
            os.path.expandvars(r"%ProgramData%\Microsoft\Windows\Start Menu\Programs\Docker Desktop.lnk"),
        ])

        for path in candidates:
            if os.path.exists(path):
                try:
                    os.startfile(path)
                    return True
                except Exception:
                    continue

        # Fallback to PowerShell Start-Process if path lookup fails
        try:
            subprocess.Popen(
                ["powershell", "-NoProfile", "-Command", "Start-Process 'Docker Desktop'"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return True
        except Exception:
            return False

    elif "darwin" in system:  # macOS
        # 1. Search for Docker.app in Applications or user Applications
        mac_apps = [
            "/Applications/Docker.app",
            os.path.expanduser("~/Applications/Docker.app"),
        ]
        for app in mac_apps:
            if os.path.exists(app):
                try:
                    subprocess.Popen(["open", "-a", app], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    return True
                except Exception:
                    pass

        # 2. General open command
        try:
            subprocess.Popen(["open", "-a", "Docker"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except Exception:
            return False

    elif "linux" in system:
        # 1. Try Docker Desktop user service (for Docker Desktop on Linux)
        try:
            res = subprocess.run(
                ["systemctl", "--user", "start", "docker-desktop"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            if res.returncode == 0:
                return True
        except Exception:
            pass

        # 2. Try launching docker-desktop binary directly
        dd_bin = shutil.which("docker-desktop") or "/opt/docker-desktop/bin/docker-desktop"
        if os.path.exists(dd_bin):
            try:
                subprocess.Popen([dd_bin], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return True
            except Exception:
                pass

        # 3. Try native systemd daemon service
        try:
            res = subprocess.run(
                ["systemctl", "start", "docker"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            if res.returncode == 0:
                return True
        except Exception:
            pass

        return False

    return False


def wait_for_docker_ready(timeout_seconds=90):
    """Wait for Docker daemon to become responsive."""
    print_msg("[WAIT]", f"Waiting for Docker engine to initialize (timeout {timeout_seconds}s)...", "\033[93m")
    start_time = time.time()

    while time.time() - start_time < timeout_seconds:
        if is_docker_daemon_running():
            print()
            return True
        elapsed = int(time.time() - start_time)
        sys.stdout.write(f"\r\033[K\033[93m[WAIT]\033[0m Initializing Docker engine... ({elapsed}s / {timeout_seconds}s)")
        sys.stdout.flush()
        time.sleep(3)

    print()
    return False


def prepare_host_environment():
    """Ensure host directories and files exist before Docker volume bind-mounts."""
    # Ensure data subdirectories exist
    for sub in ["data/aoi", "data/raw", "data/chips"]:
        Path(sub).mkdir(parents=True, exist_ok=True)

    # Sync .env and data/.env on host to ensure seamless credential sharing
    root_env = Path(".env")
    data_env = Path("data/.env")

    # If Docker previously left behind a .env directory on host, remove it safely
    if root_env.is_dir():
        try:
            nested_config = root_env / "config.env"
            saved_content = nested_config.read_text(encoding="utf-8") if nested_config.is_file() else None
            shutil.rmtree(root_env)
            if saved_content:
                data_env.write_text(saved_content, encoding="utf-8")
        except Exception:
            pass

    if data_env.is_file() and not root_env.is_file():
        try:
            shutil.copy(data_env, root_env)
        except Exception:
            pass
    elif root_env.is_file() and not data_env.is_file():
        try:
            shutil.copy(root_env, data_env)
        except Exception:
            pass
    elif not root_env.is_file() and not data_env.is_file():
        example_file = Path(".env.example")
        if example_file.is_file():
            shutil.copy(example_file, data_env)
            shutil.copy(example_file, root_env)
        else:
            data_env.touch()
            root_env.touch()

    # Ensure Earth Engine credentials folder exists with correct user ownership
    ee_dir = Path.home() / ".config" / "earthengine"
    ee_dir.mkdir(parents=True, exist_ok=True)


def run_via_docker():
    """Ensure Docker is running and launch the container cross-platform."""
    ensure_cross_platform_path()

    print("=" * 65)
    print("  GEOCHIP - SATELLITE PIPELINE DOCKER RUNNER")
    print("=" * 65)

    if not is_docker_installed():
        print_msg("\n[ERROR]", "Docker is not installed or not found in system PATH.", "\033[91m")
        print("\nGeoChip runs inside Docker to ensure all geospatial C++ libraries (GDAL/PROJ)")
        print("function without system conflicts across Windows, macOS, and Linux.")
        print("Please install Docker Desktop for your OS:")
        print("  - Windows: https://docs.docker.com/desktop/setup/install/windows-install/")
        print("  - macOS:   https://docs.docker.com/desktop/setup/install/mac-install/")
        print("  - Linux:   https://docs.docker.com/engine/install/\n")
        sys.exit(1)

    if not is_docker_daemon_running():
        print_msg("\n[NOTICE]", "Docker engine / Desktop is currently closed or stopped.", "\033[93m")
        print_msg("[ACTION]", "Attempting to launch Docker automatically...", "\033[96m")

        launched = attempt_start_docker_desktop()
        if launched:
            print_msg("[INFO]", "Docker launch signal sent. Waiting for daemon to boot...")
            ready = wait_for_docker_ready(timeout_seconds=90)
            if not ready:
                print_msg("\n[WARNING]", "Docker daemon did not become responsive within timeout.", "\033[91m")
                print("Please ensure Docker Desktop / service is running and retry: python main.py\n")
                if platform.system().lower() == "linux":
                    print("[Linux Tip] You can start native Docker with: sudo systemctl start docker")
                    print("            And enable non-root access: sudo usermod -aG docker $USER\n")
                sys.exit(1)
        else:
            print_msg("\n[WARNING]", "Could not automatically launch Docker.", "\033[91m")
            print("Please open Docker manually and retry: python main.py\n")
            if platform.system().lower() == "linux":
                print("[Linux Tip] You can start native Docker with: sudo systemctl start docker")
                print("            And enable non-root access: sudo usermod -aG docker $USER\n")
            sys.exit(1)

    # Prepare volumes
    prepare_host_environment()

    print_msg("\n[OK]", "Docker engine is active and ready.", "\033[92m")

    # If the Docker image does not exist yet on this device, build it automatically first
    if not is_image_available("geochip:latest"):
        print_msg("[BUILD]", "GeoChip Docker image 'geochip:latest' not found on this device.", "\033[93m")
        print_msg("[ACTION]", "Building Docker image from Dockerfile (first-time setup)...\n", "\033[96m")
        try:
            build_res = subprocess.run(["docker", "compose", "build"])
            if build_res.returncode != 0:
                print_msg("\n[ERROR]", "Docker image build failed. Please check the logs above.", "\033[91m")
                sys.exit(build_res.returncode)
        except FileNotFoundError:
            try:
                build_res = subprocess.run(["docker-compose", "build"])
                if build_res.returncode != 0:
                    print_msg("\n[ERROR]", "Docker image build failed. Please check the logs above.", "\033[91m")
                    sys.exit(build_res.returncode)
            except Exception as e:
                print_msg("\n[ERROR]", f"Failed to run docker compose build: {e}", "\033[91m")
                sys.exit(1)
        print_msg("\n[OK]", "Docker image built successfully!\n", "\033[92m")

    print_msg("[START]", "Starting GeoChip interactive session...\n", "\033[96m")

    cmd = ["docker", "compose", "run", "--rm", "geochip"]
    forward_args = [arg for arg in sys.argv[1:] if arg not in ("--local",)]
    if forward_args:
        cmd.extend(forward_args)

    try:
        proc = subprocess.run(cmd)
        sys.exit(proc.returncode)
    except FileNotFoundError:
        try:
            fallback_cmd = ["docker-compose", "run", "--rm", "geochip"]
            if forward_args:
                fallback_cmd.extend(forward_args)
            proc = subprocess.run(fallback_cmd)
            sys.exit(proc.returncode)
        except Exception as e:
            print_msg("[ERROR]", f"Failed to execute Docker Compose: {e}", "\033[91m")
            sys.exit(1)
    except KeyboardInterrupt:
        print("\nSession terminated by user.")
        sys.exit(0)


def main():
    # If explicitly requesting help, display CLI help directly
    if "-h" in sys.argv or "--help" in sys.argv:
        from geochip.cli import main as cli_main
        cli_main()
        return

    # If running inside Docker container or local override is specified, run the app directly
    if is_running_in_container() or "--local" in sys.argv:
        if "--local" in sys.argv:
            sys.argv.remove("--local")
        # Sanitize arguments in case runner passed redundant 'python main.py'
        if len(sys.argv) > 1 and sys.argv[1] in ("python", "python3"):
            sys.argv.pop(1)
            if len(sys.argv) > 1 and sys.argv[1] == "main.py":
                sys.argv.pop(1)
        from geochip.cli import main as cli_main
        cli_main()
        return

    # Host execution: ensure Docker Desktop is running and launch container
    run_via_docker()


if __name__ == "__main__":
    main()
