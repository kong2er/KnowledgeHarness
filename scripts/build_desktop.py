"""Build standalone executable for KnowledgeHarness launcher (PyInstaller)."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def _current_git_commit() -> str:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(ROOT),
            text=True,
        ).strip()
    except Exception:
        return "unknown"
    return out or "unknown"


def main() -> None:
    parser = argparse.ArgumentParser(description="Build KnowledgeHarness desktop executable")
    parser.add_argument("--name", default="KnowledgeHarness", help="Executable name")
    parser.add_argument(
        "--windowed",
        action="store_true",
        help="Build as windowed app (no console window)",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Run PyInstaller with --clean to rebuild from a clean cache",
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
    if args.clean:
        cmd.append("--clean")
    if args.windowed:
        cmd.append("--windowed")

    build_started = datetime.now(timezone.utc)
    print("[build]", " ".join(cmd))
    subprocess.run(cmd, cwd=str(ROOT), check=True)

    dist_dir = ROOT / "dist"
    native_target = dist_dir / args.name
    if sys.platform.startswith("win"):
        native_target = native_target.with_suffix(".exe")

    if not native_target.exists():
        raise SystemExit(f"build finished but output not found: {native_target}")

    # Explicitly warn about stale cross-platform artifacts. This avoids
    # confusion like: code changed but dist/<name>.exe timestamp didn't move
    # when building on Linux/macOS.
    cross_target = dist_dir / args.name
    if sys.platform.startswith("win"):
        cross_target = dist_dir / f"{args.name}"
    else:
        cross_target = dist_dir / f"{args.name}.exe"
    if cross_target.exists() and cross_target != native_target:
        cross_mtime = datetime.fromtimestamp(cross_target.stat().st_mtime, tz=timezone.utc)
        if cross_mtime < build_started:
            print(
                "[warn] stale cross-platform artifact detected:",
                cross_target,
            )
            print(
                "[warn] current platform is",
                sys.platform,
                "so only",
                native_target.name,
                "is rebuilt.",
            )

    build_info = {
        "name": args.name,
        "platform": sys.platform,
        "python": sys.version.split()[0],
        "windowed": bool(args.windowed),
        "clean_build": bool(args.clean),
        "built_at_utc": datetime.now(timezone.utc).isoformat(),
        "git_commit": _current_git_commit(),
        "output_path": str(native_target.resolve()),
        "output_size_bytes": int(native_target.stat().st_size),
    }
    info_path = dist_dir / f"{args.name}.buildinfo.json"
    info_path.write_text(
        json.dumps(build_info, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print(f"[ok] built: {native_target}")
    print(f"[ok] build info: {info_path}")


if __name__ == "__main__":
    main()
