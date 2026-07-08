"""Spec §7 metric 2: editable loop — source edit visible with ZERO Nix calls.

Nix is instrumented via a PATH shim directory: wrapper scripts for
nix / nix-build / nix-instantiate / nix-store append a line to a counter file
before exec'ing the real binary. A positive control (marker deleted, forcing
a rebuild) proves the shim actually intercepts uvloom's Nix invocations, then
the warm editable run must leave the counter empty.
"""

import os
import shutil
import stat
from pathlib import Path

SHIMMED = ("nix", "nix-build", "nix-instantiate", "nix-store")


def make_nix_shim(shim_dir: Path, counter: Path) -> dict:
    """Create shim wrappers; return env overrides putting them first on PATH."""
    shim_dir.mkdir(parents=True, exist_ok=True)
    counter.touch()
    for name in SHIMMED:
        real = shutil.which(name)
        if real is None:
            continue
        script = shim_dir / name
        script.write_text(
            "#!/usr/bin/env bash\n"
            f"printf '%s %s\\n' {name} \"$*\" >> \"{counter}\"\n"
            f'exec {real} "$@"\n'
        )
        script.chmod(script.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return {"PATH": f"{shim_dir}{os.pathsep}{os.environ.get('PATH', '')}"}


def test_editable_loop(tmp_path, make_project, run_uvloom):
    project = make_project("templates/simple")
    run_uvloom(project, "sync", check=True, timeout=3600)

    counter = tmp_path / "nix-calls.log"
    shim_env = make_nix_shim(tmp_path / "shim", counter)

    # Positive control: with the marker gone, sync MUST rebuild through the
    # shimmed nix-build — proving the shim sees uvloom's Nix invocations.
    (project / ".venv-uvloom.json").unlink()
    run_uvloom(project, "sync", env=shim_env, check=True, timeout=3600)
    control = counter.read_text()
    assert control.strip(), (
        "shim positive control failed: rebuild invoked no shimmed nix binary "
        "(is uvloom resolving nix off PATH?)"
    )
    counter.write_text("")  # reset

    # Edit a source file: editable venv must reflect it without any rebuild.
    src = project / "src" / "smiley_plot" / "__init__.py"
    src.write_text(
        'def smile(name="world"):\n'
        '    return f"EDITED {name}"\n'
        "\n\n"
        "def main():\n"
        "    print(smile())\n"
    )

    res = run_uvloom(project, "run", "--", "smiley-plot", env=shim_env, check=True)
    assert "EDITED world" in res.stdout, (
        f"editable venv did not reflect the source edit\n"
        f"--- stdout ---\n{res.stdout}\n--- stderr ---\n{res.stderr}"
    )
    calls = counter.read_text()
    assert calls == "", f"warm editable run invoked Nix:\n{calls}"
