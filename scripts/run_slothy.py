#!/usr/bin/env python3
"""Run the SLOTHY failing example 3 times and capture timing + outcome."""

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.resolve()
SLOTHY_EXAMPLE = REPO_ROOT / "slothy" / "example.py"
RESULTS_DIR = REPO_ROOT / "results"

# The example name that historically triggers the regression.
EXAMPLE_NAME = "ntt_dilithium_123_45678_a55"


def run_once(python_path: str, timeout: int):
    """Execute one run of the example and return structured metrics."""
    start = time.monotonic()
    cmd = [
        python_path,
        str(SLOTHY_EXAMPLE),
        "--examples", EXAMPLE_NAME,
        "--timeout", str(timeout),
    ]
    try:
        proc = subprocess.run(
            cmd,
            cwd=REPO_ROOT / "slothy",
            capture_output=True,
            text=True,
            timeout=timeout + 60,  # hard grace period for teardown / log flushing
        )
    except subprocess.TimeoutExpired as exc:
        elapsed = time.monotonic() - start
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode(errors="replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode(errors="replace")
        combined = stdout + "\n" + stderr
        return {
            "success": False,
            "returncode": None,
            "elapsed_seconds": round(elapsed, 2),
            "timed_out": True,
            "unknown": "UNKNOWN" in combined,
            "binary_search_limit": "BinarySearchLimitException" in combined,
            "no_solution": "No solution found" in combined or "SlothyException" in combined,
            "optimization_times": [],
            "reported_total_seconds": None,
            "stdout_tail": stdout[-4000:] if len(stdout) > 4000 else stdout,
            "stderr_tail": stderr[-4000:] if len(stderr) > 4000 else stderr,
        }

    elapsed = time.monotonic() - start

    stdout = proc.stdout or ""
    stderr = proc.stderr or ""
    combined = stdout + "\n" + stderr

    failed = proc.returncode != 0
    unknown = "UNKNOWN" in combined
    binary_search_limit = "BinarySearchLimitException" in combined
    no_solution = "No solution found" in combined or "SlothyException" in combined

    # Try to extract per-optimization times logged by SLOTHY
    time_matches = re.findall(r"Optimization took ([\d.]+)s", combined)
    opt_times = [float(t) for t in time_matches]

    # Also capture the total time SLOTHY itself may report
    total_match = re.search(r"Total time: ([\d.]+)s", combined)
    reported_total = float(total_match.group(1)) if total_match else None

    return {
        "success": not failed,
        "returncode": proc.returncode,
        "elapsed_seconds": round(elapsed, 2),
        "timed_out": False,
        "unknown": unknown,
        "binary_search_limit": binary_search_limit,
        "no_solution": no_solution,
        "optimization_times": opt_times,
        "reported_total_seconds": reported_total,
        "stdout_tail": stdout[-4000:] if len(stdout) > 4000 else stdout,
        "stderr_tail": stderr[-4000:] if len(stderr) > 4000 else stderr,
    }


def run_benchmark(python_path: str, runs: int, timeout: int):
    """Run the benchmark *runs* times and produce a summary."""
    if runs < 1:
        raise ValueError("runs must be at least 1")

    results = []
    for i in range(runs):
        print(f"\n=== Run {i + 1}/{runs} ===", flush=True)
        result = run_once(python_path, timeout)
        results.append(result)
        print(
            f"  success={result['success']}, elapsed={result['elapsed_seconds']}s, "
            f"unknown={result['unknown']}, binary_search_limit={result['binary_search_limit']}",
            flush=True,
        )

    sorted_elapsed = sorted(r["elapsed_seconds"] for r in results)
    median_elapsed = sorted_elapsed[len(sorted_elapsed) // 2]

    summary = {
        "python_path": python_path,
        "example": EXAMPLE_NAME,
        "runs": results,
        "median_elapsed": round(median_elapsed, 2),
        "min_elapsed": round(sorted_elapsed[0], 2),
        "max_elapsed": round(sorted_elapsed[-1], 2),
        "any_failed": any(not r["success"] for r in results),
        "any_timed_out": any(r["timed_out"] for r in results),
        "any_unknown": any(r["unknown"] for r in results),
        "any_binary_search_limit": any(r["binary_search_limit"] for r in results),
        "any_no_solution": any(r["no_solution"] for r in results),
    }
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Benchmark SLOTHY example")
    parser.add_argument("python_path", help="Path to python in the or-tools venv")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--out", "-o", help="JSON output file")
    args = parser.parse_args()

    summary = run_benchmark(args.python_path, args.runs, args.timeout)

    if args.out:
        with open(args.out, "w") as f:
            json.dump(summary, f, indent=2)
        print(f"\nResults written to {args.out}")
    else:
        print(json.dumps(summary, indent=2))

    sys.exit(1 if summary["any_failed"] else 0)
