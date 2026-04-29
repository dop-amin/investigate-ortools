#!/usr/bin/env python3
"""Build or-tools at a specific commit and prepare an isolated venv with the wheel."""

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.resolve()
OR_TOOLS_DIR = REPO_ROOT / "or-tools"
SLOTHY_DIR = REPO_ROOT / "slothy"
RESULTS_DIR = REPO_ROOT / "results"
PYBIND11_PROTOBUF_TAG = os.environ.get(
    "ORTOOLS_PYBIND11_PROTOBUF_TAG",
    "f02a2b7653bc50eb5119d125842a3870db95d251",
)
SLOTHY_RUNTIME_DEPS = ["sympy==1.14.0", "unicorn==2.1.4"]
PYTHON_DEP_CONSTRAINTS = ["protobuf<=6.31.1"]


def run(cmd, cwd=None, check=True):
    """Run a shell command, echoing it first."""
    print(f"  > {' '.join(str(c) for c in cmd)}", flush=True)
    return subprocess.run(cmd, cwd=cwd, check=check, capture_output=False)


def _safe_name(ref: str) -> str:
    """Return a filesystem-safe name for a git ref."""
    return re.sub(r"[^A-Za-z0-9._-]+", "_", ref)


def _maybe_disable_pybind11_protobuf_patch(or_tools_dir: Path) -> None:
    """Pin pybind11_protobuf and remove its fragile moving-target patch.

    or-tools v9.7/v9.8 fetch pybind11_protobuf from the live ``main`` branch and
    then apply a local patch. That is not reproducible during a historical
    bisect because upstream ``main`` keeps moving. Pinning to a fixed commit and
    skipping the patch isolates the bisect to or-tools changes.
    """
    deps_file = or_tools_dir / "cmake" / "dependencies" / "CMakeLists.txt"
    if not deps_file.exists():
        print(f"  pybind11_protobuf workaround skipped: {deps_file} not found")
        return

    text = deps_file.read_text()
    if "pybind11_protobuf" not in text:
        print("  pybind11_protobuf workaround skipped: dependency not present")
        return

    updated = re.sub(
        r'(GIT_REPOSITORY\s+"https://github\.com/pybind/pybind11_protobuf\.git"\s*\n\s*)GIT_TAG\s+"[^"]+"',
        rf'\1GIT_TAG "{PYBIND11_PROTOBUF_TAG}"',
        text,
        count=1,
    )
    updated = re.sub(
        r'\n\s*PATCH_COMMAND\s+git apply --ignore-whitespace\s+("\$\{CMAKE_CURRENT_LIST_DIR\}/\.\./\.\./patches/pybind11_protobuf\.patch")',
        r"\n      # PATCH_COMMAND disabled by investigate-ortools: historical builds need a pinned upstream.",
        updated,
        count=1,
    )

    if updated == text:
        print("  pybind11_protobuf workaround made no changes")
        return

    deps_file.write_text(updated)
    print(f"  Pinned pybind11_protobuf to {PYBIND11_PROTOBUF_TAG} and disabled its patch")


def build(commit: str, jobs: int):
    """Checkout *commit*, build the Python wheel, install into a venv, return python path."""
    RESULTS_DIR.mkdir(exist_ok=True)
    commit_name = _safe_name(commit)

    # Use a completely isolated build directory per commit so there is zero
    # chance of stale FetchContent caches or patch artifacts from a previous
    # or-tools version.
    build_dir = RESULTS_DIR / f"build-{commit_name}"
    if build_dir.exists():
        shutil.rmtree(build_dir)

    # Also remove any legacy build directory that may have been left behind
    legacy_build = OR_TOOLS_DIR / "build"
    if legacy_build.exists():
        print(f"  Cleaning legacy build dir: {legacy_build}")
        shutil.rmtree(legacy_build)

    # 1. checkout commit (force to discard any local changes from prior builds)
    run(["git", "checkout", "-f", commit], cwd=OR_TOOLS_DIR)

    # The 'pybind11_protobuf' dependency in or-tools v9.7/v9.8 fetches from the
    # 'main' branch (a moving target) and applies a patch that frequently
    # breaks when upstream changes.  To avoid patch failures during bisecting,
    # we temporarily replace the live fetch with a fixed tag that is known to
    # compile without the patch (the patch was only needed for newer upstream
    # commits that broke the build).
    _maybe_disable_pybind11_protobuf_patch(OR_TOOLS_DIR)
    run([
        "cmake", "-S", str(OR_TOOLS_DIR), "-B", str(build_dir),
        "-DBUILD_PYTHON=ON",
        "-DCMAKE_BUILD_TYPE=Release",
        "-DBUILD_DEPS=ON",
    ])

    # 3. build the python_package target
    run([
        "cmake", "--build", str(build_dir),
        "--target", "python_package",
        "-j", str(jobs),
    ])

    # 4. locate the produced wheel
    wheel_candidates = list((build_dir / "python" / "dist").glob("*.whl"))
    if not wheel_candidates:
        wheel_candidates = list((build_dir / "python").glob("*.whl"))
    if not wheel_candidates:
        raise RuntimeError(f"No wheel found under {build_dir / 'python'}")
    wheel = wheel_candidates[0]
    print(f"Found wheel: {wheel}")

    # 5. create a fresh venv for this commit
    venv_dir = RESULTS_DIR / f"venv-{commit_name}"
    if venv_dir.exists():
        shutil.rmtree(venv_dir)
    run([sys.executable, "-m", "venv", str(venv_dir)])

    venv_python = venv_dir / "bin" / "python"
    venv_pip = venv_dir / "bin" / "pip"

    # 6. install wheel + SLOTHY in editable mode.  SLOTHY's metadata pins an
    # or-tools release from PyPI, so install it with --no-deps to preserve the
    # wheel built from the commit under test.
    run([str(venv_pip), "install", str(wheel), *PYTHON_DEP_CONSTRAINTS])
    run([str(venv_pip), "install", *SLOTHY_RUNTIME_DEPS])
    run([str(venv_pip), "install", "--no-deps", "-e", str(SLOTHY_DIR)])

    # 7. free disk space by removing the C++ build tree
    shutil.rmtree(build_dir)

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
