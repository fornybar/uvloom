"""Shared fixtures for the uvloom CLI end-to-end suite (spec §7).

These tests run as plain pytest with network + nix available (CI-style),
never inside a nix build sandbox.

Environment knobs:

- ``UVLOOM_E2E_BIN``      — path to a prebuilt ``uvloom`` executable. When
  unset the session builds ``.#uvloom-cli`` itself via ``nix build``.
- ``UVLOOM_E2E_LAT_SOFT_MS`` — soft warm-latency threshold in ms (default
  150; exceeding it warns). ``UVLOOM_E2E_LAT_HARD_MS`` — opt-in hard
  threshold (no default; unset means never fail), see test_warm_latency.py.
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "slow: long-running E2E case (cold Nix builds, full matrix)"
    )


@pytest.fixture(scope="session", autouse=True)
def _require_nix():
    """Guard the whole suite: uvloom_bin runs a cold ``nix build`` and every
    case shells out to nix, so without it the session hard-errors after a
    long hang. Skip loudly instead."""
    if shutil.which("nix") is None:
        pytest.skip(
            "nix not on PATH — run the E2E suite via `just cli-e2e` "
            "(or `just cli-e2e-fast` for -m 'not slow')"
        )


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture(scope="session")
def uvloom_bin(tmp_path_factory) -> str:
    """Path of the uvloom executable under test.

    ``UVLOOM_E2E_BIN`` overrides; otherwise build ``.#uvloom-cli`` into a
    session tmp out-link (GC-rooted for the session's lifetime).
    """
    override = os.environ.get("UVLOOM_E2E_BIN")
    if override:
        p = Path(override).resolve()
        if not (p.is_file() and os.access(p, os.X_OK)):
            pytest.fail(f"UVLOOM_E2E_BIN={override} is not an executable file")
        return str(p)

    out_link = tmp_path_factory.mktemp("bin") / "uvloom-cli"
    subprocess.run(
        ["nix", "build", f"{REPO_ROOT}#uvloom-cli", "-o", str(out_link)],
        cwd=REPO_ROOT,
        check=True,
    )
    return str(out_link / "bin" / "uvloom")


def _clean_env(extra: dict | None = None) -> dict:
    """os.environ minus anything that could leak the harness venv into uvloom."""
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in ("VIRTUAL_ENV", "PYTHONPATH", "PYTHONHOME", "REPO_ROOT")
        and not k.startswith("UV_")
    }
    if extra:
        env.update(extra)
    return env


@pytest.fixture
def clean_env():
    """``clean_env(extra=None)`` — a cleaned copy of os.environ (see _clean_env)."""
    return _clean_env


@pytest.fixture
def make_project(tmp_path):
    """Copy ``templates/<t>`` or ``examples/<e>`` into tmp and de-flake it.

    Usage: ``project = make_project("templates/simple")``. The originals are
    never mutated; flake.nix + flake.lock are deleted from the copy so the
    fixture exercises the flake-less CLI workflow.
    """

    def _make(name: str, dest: Path | None = None) -> Path:
        src = REPO_ROOT / name
        assert src.is_dir(), f"unknown fixture {name!r} (expected under {REPO_ROOT})"
        dest = dest or (tmp_path / Path(name).name)
        shutil.copytree(src, dest)
        for f in ("flake.nix", "flake.lock"):
            (dest / f).unlink(missing_ok=True)
        return dest

    return _make


@pytest.fixture
def run_uvloom(uvloom_bin):
    """``run_uvloom(project, *args, env=None, timeout=1800, check=False)``.

    Runs uvloom with cwd=project, captured text output, and a cleaned
    environment (``env`` merged on top). ``check=True`` raises an
    AssertionError carrying full stdout/stderr on nonzero exit.
    """

    def _run(
        project: Path,
        *args: str,
        env: dict | None = None,
        timeout: int = 1800,
        check: bool = False,
    ) -> subprocess.CompletedProcess:
        res = subprocess.run(
            [uvloom_bin, *args],
            cwd=project,
            env=_clean_env(env),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if check and res.returncode != 0:
            raise AssertionError(
                f"uvloom {' '.join(args)} exited {res.returncode}\n"
                f"--- stdout ---\n{res.stdout}\n--- stderr ---\n{res.stderr}"
            )
        return res

    return _run
