#!/usr/bin/env python3
"""Build and benchmark one or-tools commit."""

import argparse
import json
import os
import shutil
import sys
import traceback
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.resolve()
RESULTS_DIR = REPO_ROOT / "results"
SCRIPTS_DIR = REPO_ROOT / "scripts"

sys.path.insert(0, str(SCRIPTS_DIR))
import build_ortools
import run_slothy


def evaluate(args) -> dict:
    commit_name = build_ortools._safe_name(args.commit)
    commit_dir = RESULTS_DIR / commit_name
    commit_dir.mkdir(parents=True, exist_ok=True)
    out_json = Path(args.out) if args.out else commit_dir / "result.json"

    cp_sat_params = dict(args.cp_sat_param)
    python_path = args.python_path

    if python_path is None:
        print(f"\n{'=' * 60}")
        print(f"Building or-tools @ {args.commit}")
        print(f"{'=' * 60}")
        try:
            python_path = build_ortools.build(args.commit, args.jobs)
        except Exception as exc:
            summary = {
                "commit": args.commit,
                "build_error": {
                    "type": type(exc).__name__,
                    "message": str(exc),
                    "traceback_tail": traceback.format_exc()[-4000:],
                },
                "run_error": None,
                "runs": [],
                "median_elapsed": 0.0,
                "any_failed": True,
                "any_timed_out": False,
                "any_unknown": False,
                "any_binary_search_limit": False,
                "any_no_solution": False,
                "cp_sat_params": cp_sat_params,
            }
            out_json.parent.mkdir(parents=True, exist_ok=True)
            out_json.write_text(json.dumps(summary, indent=2), encoding="utf-8")
            return summary

    print(f"\n{'=' * 60}")
    print(f"Running SLOTHY benchmark @ {args.commit}")
    print(f"{'=' * 60}")
    try:
        summary = run_slothy.run_benchmark(
            python_path,
            args.runs,
            args.timeout,
            args.hard_timeout,
            cp_sat_params=cp_sat_params,
        )
        summary["commit"] = args.commit
        summary["build_error"] = None
        summary["run_error"] = None
    except Exception as exc:
        summary = {
            "commit": args.commit,
            "python_path": python_path,
            "build_error": None,
            "run_error": {
                "type": type(exc).__name__,
                "message": str(exc),
                "traceback_tail": traceback.format_exc()[-4000:],
            },
            "runs": [],
            "median_elapsed": 0.0,
            "any_failed": True,
            "any_timed_out": False,
            "any_unknown": False,
            "any_binary_search_limit": False,
            "any_no_solution": False,
            "cp_sat_params": cp_sat_params,
        }

    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"\nResults written to {out_json}")

    if not args.keep_venv and args.python_path is None:
        venv_dir = RESULTS_DIR / f"venv-{commit_name}"
        if venv_dir.exists():
            shutil.rmtree(venv_dir)

    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate one or-tools commit")
    parser.add_argument("commit", help="or-tools commit hash or tag")
    parser.add_argument("--runs", type=int, default=3, help="Runs for this commit")
    parser.add_argument(
        "--timeout",
        type=int,
        default=300,
        help="SLOTHY solver timeout per CP-SAT call, in seconds",
    )
    parser.add_argument(
        "--hard-timeout",
        type=int,
        default=None,
        help="Whole-process timeout per run in seconds; default is max(3600, timeout*20). Use 0 to disable.",
    )
    parser.add_argument(
        "--jobs",
        "-j",
        type=int,
        default=max(1, os.cpu_count() - 1),
        help="CMake build parallelism",
    )
    parser.add_argument(
        "--python-path",
        help="Reuse an existing venv Python instead of rebuilding the commit",
    )
    parser.add_argument(
        "--keep-venv",
        action="store_true",
        help="Keep the per-commit venv after the benchmark",
    )
    parser.add_argument("--out", "-o", help="JSON output path")
    parser.add_argument(
        "--cp-sat-param",
        action="append",
        type=run_slothy.parse_cp_sat_param,
        default=[],
        metavar="KEY=VALUE",
        help="Set a CP-SAT parameter on every SLOTHY CpSolver instance.",
    )
    args = parser.parse_args()

    RESULTS_DIR.mkdir(exist_ok=True)
    summary = evaluate(args)
    return 1 if summary.get("any_failed") else 0


if __name__ == "__main__":
    raise SystemExit(main())
