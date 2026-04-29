#!/usr/bin/env python3
"""Build or-tools at a specific commit and prepare an isolated venv with the wheel."""

import argparse
import glob
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.resolve()
OR_TOOLS_DIR = REPO_ROOT / "or-tools"
SLOTHY_DIR = REPO_ROOT / "slothy"
BUILD_DIR = OR_TOOLS_DIR / "build"
RESULTS_DIR = REPO_ROOT / "results"


def run(cmd, cwd=None, check=True):
    """Run a shell command, echoing it first."""
    print(f"  > {' '.join(str(c) for c in cmd)}", flush=True)
    return subprocess.run(cmd, cwd=cwd, check=check, capture_output=False)


def build(commit: str, jobs: int):
    """Checkout *commit*, build the Python wheel, install into a venv, return python path."""
    RESULTS_DIR.mkdir(exist_ok=True)

    # 1. checkout commit (force to discard any local changes from prior builds)
    run(["git", "checkout", "-f", commit], cwd=OR_TOOLS_DIR)

    # 2. clean previous build directory
    if BUILD_DIR.exists():
        shutil.rmtree(BUILD_DIR)

    # 3. configure (FetchContent will pull pinned deps automatically)
    run([
        "cmake", "-S", str(OR_TOOLS_DIR), "-B", str(BUILD_DIR),
        "-DBUILD_PYTHON=ON",
        "-DCMAKE_BUILD_TYPE=Release",
        "-DBUILD_DEPS=ON",
    ])

    # 4. build the python_package target
    run([
        "cmake", "--build", str(BUILD_DIR),
        "--target", "python_package",
        "-j", str(jobs),
    ])

    # 5. locate the produced wheel
    wheel_candidates = list((BUILD_DIR / "python" / "dist").glob("*.whl"))
    if not wheel_candidates:
        wheel_candidates = list((BUILD_DIR / "python").glob("*.whl"))
    if not wheel_candidates:
        raise RuntimeError(f"No wheel found under {BUILD_DIR / 'python'}")
    wheel = wheel_candidates[0]
    print(f"Found wheel: {wheel}")

    # 6. create a fresh venv for this commit
    venv_dir = RESULTS_DIR / f"venv-{commit}"
    if venv_dir.exists():
        shutil.rmtree(venv_dir)
    run([sys.executable, "-m", "venv", str(venv_dir)])

    venv_python = venv_dir / "bin" / "python"
    venv_pip = venv_dir / "bin" / "pip"

    # 7. install wheel + SLOTHY in editable mode
    run([str(venv_pip), "install", "--upgrade", "pip"])
    run([str(venv_pip), "install", str(wheel)])
    run([str(venv_pip), "install", "-e", str(SLOTHY_DIR)])

    # 8. free disk space by removing the C++ build tree
    shutil.rmtree(BUILD_DIR)

    print(f"\nBuild complete. Venv: {venv_dir}")
    print(f"Python: {venv_python}")
    return str(venv_python)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build or-tools at a commit")
    parser.add_argument("commit", help="Git commit hash or tag")
    parser.add_argument("--jobs", "-j", type=int, default=max(1, os.cpu_count() - 1))
    args = parser.parse_args()

    python_path = build(args.commit, args.jobs)
    print(python_path)
