# investigate-ortools

Automated infrastructure to bisect the or-tools regression affecting SLOTHY.

## Structure

```
investigate-ortools/
├── flake.nix              # Nix dev shell with build toolchain
├── scripts/
│   ├── build_ortools.py   # Build or-tools at a commit, create venv
│   ├── run_slothy.py      # Run SLOTHY example 3x, capture timing & outcome
│   └── bisect.py          # Orchestrate full git bisect workflow
├── slothy/                # git submodule → upstream SLOTHY
└── or-tools/              # git submodule → upstream or-tools
```

## Setup

Enter the Nix shell (installs cmake, ninja, swig, python3, gcc, git):

```bash
nix develop
```

Initialize submodules (first time only):

```bash
git submodule update --init --recursive
```

## Usage

Run the full automated bisect between `v9.7` (good) and `v9.8` (bad):

```bash
python3 scripts/bisect.py --good v9.7 --bad v9.8 --runs 3 --timeout 300
```

Options:
- `--good`: Known-good tag/commit (default: `v9.7`)
- `--bad`: Known-bad tag/commit (default: `v9.8`)
- `--runs`: Number of test runs per commit (default: 3)
- `--timeout`: SLOTHY solver timeout per CP-SAT call in seconds (default: 300)
- `--hard-timeout`: Whole-process timeout per benchmark run; default is `max(3600, timeout*20)`, and `0` disables it
- `--jobs`, `-j`: Build parallelism (default: all cores minus one)
- `--skip-boundaries`: Skip the initial boundary tests (use with care)

## How it works

1. **Boundary characterization**: Builds `v9.7` and `v9.8`, runs the failing SLOTHY example (`ntt_dilithium_123_45678_a55`) 3 times each.
2. **Classification**:
   - **BAD** if any run fails with `BinarySearchLimitException` / `No solution found`
   - **BAD** (fallback) if all runs pass but median time is >= 1.3x the `v9.7` median
   - **GOOD** otherwise
   - **SKIP** on unexpected failures (build errors, etc.)
3. **Bisect loop**: `git bisect` checks out intermediate commits; each is built and tested.
4. **Cleanup**: Build directories and per-commit venvs are deleted after testing to save disk space.
5. **Results**: Everything is logged under `results/<commit>/result.json`. The final `results/bisect.log` and `results/bad_commit.txt` identify the culprit.

## Notes

- or-tools is built with `BUILD_DEPS=ON`, so it automatically fetches its pinned abseil/protobuf/re2/etc. for each commit. The Nix flake only provides the host toolchain.
- SCIP support is disabled (`USE_SCIP=OFF`) because SLOTHY exercises CP-SAT only, and building GSCIP can fail on newer hardened compilers.
- Python build-time modules such as `mypy_protobuf` are installed into the per-commit venv before CMake configure. The build points CMake at that venv and disables OR-Tools' `FETCH_PYTHON_DEPS` path to avoid `pip --user` writes into an immutable Nix Python.
- Historical or-tools commits that fetch `pybind11_protobuf` from `main` are patched during the build to use a fixed commit and skip the now-fragile local patch. Override the pin with `ORTOOLS_PYBIND11_PROTOBUF_TAG=<commit>` if needed.
- SLOTHY is run directly from the checked-out submodule; only its Python runtime dependencies are installed into the per-commit venv.
- Configure/build logs are written to `results/<commit>/configure.log`, `build.log`, and, after build failures, `build-verbose-retry.log`.
- Each commit rebuild takes 15–30 minutes on a typical x86_64 machine. The full bisect (~8 steps) will run overnight.
- The target machine for evaluation is x86_64 Debian Linux.
