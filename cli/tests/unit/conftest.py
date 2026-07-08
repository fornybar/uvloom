"""Shared fixtures: real Project objects over tmp_path, no mocks of our code."""

import stat
import textwrap
from pathlib import Path

import pytest

from uvloom_cli.config import load_project


def write_pyproject(
    root: Path, *, name: str = "demo", uv_table: str = ""
) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    body = textwrap.dedent(
        f"""\
        [project]
        name = "{name}"
        version = "0.1.0"
        requires-python = ">=3.11"
        dependencies = []
        """
    )
    if uv_table:
        body += "\n[tool.uv]\n" + textwrap.dedent(uv_table) + "\n"
    path = root / "pyproject.toml"
    path.write_text(body)
    return path


def make_project(root: Path, *, name: str = "demo", uv_table: str = ""):
    write_pyproject(root, name=name, uv_table=uv_table)
    return load_project(root)


def write_stub(path: Path, script: str) -> Path:
    """Executable shell stub (subprocess boundary — allowed to fake)."""
    path.write_text("#!/bin/sh\n" + script)
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


@pytest.fixture(autouse=True)
def _strip_ambient_env(monkeypatch):
    """The developer's shell may export uv/uvloom knobs that the code under
    test reads straight from os.environ (config.source_preference, envkey,
    nixrun) — ambient values silently flip source preferences, env keys, and
    lib discovery. Strip them for every test; tests that need one set it
    explicitly (autouse fixtures run before requested ones, so fake_lib's
    setenv still wins)."""
    for var in (
        "UV_PYTHON",
        "UV_NO_BINARY",
        "UV_NO_BINARY_PACKAGE",
        "UVLOOM_LIB",
        "UVLOOM_UV",
    ):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture
def project(tmp_path):
    return make_project(tmp_path / "proj")


@pytest.fixture
def fake_lib(tmp_path, monkeypatch):
    """A directory that satisfies nixrun.uvloom_lib_path() deterministically."""
    lib = tmp_path / "fakelib"
    lib.mkdir()
    (lib / "default.nix").write_text("{ lib, uv2nix, pyproject-nix, pyproject-build-systems }: { }\n")
    monkeypatch.setenv("UVLOOM_LIB", str(lib))
    return lib


@pytest.fixture
def no_nix(tmp_path, monkeypatch):
    """PATH without any real binaries, so `nix log` attempts fail instantly."""
    empty = tmp_path / "emptybin"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    return empty
