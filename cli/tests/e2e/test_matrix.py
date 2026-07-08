"""Spec §7 metric 1: E2E matrix over templates/ and examples/ (flakes removed).

For each fixture: ``uvloom lock`` (only when the lock is missing — all
fixtures ship one), ``uvloom sync``, then a project-appropriate command whose
output is asserted.

Commands were picked by inspecting each fixture:

- templates/{simple,editable,pytest}: identical smiley-plot console script
  printing ``:) world`` (editable differs only in build-requires ``editables``).
- examples/python_package: native-wheel coverage — ``plot-smiley`` runs
  meshpy triangulation + matplotlib PNG rendering and prints the output path.
- examples/non_package_app: virtual root (``package = false``) — run its
  entry ``python app.py`` which prints ``ok`` via a local ``utils`` import.
- examples/marimo_app: a PEP 723 script (no pyproject.toml), so sync is
  skipped and ``uvloom run marimo_app.py`` executes the app headlessly. Its
  cells emit mo.md/mo.ui.table outputs, which marimo does not print when a
  notebook runs as a script — stdout is legitimately empty. The cell pins
  the script cache marker as its artifact and test_marimo_import_probe
  imports marimo from the built venv directly.
- examples/simple_script is covered by the dedicated PEP 723 test
  (test_pep723.py) and deliberately omitted here.
"""

import json
import subprocess

import pytest

# (fixture, uvloom argv, stdout fragment or None, produced artifact or None)
MATRIX = [
    pytest.param(
        "templates/simple",
        ["run", "--", "smiley-plot"],
        ":) world",
        None,
        id="templates-simple",
    ),
    pytest.param(
        "templates/editable",
        ["run", "--", "smiley-plot"],
        ":) world",
        None,
        id="templates-editable",
    ),
    pytest.param(
        "templates/pytest",
        ["run", "--", "smiley-plot"],
        ":) world",
        None,
        id="templates-pytest",
    ),
    pytest.param(
        "examples/python_package",
        ["run", "--", "plot-smiley", "--output", "smiley-e2e.png"],
        "smiley-e2e.png",
        "smiley-e2e.png",
        id="examples-python_package",
    ),
    pytest.param(
        "examples/non_package_app",
        ["run", "--", "python", "app.py"],
        "ok",
        None,
        id="examples-non_package_app",
    ),
    pytest.param(
        "examples/marimo_app",
        ["run", "marimo_app.py"],
        None,
        # The app prints nothing (see module docstring); the script cache
        # marker written by driver.build_script_venv is the positive signal
        # that the venv actually built.
        "marimo_app.py.uvloom.json",
        id="examples-marimo_app",
    ),
]


@pytest.mark.slow
@pytest.mark.parametrize("fixture,cmd,expect,artifact", MATRIX)
def test_matrix(fixture, cmd, expect, artifact, make_project, run_uvloom):
    project = make_project(fixture)
    is_script_fixture = not (project / "pyproject.toml").exists()

    if not is_script_fixture:
        if not (project / "uv.lock").exists():
            run_uvloom(project, "lock", check=True, timeout=600)
        run_uvloom(project, "sync", check=True, timeout=3600)
        assert (project / ".venv").is_symlink(), ".venv must be a GC-rooted symlink"
        assert (project / ".venv-uvloom.json").is_file(), "marker file must exist"

    res = run_uvloom(project, *cmd, check=True, timeout=3600)
    if expect is not None:
        assert expect in res.stdout, (
            f"expected {expect!r} in stdout of uvloom {' '.join(cmd)}\n"
            f"--- stdout ---\n{res.stdout}\n--- stderr ---\n{res.stderr}"
        )
    else:
        # No stdout contract (marimo): the happy path must at least be free
        # of interpreter failures leaking to stderr.
        assert "Traceback" not in res.stderr and "ImportError" not in res.stderr, (
            f"--- stderr ---\n{res.stderr}"
        )
    if artifact is not None:
        assert (project / artifact).is_file(), f"{artifact} not produced"

    # Metric 8 spot-check: never a raw Nix eval trace on the happy path.
    assert "while evaluating" not in res.stderr


@pytest.mark.slow
def test_marimo_import_probe(make_project, run_uvloom):
    """The marimo cell above only proves exit 0 + marker; probe the built
    script venv directly. A MATRIX param cannot express this: ``uvloom run
    -- python -c ...`` needs a project root, and the PEP 723 fixture has no
    pyproject.toml."""
    project = make_project("examples/marimo_app")
    run_uvloom(project, "run", "marimo_app.py", check=True, timeout=3600)

    marker = json.loads((project / "marimo_app.py.uvloom.json").read_text())
    res = subprocess.run(
        [
            f"{marker['store_path']}/bin/python",
            "-c",
            "import marimo; print(marimo.__name__)",
        ],
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert res.returncode == 0, f"--- stderr ---\n{res.stderr}"
    assert res.stdout.strip() == "marimo"
