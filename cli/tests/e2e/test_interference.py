"""Spec §7 metric 5: plain-uv interference never corrupts uvloom state.

Two halves:

1. Foreign-.venv guard (spec req 9): after ``uvloom sync``, a plain
   ``uv sync`` (or, if uv leaves the symlink alone, a manually planted real
   ``.venv`` directory) makes the next ``uvloom sync`` refuse with the exact
   documented message; ``uvloom sync --force`` recovers.
2. ``uvloom add`` (UV_NO_SYNC behavior): adding a real tiny package must not
   create or mutate a mutable ``.venv``, must invalidate the marker key, print
   the out-of-date hint, and rebuild with the added package on the next run.
"""

import json
import shutil
import subprocess

GUARD_MSG = ".venv exists and is not managed by uvloom — remove it or run 'uvloom sync --force'"
HINT_MSG = "environment out of date — run 'uvloom sync'"


def _write_local_package(project):
    pkg = project / "local-cowsay"
    pkg.mkdir()
    (pkg / "pyproject.toml").write_text(
        """
[build-system]
requires = []
build-backend = "local_cowsay"
backend-path = ["."]

[project]
name = "local-cowsay"
version = "0.1.0"
requires-python = ">=3.11"
""".lstrip()
    )
    (pkg / "local_cowsay.py").write_text(
        """
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

NAME = "local_cowsay"
VERSION = "0.1.0"
DIST_INFO = f"{NAME}-{VERSION}.dist-info"
METADATA = (
    "Metadata-Version: 2.1\\n"
    "Name: local-cowsay\\n"
    "Version: 0.1.0\\n"
)
WHEEL = (
    "Wheel-Version: 1.0\\n"
    "Generator: local-cowsay\\n"
    "Root-Is-Purelib: true\\n"
    "Tag: py3-none-any\\n"
)


def moo():
    return "moo"


def prepare_metadata_for_build_wheel(metadata_directory, config_settings=None):
    dist_info = Path(metadata_directory) / DIST_INFO
    dist_info.mkdir()
    (dist_info / "METADATA").write_text(METADATA)
    (dist_info / "WHEEL").write_text(WHEEL)
    return DIST_INFO


def build_wheel(wheel_directory, config_settings=None, metadata_directory=None):
    wheel = Path(wheel_directory) / f"{NAME}-{VERSION}-py3-none-any.whl"
    with ZipFile(wheel, "w", ZIP_DEFLATED) as zf:
        zf.writestr(
            ZipInfo("local_cowsay.py", date_time=(1980, 1, 1, 0, 0, 0)),
            Path(__file__).read_bytes(),
            compress_type=ZIP_DEFLATED,
        )
        zf.writestr(f"{DIST_INFO}/METADATA", METADATA)
        zf.writestr(f"{DIST_INFO}/WHEEL", WHEEL)
        zf.writestr(f"{DIST_INFO}/RECORD", "")
    return wheel.name


def prepare_metadata_for_build_editable(metadata_directory, config_settings=None):
    return prepare_metadata_for_build_wheel(metadata_directory, config_settings)


def build_editable(wheel_directory, config_settings=None, metadata_directory=None):
    return build_wheel(wheel_directory, config_settings, metadata_directory)
""".lstrip()
    )
    return pkg


def _is_store_symlink(venv) -> bool:
    return venv.is_symlink() and str(venv.resolve()).startswith("/nix/store/")


def test_foreign_venv_guard(make_project, run_uvloom, clean_env):
    project = make_project("templates/simple")
    run_uvloom(project, "sync", check=True, timeout=3600)
    venv = project / ".venv"
    assert _is_store_symlink(venv)

    # Plain uv sync, pointed at the store python so uv needn't download one.
    marker = json.loads((project / ".venv-uvloom.json").read_text())
    env = clean_env()
    if marker.get("interpreter"):
        env["UV_PYTHON"] = marker["interpreter"]
    subprocess.run(
        ["uv", "sync"], cwd=project, env=env, capture_output=True, text=True, timeout=600
    )

    if not venv.exists() or _is_store_symlink(venv):
        # uv refused / left the link intact — plant a foreign dir explicitly
        # so the guard branch is exercised deterministically.
        if venv.is_symlink():
            venv.unlink()
        venv.mkdir()
        (venv / "pyvenv.cfg").write_text("home = /nowhere\n")
    assert not _is_store_symlink(venv), ".venv should now be foreign"

    res = run_uvloom(project, "sync", timeout=600)
    assert res.returncode == 1, f"expected guard failure, got rc={res.returncode}"
    assert GUARD_MSG in res.stderr, f"missing guard message; stderr:\n{res.stderr}"

    # --force recovers: foreign dir removed, store symlink restored.
    run_uvloom(project, "sync", "--force", check=True, timeout=3600)
    assert _is_store_symlink(venv), ".venv not restored to a store symlink by --force"


def test_add_never_mutates_venv(make_project, run_uvloom):
    project = make_project("templates/simple")
    run_uvloom(project, "sync", check=True, timeout=3600)
    venv = project / ".venv"
    marker_path = project / ".venv-uvloom.json"
    assert _is_store_symlink(venv)
    target_before = venv.resolve()
    assert "key" in json.loads(marker_path.read_text())

    pkg = _write_local_package(project)
    res = run_uvloom(project, "add", f"./{pkg.name}", check=True, timeout=600)

    # .venv untouched: still the exact same existing immutable store symlink.
    assert venv.exists(), "'uvloom add' deleted .venv"
    assert venv.is_symlink(), "'uvloom add' replaced .venv with a real directory"
    assert _is_store_symlink(venv), "'uvloom add' replaced the store symlink"
    assert venv.resolve() == target_before, "'uvloom add' changed the .venv target"

    # Marker invalidated (key dropped) and hint printed.
    marker = json.loads(marker_path.read_text())
    assert "key" not in marker, "'uvloom add' did not invalidate the env key"
    assert HINT_MSG in res.stderr, f"missing out-of-date hint; stderr:\n{res.stderr}"

    # The next run rebuilds the invalidated environment and uses the new dependency.
    rebuilt = run_uvloom(
        project,
        "run",
        "--",
        "python",
        "-c",
        "import local_cowsay; print(local_cowsay.moo())",
        check=True,
        timeout=3600,
    )
    assert rebuilt.stdout.strip() == "moo", (
        "rebuilt environment could not use the added local package; "
        f"stdout:\n{rebuilt.stdout}\nstderr:\n{rebuilt.stderr}"
    )

    # uv actually recorded the dependency (passthrough worked).
    assert "local-cowsay" in (project / "pyproject.toml").read_text()
    assert shutil.which("uv") is not None  # sanity: real uv was on PATH
