#!/usr/bin/env python3
"""
GeoChip Automated Docker Runner.
Checks Docker installation, automatically launches Docker Desktop if stopped,
and starts the interactive GeoChip container.
"""

import sys
from main import run_via_docker

if __name__ == "__main__":
    if "-h" in sys.argv or "--help" in sys.argv:
        print("Usage: python run_docker.py")
        print("\nAutomated Docker runner for GeoChip. Checks Docker installation,")
        print("launches Docker Desktop if stopped, and runs the interactive container.")
        sys.exit(0)
    run_via_docker()
