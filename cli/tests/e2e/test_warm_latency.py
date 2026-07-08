"""Spec §7 metric 3: warm-path ``uvloom run`` latency.

Overhead = best-of-N ``uvloom run -- python -c pass`` minus best-of-N bare
``<venv python> -c pass``. Soft threshold (default 150 ms) warns. Hard
threshold is opt-in via ``UVLOOM_E2E_LAT_HARD_MS`` and fails when set.
Linux CI sets a deliberately generous 1000 ms hard limit to catch catastrophic
regressions without making normal runner variance flaky.
"""

import os
import subprocess
import time
import warnings

RUNS = 5
MEASURED_TIMEOUT = 60
WARMUP_TIMEOUT = 3600


def _best_of(n: int, argv: list[str], cwd, env: dict, timeout: int) -> float:
    best = float("inf")
    for _ in range(n):
        t0 = time.perf_counter()
        res = subprocess.run(
            argv,
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        elapsed = time.perf_counter() - t0
        assert res.returncode == 0, (
            f"{argv[0]} exited {res.returncode}\n{res.stdout}\n{res.stderr}"
        )
        best = min(best, elapsed)
    return best


def test_warm_run_latency(make_project, run_uvloom, uvloom_bin, clean_env, record_property):
    soft_ms = float(os.environ.get("UVLOOM_E2E_LAT_SOFT_MS", "150"))
    hard_ms_env = os.environ.get("UVLOOM_E2E_LAT_HARD_MS")
    hard_ms = float(hard_ms_env) if hard_ms_env is not None else None

    project = make_project("templates/simple")
    run_uvloom(project, "sync", check=True, timeout=3600)

    venv_python = os.path.realpath(project / ".venv" / "bin" / "python")
    assert os.access(venv_python, os.X_OK)
    env = clean_env({"REPO_ROOT": str(project)})

    # Warm both binaries once (page cache) before measuring.
    subprocess.run(
        [venv_python, "-c", "pass"],
        cwd=project,
        env=env,
        capture_output=True,
        timeout=WARMUP_TIMEOUT,
    )
    subprocess.run(
        [uvloom_bin, "run", "--", "python", "-c", "pass"],
        cwd=project,
        env=env,
        capture_output=True,
        text=True,
        timeout=WARMUP_TIMEOUT,
    )

    base = _best_of(RUNS, [venv_python, "-c", "pass"], project, env, MEASURED_TIMEOUT)
    warm = _best_of(
        RUNS,
        [uvloom_bin, "run", "--", "python", "-c", "pass"],
        project,
        env,
        MEASURED_TIMEOUT,
    )

    overhead_ms = (warm - base) * 1000.0
    record_property("warm_overhead_ms", round(overhead_ms, 1))
    record_property("baseline_ms", round(base * 1000.0, 1))

    if hard_ms is not None and overhead_ms > hard_ms:
        raise AssertionError(
            f"warm 'uvloom run' overhead {overhead_ms:.1f} ms exceeds hard "
            f"threshold {hard_ms:.0f} ms (baseline {base * 1000:.1f} ms)"
        )
    if overhead_ms > soft_ms:
        message = (
            f"warm 'uvloom run' overhead {overhead_ms:.1f} ms exceeds soft "
            f"threshold {soft_ms:.0f} ms"
        )
        if hard_ms is not None:
            message += f" (hard limit {hard_ms:.0f} ms)"
        warnings.warn(message, stacklevel=1)
