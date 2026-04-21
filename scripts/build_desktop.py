"""Build standalone executable for KnowledgeHarness launcher (PyInstaller)."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    parser = argparse.ArgumentParser(description="Build KnowledgeHarness desktop executable")
    parser.add_argument("--name", default="KnowledgeHarness", help="Executable name")
    parser.add_argument(
        "--windowed",
        action="store_true",
        help="Build as windowed app (no console window)",
    )
    args = parser.parse_args()

    pyinstaller = shutil.which("pyinstaller")
    if not pyinstaller:
        raise SystemExit(
            "pyinstaller not found. Install it first: pip install pyinstaller"
        )

    cmd = [
        pyinstaller,
        "--noconfirm",
        "--onefile",
        "--name",
        args.name,
        "launch_app.py",
    ]
    if args.windowed:
        cmd.append("--windowed")

    print("[build]", " ".join(cmd))
    subprocess.run(cmd, cwd=str(ROOT), check=True)
    dist_path = ROOT / "dist" / args.name
    if sys.platform.startswith("win"):
        dist_path = dist_path.with_suffix(".exe")
    print(f"[ok] built: {dist_path}")


if __name__ == "__main__":
    main()
