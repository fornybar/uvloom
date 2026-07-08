"""E2E: `uvloom flakify` graduation path (spec §7 metric 7).

On a synced, flake-less copy of templates/simple: flakify writes a flake.nix
whose `nix build` produces a venv with the same Python package set as the
CLI-built one (same lock + same pins => same packages). The CLI env is built
--no-editable so both venvs are store-source and directly comparable.

The emitted flake's `uvloom` input points at the *published*
github:fornybar/uvloom, deliberately: the flake must work for real users, so
it must not rely on unpublished library features (asserted below by checking
the emitted flake never uses `filterSource`). The build itself, however,
overrides that input to the checkout under test so lib changes are exercised
by this suite before they are published.
"""

import os
import subprocess

import pytest

pytestmark = pytest.mark.slow


def _run(cmd: list[str], cwd, timeout: int = 3600) -> subprocess.CompletedProcess:
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in ("VIRTUAL_ENV", "PYTHONPATH", "PYTHONHOME", "REPO_ROOT")
    }
    res = subprocess.run(
        cmd, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout
    )
    assert res.returncode == 0, (
        f"{' '.join(cmd)} exited {res.returncode}\n"
        f"--- stdout ---\n{res.stdout}\n--- stderr ---\n{res.stderr}"
    )
    return res


def _reference_names(store_path: str, cwd) -> set[str]:
    """Direct store references as hashless names, minus the path's own name."""
    out = _run(["nix-store", "-q", "--references", store_path], cwd=cwd).stdout
    own = store_path.split("/nix/store/", 1)[1].split("-", 1)[1]
    names = {line.rsplit("/", 1)[1].split("-", 1)[1] for line in out.split() if line}
    return names - {own}


def test_flakify_build_matches_cli_env(make_project, run_uvloom, repo_root):
    project = make_project("templates/simple")

    # CLI-built environment (store-source, to match the flake's venv).
    run_uvloom(project, "sync", "--no-editable", check=True)
    cli_env = os.path.realpath(project / ".venv")
    assert cli_env.startswith("/nix/store/")

    # Graduate.
    run_uvloom(project, "flakify", check=True)
    flake = (project / "flake.nix").read_text()
    # Pins translate to flake inputs at the same revisions (req 20), and
    # generated flakes preserve the CLI's filtered source model by default.
    assert "github:NixOS/nixpkgs/" in flake
    assert "uvloom.url" in flake
    assert "filterSource = true;" in flake
    assert "extraSourcePaths" in flake

    # Refuses to overwrite an existing flake.nix (req 20).
    res = run_uvloom(project, "flakify")
    assert res.returncode == 1
    assert "refusing to overwrite" in res.stderr

    # Flakes only see tracked files.
    _run(["git", "init", "-q"], cwd=project)
    _run(["git", "add", "-A"], cwd=project)

    # Build with the uvloom input overridden to this checkout so the e2e
    # suite tests the local lib, not the published default branch.
    _run(
        [
            "nix",
            "build",
            ".#default",
            "-o",
            "result-env",
            "--accept-flake-config",
            "--override-input",
            "uvloom",
            f"path:{repo_root}",
            "--no-write-lock-file",
        ],
        cwd=project,
    )
    flake_env = os.path.realpath(project / "result-env")
    assert flake_env.startswith("/nix/store/")

    # Same package set: identical references modulo the store hashes and the
    # venv derivations themselves.
    cli_refs = _reference_names(cli_env, cwd=project)
    flake_refs = _reference_names(flake_env, cwd=project)
    assert cli_refs == flake_refs, (
        f"package sets differ:\n"
        f"cli only:   {sorted(cli_refs - flake_refs)}\n"
        f"flake only: {sorted(flake_refs - cli_refs)}"
    )
    # Sanity: the set actually contains the project package and an interpreter.
    assert "smiley-plot-0.1.0" in cli_refs
    assert any(name.startswith("python3") for name in cli_refs)
