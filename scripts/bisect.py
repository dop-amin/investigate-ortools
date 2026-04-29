#!/usr/bin/env python3
"""Orchestrate a git bisect between two or-tools tags/commits to find the SLOTHY regression."""

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.resolve()
OR_TOOLS_DIR = REPO_ROOT / "or-tools"
RESULTS_DIR = REPO_ROOT / "results"
SCRIPTS_DIR = REPO_ROOT / "scripts"

sys.path.insert(0, str(SCRIPTS_DIR))
import build_ortools
import run_slothy


def git(cmd, cwd=OR_TOOLS_DIR, check=True):
    """Run a git command inside the or-tools submodule."""
    full = ["git"] + cmd
    print(f"  > {' '.join(full)}", flush=True)
    return subprocess.run(full, cwd=cwd, check=check, capture_output=True, text=True)


def classify(summary: dict, baseline_median: float) -> str:
    """Classify a benchmark summary as 'good', 'bad', or 'skip'."""
    # Any hard failure indicating the solver gave up -> definitely bad
    if summary["any_no_solution"] or summary["any_binary_search_limit"]:
        return "bad"

    # If it failed for an unknown reason, we can't classify -> skip
    if summary["any_failed"]:
        return "skip"

    # All runs succeeded. Use timing criterion.
    if baseline_median > 0 and summary["median_elapsed"] >= 1.3 * baseline_median:
        return "bad"

    return "good"


def test_commit(commit: str, args) -> dict:
    """Build or-tools at *commit* and run the SLOTHY benchmark."""
    commit_dir = RESULTS_DIR / commit
    commit_dir.mkdir(parents=True, exist_ok=True)

    # Build
    print(f"\n{'=' * 60}")
    print(f"Building or-tools @ {commit}")
    print(f"{'=' * 60}")
    python_path = build_ortools.build(commit, args.jobs)

    # Run benchmark
    print(f"\n{'=' * 60}")
    print(f"Running SLOTHY benchmark @ {commit}")
    print(f"{'=' * 60}")
    out_json = commit_dir / "result.json"
    summary = run_slothy.run_benchmark(python_path, args.runs, args.timeout)

    with open(out_json, "w") as f:
        json.dump(summary, f, indent=2)

    # Clean up venv to save disk space
    venv_dir = RESULTS_DIR / f"venv-{commit}"
    if venv_dir.exists():
        shutil.rmtree(venv_dir)

    return summary


def main():
    parser = argparse.ArgumentParser(description="Bisect or-tools regression")
    parser.add_argument("--good", default="v9.7", help="Known-good tag or commit")
    parser.add_argument("--bad", default="v9.8", help="Known-bad tag or commit")
    parser.add_argument("--runs", type=int, default=3, help="Runs per commit")
    parser.add_argument("--timeout", type=int, default=300, help="Timeout per run (seconds)")
    parser.add_argument("--jobs", "-j", type=int, default=max(1, os.cpu_count() - 1),
                        help="CMake build parallelism")
    parser.add_argument("--skip-boundaries", action="store_true",
                        help="Skip boundary testing and go straight to bisect (use with care)")
    args = parser.parse_args()

    RESULTS_DIR.mkdir(exist_ok=True)

    # Ensure submodules are populated
    if not (REPO_ROOT / "slothy" / "example.py").exists():
        print("Initializing git submodules...")
        subprocess.run(["git", "submodule", "update", "--init", "--recursive"],
                       cwd=REPO_ROOT, check=True)

    baseline_median = 0.0

    if not args.skip_boundaries:
        # Test GOOD boundary
        print(f"\n{'=' * 60}")
        print("Testing GOOD boundary")
        print(f"{'=' * 60}")
        good_summary = test_commit(args.good, args)
        baseline_median = good_summary["median_elapsed"]
        print(f"\nGOOD ({args.good}): median={baseline_median}s, "
              f"any_failed={good_summary['any_failed']}, "
              f"any_no_solution={good_summary['any_no_solution']}")

        # Test BAD boundary
        print(f"\n{'=' * 60}")
        print("Testing BAD boundary")
        print(f"{'=' * 60}")
        bad_summary = test_commit(args.bad, args)
        print(f"\nBAD ({args.bad}): median={bad_summary['median_elapsed']}s, "
              f"any_failed={bad_summary['any_failed']}, "
              f"any_no_solution={bad_summary['any_no_solution']}")

        # Decide whether to proceed
        if not bad_summary["any_no_solution"] and not bad_summary["any_binary_search_limit"]:
            if not bad_summary["any_failed"]:
                if baseline_median > 0 and bad_summary["median_elapsed"] < 1.3 * baseline_median:
                    print("\n" + "!" * 60)
                    print("WARNING: BAD boundary does NOT reproduce the regression.")
                    print("The test passes and is not significantly slower on this machine.")
                    print("Bisect aborted.")
                    print("!" * 60)
                    return
            else:
                print("\nBAD boundary failed, but not with the expected UNKNOWN / no-solution pattern.")
                print("Will attempt bisect anyway; some commits may be classified as 'skip'.")
    else:
        print("Skipping boundary tests (--skip-boundaries).")

    # Start bisect
    print(f"\n{'=' * 60}")
    print("Starting git bisect")
    print(f"{'=' * 60}")

    git(["bisect", "start"])
    git(["bisect", "good", args.good])
    git(["bisect", "bad", args.bad])

    last_commit = None
    iteration = 0

    try:
        while True:
            iteration += 1
            r = git(["rev-parse", "HEAD"])
            commit = r.stdout.strip()

            if commit == last_commit:
                print("\nBisect converged (same commit as last iteration).")
                break
            last_commit = commit

            print(f"\n{'=' * 60}")
            print(f"Bisect iteration {iteration}: {commit}")
            print(f"{'=' * 60}")

            # If we already tested this commit during boundaries, reuse results
            commit_dir = RESULTS_DIR / commit
            cached = commit_dir / "result.json"
            if cached.exists():
                print("Using cached results from boundary test.")
                with open(cached) as f:
                    summary = json.load(f)
            else:
                summary = test_commit(commit, args)

            classification = classify(summary, baseline_median)
            print(f"Classification: {classification.upper()}")

            if classification == "good":
                git(["bisect", "good"])
            elif classification == "bad":
                git(["bisect", "bad"])
            else:
                git(["bisect", "skip"])

    except subprocess.CalledProcessError as e:
        # git bisect exits with non-zero when it finishes or aborts
        print(f"\ngit bisect exited (this is usually expected when finished).")
        if e.stdout:
            print(e.stdout)
        if e.stderr:
            print(e.stderr)

    # Extract and report the first bad commit
    print(f"\n{'=' * 60}")
    print("Bisect finished")
    print(f"{'=' * 60}")

    try:
        r = git(["bisect", "log"], check=False)
        log_path = RESULTS_DIR / "bisect.log"
        with open(log_path, "w") as f:
            f.write(r.stdout)
        print(f"Bisect log saved to {log_path}")
    except Exception:
        pass

    try:
        r = git(["bisect", "reset"])
    except subprocess.CalledProcessError:
        pass

    # Try to find the first bad commit from the log
    try:
        with open(RESULTS_DIR / "bisect.log") as f:
            log = f.read()
        for line in log.splitlines():
            if line.startswith("# first bad commit:"):
                bad_commit = line.split(":", 1)[1].strip()
                print(f"\n>>> FIRST BAD COMMIT: {bad_commit}")
                with open(RESULTS_DIR / "bad_commit.txt", "w") as f:
                    f.write(bad_commit + "\n")
                break
    except Exception:
        print("Could not extract first bad commit automatically.")

    print("\nAll results are in the 'results/' directory.")


if __name__ == "__main__":
    main()
