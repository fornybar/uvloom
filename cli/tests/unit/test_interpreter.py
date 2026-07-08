"""interpreter.py: version request mapping + interpreter cache invalidation."""

import pytest

from uvloom_cli import driver, envkey, nixrun
from uvloom_cli.errors import CliError
from uvloom_cli import interpreter
from uvloom_cli.interpreter import interpreter_attr, resolve_interpreter


def test_minor_request_maps_to_attr(capsys):
    assert interpreter_attr("3.12") == "python312"
    assert interpreter_attr("3.11") == "python311"
    assert capsys.readouterr().err == ""  # no warning for minor requests


def test_exact_patch_degrades_with_warning(capsys):
    assert interpreter_attr("3.12.4") == "python312"
    err = capsys.readouterr().err
    assert "3.12.4" in err
    assert "python312" in err
    assert err.startswith("uvloom: warning:")


def test_none_maps_to_none():
    assert interpreter_attr(None) is None


def test_whitespace_tolerated():
    assert interpreter_attr(" 3.12 ") == "python312"


@pytest.mark.parametrize("bad", ["pypy3", "3", "3.x", "python3.12", ""])
def test_invalid_request_raises(bad):
    with pytest.raises(CliError, match="cannot map python request"):
        interpreter_attr(bad)


def test_absolute_path_request_is_not_a_version():
    with pytest.raises(CliError, match="cannot map python request"):
        interpreter_attr("/nix/store/xyz/bin/python3.12")


def test_resolve_rejects_public_absolute_path_request(project, tmp_path, monkeypatch):
    exe = tmp_path / "python3.12"
    exe.write_text("#!/bin/sh\n")
    exe.chmod(0o755)
    monkeypatch.setenv("UV_PYTHON", str(exe))
    with pytest.raises(CliError, match=r"UV_PYTHON must be a MAJOR\.MINOR"):
        resolve_interpreter(project)


def test_resolve_accepts_matching_private_nested_marker(project, tmp_path, monkeypatch):
    exe = _fake_exe(tmp_path, "python3.12")
    (project.root / ".python-version").write_text("3.12\n")
    monkeypatch.setenv("UV_PYTHON", exe)
    monkeypatch.setenv("UVLOOM_RESOLVED_PYTHON", exe)
    driver_path = driver.render_driver(project)
    envkey.write_marker(
        project,
        {
            "interpreter": exe,
            "interpreter_request": "3.12",
            "interpreter_requires_python": ">=3.11",
            "interpreter_fingerprint": interpreter._cache_fingerprint(driver_path),
        },
    )
    monkeypatch.setattr(
        nixrun, "nix_build", lambda *a, **k: pytest.fail("cache hit must not build")
    )
    assert resolve_interpreter(project) == exe


# --- resolve_interpreter: interpreter cache invalidation ----------------------


def _fake_exe(tmp_path, name: str) -> str:
    exe = tmp_path / name
    exe.write_text("#!/bin/sh\n")
    exe.chmod(0o755)
    return str(exe)


def test_resolve_hits_cache_when_request_unchanged(project, tmp_path, monkeypatch):
    exe = _fake_exe(tmp_path, "py")
    (project.root / ".python-version").write_text("3.12\n")
    driver_path = driver.render_driver(project)
    envkey.write_marker(
        project,
        {
            "interpreter": exe,
            "interpreter_request": "3.12",
            "interpreter_requires_python": ">=3.11",
            "interpreter_fingerprint": interpreter._cache_fingerprint(driver_path),
        },
    )
    monkeypatch.setattr(
        nixrun, "nix_build", lambda *a, **k: pytest.fail("cache hit must not build")
    )
    assert resolve_interpreter(project) == exe


def test_interpreter_fingerprint_covers_driver_pins_and_recursive_mutable_lib(
    project, fake_lib, tmp_path, monkeypatch
):
    driver_path = driver.render_driver(project)
    pins = tmp_path / "pins"
    pins.mkdir()
    (pins / "pins.json").write_text('{"rev": 1}\n')
    (pins / "pins.nix").write_text("{ }\n")
    monkeypatch.setattr(nixrun, "data_path", lambda name: pins / name)
    first = interpreter._cache_fingerprint(driver_path)
    driver_path.write_text(driver_path.read_text() + "# changed\n")
    assert interpreter._cache_fingerprint(driver_path) != first

    (pins / "pins.json").write_text('{"rev": 2}\n')
    after_pin = interpreter._cache_fingerprint(driver_path)
    assert after_pin != first

    nested = fake_lib / "nested"
    nested.mkdir()
    input_ = nested / "input.nix"
    input_.write_text("1\n")
    second = interpreter._cache_fingerprint(driver_path)
    input_.write_text("2\n")
    assert interpreter._cache_fingerprint(driver_path) != second


def test_interpreter_fingerprint_turns_mutable_lib_race_into_cli_error(
    project, fake_lib, monkeypatch
):
    driver_path = driver.render_driver(project)
    original = interpreter._hash_file

    def vanished(h, label, path):
        if label.startswith("uvloom-lib:"):
            raise FileNotFoundError("changed during scan")
        return original(h, label, path)

    monkeypatch.setattr(interpreter, "_hash_file", vanished)
    with pytest.raises(CliError, match="cannot fingerprint mutable UVLOOM_LIB"):
        interpreter._cache_fingerprint(driver_path)


def test_resolve_reresolves_when_request_changed(project, fake_lib, tmp_path, monkeypatch):
    # Cached path still exists, but was resolved before .python-version appeared.
    stale = _fake_exe(tmp_path, "stale-py")
    fresh = _fake_exe(tmp_path, "fresh-py")
    envkey.write_marker(
        project,
        {
            "interpreter": stale,
            "interpreter_request": None,
            "interpreter_requires_python": ">=3.11",
        },
    )
    (project.root / ".python-version").write_text("3.12\n")

    out = tmp_path / "out"
    out.write_text(fresh + "\n")
    built = []

    def fake_nix_build(args, *, out_link=None, verbose=False, cwd=None):
        built.append(args)
        return str(out)

    monkeypatch.setattr(nixrun, "nix_build", fake_nix_build)
    assert resolve_interpreter(project) == fresh
    assert built  # existing stale path did NOT count as a hit
    marker = envkey.read_marker(project)
    assert marker["interpreter"] == fresh
    assert marker["interpreter_request"] == "3.12"
    assert marker["interpreter_requires_python"] == ">=3.11"


def test_resolve_reresolves_when_requires_python_changed(
    project, fake_lib, tmp_path, monkeypatch
):
    # With no .python-version, the driver infers from requires-python.
    stale = _fake_exe(tmp_path, "stale-py")
    fresh = _fake_exe(tmp_path, "fresh-py")
    envkey.write_marker(
        project,
        {
            "interpreter": stale,
            "interpreter_request": None,
            "interpreter_requires_python": ">=3.11",
        },
    )
    pyproject = project.pyproject_path.read_text()
    project.pyproject_path.write_text(
        pyproject.replace('requires-python = ">=3.11"', 'requires-python = ">=3.12"')
    )

    out = tmp_path / "out"
    out.write_text(fresh + "\n")
    built = []

    def fake_nix_build(args, *, out_link=None, verbose=False, cwd=None):
        built.append(args)
        return str(out)

    monkeypatch.setattr(nixrun, "nix_build", fake_nix_build)
    assert resolve_interpreter(project) == fresh
    assert built
    marker = envkey.read_marker(project)
    assert marker["interpreter"] == fresh
    assert marker["interpreter_request"] is None
    assert marker["interpreter_requires_python"] == ">=3.12"


def test_resolve_reresolves_old_format_interpreter_cache(
    project, fake_lib, tmp_path, monkeypatch
):
    stale = _fake_exe(tmp_path, "stale-py")
    fresh = _fake_exe(tmp_path, "fresh-py")
    envkey.write_marker(project, {"interpreter": stale, "interpreter_request": None})

    out = tmp_path / "out"
    out.write_text(fresh + "\n")
    built = []

    def fake_nix_build(args, *, out_link=None, verbose=False, cwd=None):
        built.append(args)
        return str(out)

    monkeypatch.setattr(nixrun, "nix_build", fake_nix_build)
    assert resolve_interpreter(project) == fresh
    assert built
    marker = envkey.read_marker(project)
    assert marker["interpreter"] == fresh
    assert marker["interpreter_request"] is None
    assert marker["interpreter_requires_python"] == ">=3.11"


@pytest.mark.parametrize("kind", ["missing", "directory", "non-executable"])
def test_resolve_omits_invalid_cached_interpreter(
    project, fake_lib, tmp_path, monkeypatch, kind
):
    cached = tmp_path / f"cached-{kind}"
    if kind == "directory":
        cached.mkdir()
    elif kind == "non-executable":
        cached.write_text("#!/bin/sh\n")
    fresh = _fake_exe(tmp_path, f"fresh-{kind}")
    envkey.write_marker(
        project,
        {
            "interpreter": str(cached),
            "interpreter_request": None,
            "interpreter_requires_python": ">=3.11",
        },
    )
    out = tmp_path / f"out-{kind}"
    out.write_text(fresh + "\n")
    built = []

    def fake_nix_build(args, *, out_link=None, verbose=False, cwd=None):
        built.append(args)
        return str(out)

    monkeypatch.setattr(nixrun, "nix_build", fake_nix_build)
    assert resolve_interpreter(project) == fresh
    assert built
    assert envkey.read_marker(project)["interpreter"] == fresh


@pytest.mark.parametrize("kind", ["missing", "directory", "non-executable"])
def test_resolve_rejects_invalid_resolved_interpreter(
    project, fake_lib, tmp_path, monkeypatch, kind
):
    resolved = tmp_path / f"resolved-{kind}"
    if kind == "directory":
        resolved.mkdir()
    elif kind == "non-executable":
        resolved.write_text("#!/bin/sh\n")
    out = tmp_path / f"resolved-out-{kind}"
    out.write_text(f"{resolved}\n")
    monkeypatch.setattr(nixrun, "nix_build", lambda *a, **k: str(out))

    with pytest.raises(CliError, match="not a regular executable file"):
        resolve_interpreter(project)
