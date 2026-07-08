"""driver.py: driver.nix rendering, marker interpreter carry-forward, script lock."""

import fcntl
import json
import os
import re
import subprocess
import tomllib
from pathlib import Path

import pytest

from uvloom_cli import driver, envkey, nixrun
from uvloom_cli.driver import (
    _deps_line,
    _script_key,
    _render,
    build_script_venv,
    build_venv,
    render_driver,
)
from uvloom_cli.errors import CliError
from uvloom_cli.interpreter import resolve_interpreter

from conftest import make_project

PLACEHOLDER_RE = re.compile(r"@[A-Za-z]\w*@")


def rendered(project, **kwargs) -> str:
    path = render_driver(project, **kwargs)
    assert path == project.root / ".uvloom" / "driver.nix"
    return path.read_text()


def test_render_leaves_no_placeholders(project, fake_lib):
    text = rendered(project)
    assert not PLACEHOLDER_RE.search(text), PLACEHOLDER_RE.search(text)
    # .uvloom dir is self-ignoring
    assert (project.root / ".uvloom" / ".gitignore").read_text() == "*\n"


def test_render_does_not_rescan_substitution_values():
    assert _render("x @path@ y @pins@", {"path": "/tmp/@pins@/proj", "pins": "P"}) == (
        "x /tmp/@pins@/proj y P"
    )


def test_render_unknown_placeholder_raises():
    with pytest.raises(RuntimeError, match="@missing@"):
        _render("x @missing@", {})


def test_render_core_wiring(project, fake_lib):
    text = rendered(project)
    assert "filterSource = true;" in text
    assert str(fake_lib) in text  # UVLOOM_LIB honored
    assert str(project.root) in text
    assert 'sourcePreference = "wheel";' in text
    assert '"demo-env"' in text
    assert "interpreter = null;" in text  # no version request


def test_sdist_preference_from_uv_no_binary(tmp_path, fake_lib):
    project = make_project(tmp_path / "p", uv_table="no-binary = true")
    assert 'sourcePreference = "sdist";' in rendered(project)


def _code(text: str) -> str:
    """Rendered driver minus comment lines — assert on code, never on prose."""
    return "\n".join(
        line for line in text.splitlines() if not line.lstrip().startswith("#")
    )


def test_editable_flag_is_rendered_without_cli_editables_workaround(project, fake_lib):
    editable = rendered(project, editable=True)
    non_editable = rendered(project, editable=False)
    assert "editable = true;" in editable
    assert "editable = false;" in non_editable
    # Library owns editable build requirements so every library caller gets
    # correct behavior, including local directory dependencies.
    assert "editables" not in _code(editable)
    assert "editables" not in _code(non_editable)


def test_hammer_flag_toggles_hammer_overlay(project, fake_lib):
    # hammer defaults to on (flag-driven; config no longer consulted); the
    # overlay is sourced from the vendored pins — `pins.hammer` is the
    # minimal distinguishing token.
    assert "pins.hammer" in _code(rendered(project))
    assert "pins.hammer" in _code(rendered(project, hammer=True))
    assert "pins.hammer" not in _code(rendered(project, hammer=False))


def test_user_overlay_present_iff_uv_nix_exists(project, fake_lib):
    assert "uv.nix" not in _code(rendered(project))
    project.overlay_path.write_text("final: prev: { }\n")
    assert "uv.nix" in _code(rendered(project))


def test_interpreter_attr_rendered_from_python_version(project, fake_lib):
    (project.root / ".python-version").write_text("3.12\n")
    assert "interpreter = pkgs.python312;" in rendered(project)


def test_default_render_has_empty_extra_source_paths(project, fake_lib):
    assert "extraSourcePaths = [ ];" in rendered(project)


def test_render_can_disable_filter_source(project, fake_lib):
    text = rendered(project, filter_source=False, extra_source_paths=("assets",))
    assert "filterSource = false;" in text
    assert 'extraSourcePaths = [ "assets" ];' in text


def test_check_driver_filename_and_extra_source_paths(project, fake_lib):
    path = render_driver(
        project, filename="check.driver.nix", extra_source_paths=("tests",)
    )
    assert path == project.root / ".uvloom" / "check.driver.nix"
    text = path.read_text()
    assert 'extraSourcePaths = [ "tests" ];' in text
    assert not PLACEHOLDER_RE.search(text), PLACEHOLDER_RE.search(text)


# --- inline script key -------------------------------------------------------


def test_script_key_sensitive_to_hammer(tmp_path):
    script = tmp_path / "s.py"
    script.write_text("print('hi')\n")
    assert _script_key(script, hammer=True) != _script_key(script, hammer=False)


@pytest.mark.parametrize(
    "source",
    [
        {"path": "/tmp/wheel.whl"},
        {"directory": "/tmp/local", "editable": "relative-editable"},
        {"path": "relative.whl", "directory": "/tmp/local", "editable": "/tmp/editable"},
    ],
)
def test_script_lock_projection_rewrites_only_absolute_local_sources(tmp_path, source):
    script_dir = tmp_path / "project" / "scripts"
    script_dir.mkdir(parents=True)
    script = script_dir / "s.py"
    script.write_text("print('hi')\n")
    lock = script.with_name("s.py.lock")
    source_toml = ", ".join(f'{key} = {json.dumps(value)}' for key, value in source.items())
    original = f'''version = 1

[[package]]
name = "demo"
version = "0"
source = {{ {source_toml} }}
'''
    lock.write_text(original)

    private = driver._project_script_lock(script)

    assert lock.read_text() == original, "must never mutate uv-owned script lock"
    assert private == script_dir / ".uvloom" / f"{driver._script_stem(script)}.uv2nix.lock"
    expected = {
        key: os.path.relpath(value, script_dir) if os.path.isabs(value) else value
        for key, value in source.items()
    }
    assert tomllib.loads(private.read_text())["package"][0]["source"] == expected


def test_inline_driver_uses_private_projected_lock(tmp_path, fake_lib):
    script = _make_script(tmp_path)
    private = driver._project_script_lock(script)
    rendered = driver.render_inline_driver(script, lock_path=private).read_text()
    assert str(private) in rendered
    assert str(script.with_name("s.py.lock")) not in rendered


# --- deps_spec ---------------------------------------------------------------


def _write_root_dev_lock(project):
    project.lock_path.write_text(
        """version = 1

[[package]]
name = "demo"
source = { editable = "." }

[package.dev-dependencies]
dev = []
"""
    )


def test_deps_spec_workspace_default_selects_dev_for_cli(project, fake_lib):
    _write_root_dev_lock(project)
    text = rendered(project, deps_spec="workspace-default")
    assert (
        'dependencies = project.workspace.deps.default // { "demo" = '
        'lib.unique ((project.workspace.deps.default."demo" or [ ]) ++ [ "dev" ]); };'
    ) in text


def test_deps_spec_workspace_default_selects_dev_when_noneditable(project, fake_lib):
    _write_root_dev_lock(project)
    text = rendered(project, deps_spec="workspace-default", editable=False)
    assert 'project.workspace.deps.default."demo" or [ ]) ++ [ "dev" ]' in text
    assert "editable = false;" in text


def test_deps_spec_workspace_default_without_configured_dev_uses_workspace_default(project, fake_lib):
    assert "dependencies =" not in rendered(project, deps_spec="workspace-default")


def test_deps_spec_all_groups(project, fake_lib):
    text = rendered(project, deps_spec="all-groups")
    assert "project.workspace.deps.default project.workspace.deps.groups" in text
    assert "workspace.deps.all" not in text


def test_deps_spec_default_empty_uses_workspace_default(project, fake_lib):
    text = rendered(project, deps_spec="default=;groups=;extras=")
    assert "dependencies = project.workspace.deps.default;" in text


def test_deps_spec_default_groups_and_extras(project, fake_lib):
    text = rendered(project, deps_spec="default=docs;groups=lint;extras=cli")
    assert '++ [ "docs" "lint" "cli" ]' in text
    assert '"dev"' not in text


def test_deps_spec_default_all_groups_with_extra(project, fake_lib):
    text = rendered(project, deps_spec="default=all;groups=;extras=cli")
    assert "project.workspace.deps.default project.workspace.deps.groups" in text
    assert '++ [ "cli" ]' in text


def test_deps_spec_all_groups_with_extra(project, fake_lib):
    text = rendered(project, deps_spec="all-groups;extras=cli")
    assert "project.workspace.deps.default project.workspace.deps.groups" in text
    assert '++ [ "cli" ]' in text


def test_deps_spec_groups_and_extras(project, fake_lib):
    _write_root_dev_lock(project)
    text = rendered(project, deps_spec="groups=docs,test;extras=fast")
    assert 'dependencies = project.workspace.deps.default // { "demo" = lib.unique ((project.workspace.deps.default."demo" or [ ]) ++ [ "dev" "docs" "test" "fast" ]); };' in text


def test_deps_spec_groups_without_root_dev_does_not_add_dev(project, fake_lib):
    text = rendered(project, deps_spec="groups=docs;extras=")
    assert '++ [ "docs" ]' in text
    assert '"dev"' not in text


def test_deps_spec_groups_with_root_dev_adds_dev(project, fake_lib):
    _write_root_dev_lock(project)
    text = rendered(project, deps_spec="groups=docs;extras=")
    assert '++ [ "dev" "docs" ]' in text


def test_deps_line_dedupes_and_keeps_dev_first(project):
    _write_root_dev_lock(project)
    line = _deps_line(project, "groups=dev,docs;extras=")
    assert '"demo" = lib.unique ((project.workspace.deps.default."demo" or [ ]) ++ [ "dev" "docs" ])' in line


def test_deps_line_uses_normalized_root_lock_name(project):
    project.lock_path.write_text(
        """version = 1\n\n[[package]]\nname = "demo-normalized"\nsource = { editable = "." }\n"""
    )
    assert '"demo-normalized"' in _deps_line(project, "groups=docs;extras=")


def test_deps_line_rejects_same_selector_as_group_and_extra(project):
    with pytest.raises(CliError, match="both --group and --extra"):
        _deps_line(project, "groups=docs;extras=docs")


def test_deps_line_rejects_declared_group_extra_name_collision(project):
    project.lock_path.write_text(
        """version = 1\n\n[[package]]\nname = "demo"\nsource = { editable = "." }\n[package.dev-dependencies]\ndocs = []\n[package.optional-dependencies]\ndocs = []\n"""
    )
    with pytest.raises(CliError, match="defines it as both"):
        _deps_line(project, "groups=docs;extras=")


def test_deps_spec_malformed_raises(project):
    with pytest.raises(CliError, match="malformed deps_spec"):
        _deps_line(project, "groups-only=docs")


# --- build_venv: interpreter carry-forward ------------------------------------


def _run_build(project, monkeypatch, store_path="/nix/store/abc-venv", force=False, editable=False):
    monkeypatch.setattr(nixrun, "nix_build", lambda *a, **k: store_path)
    return build_venv(
        project,
        editable=editable,
        deps_spec="workspace-default",
        hammer=True,
        source_preference="wheel",
        force=force,
    )


def test_build_venv_keeps_interpreter_when_inputs_unchanged(
    project, fake_lib, monkeypatch, tmp_path
):
    monkeypatch.delenv("UV_PYTHON", raising=False)
    (project.root / ".python-version").write_text("3.12\n")
    exe = tmp_path / "py"
    exe.write_text("#!/bin/sh\n")
    exe.chmod(0o755)
    envkey.write_marker(
        project,
        {
            "interpreter": str(exe),
            "interpreter_request": "3.12",
            "interpreter_requires_python": ">=3.11",
        },
    )
    _run_build(project, monkeypatch)
    marker = envkey.read_marker(project)
    assert marker["interpreter"] == str(exe)
    assert marker["interpreter_request"] == "3.12"
    assert marker["interpreter_requires_python"] == ">=3.11"
    assert marker["store_path"] == "/nix/store/abc-venv"


def test_build_venv_drops_stale_interpreter_when_request_changed(project, fake_lib, monkeypatch):
    monkeypatch.delenv("UV_PYTHON", raising=False)
    envkey.write_marker(
        project,
        {
            "interpreter": "/nix/store/py",
            "interpreter_request": "3.11",
            "interpreter_requires_python": ">=3.11",
        },
    )
    (project.root / ".python-version").write_text("3.12\n")
    _run_build(project, monkeypatch)
    marker = envkey.read_marker(project)
    assert marker["interpreter"] is None
    assert marker["interpreter_request"] is None
    assert marker["interpreter_requires_python"] is None


def test_build_venv_drops_interpreter_when_requires_python_changed(
    project, fake_lib, monkeypatch
):
    # THE stale-interpreter bug: no .python-version, so the effective request
    # is None before AND after — only [project].requires-python changed. The
    # cached interpreter was inferred from the old constraint; carrying it
    # forward would run the wrong python forever.
    monkeypatch.delenv("UV_PYTHON", raising=False)
    envkey.write_marker(
        project,
        {
            "interpreter": "/nix/store/py",
            "interpreter_request": None,
            "interpreter_requires_python": ">=3.11",
        },
    )
    project.pyproject_path.write_text(
        project.pyproject_path.read_text().replace(
            'requires-python = ">=3.11"', 'requires-python = ">=3.12"'
        )
    )
    _run_build(project, monkeypatch)
    marker = envkey.read_marker(project)
    assert marker["interpreter"] is None
    assert marker["interpreter_request"] is None
    assert marker["interpreter_requires_python"] is None


def test_resolve_interpreter_hits_cache_after_sync(project, fake_lib, monkeypatch, tmp_path):
    # Regression: build_venv used to omit interpreter_requires_python from
    # the rewritten marker, so resolve_interpreter's hit-condition
    # (`"interpreter_requires_python" in marker`) could never succeed after
    # a sync — every subsequent run re-resolved the interpreter.
    monkeypatch.delenv("UV_PYTHON", raising=False)
    exe = tmp_path / "py"
    exe.write_text("")
    exe.chmod(0o755)
    envkey.write_marker(
        project,
        {
            "interpreter": str(exe),
            "interpreter_request": None,
            "interpreter_requires_python": ">=3.11",
        },
    )
    _run_build(project, monkeypatch, editable=True)  # sync with unchanged interpreter inputs
    monkeypatch.setattr(
        nixrun, "nix_build", lambda *a, **k: pytest.fail("cache hit must not build")
    )
    assert resolve_interpreter(project) == str(exe)


def test_build_venv_marker_caches_hot_path_config_only(project, fake_lib, monkeypatch):
    # The cached config carries exactly the fields the hot-path key needs;
    # the interpreter request is keyed separately (interpreter_request), so
    # a stray copy under config would go stale silently.
    _run_build(project, monkeypatch)
    marker = envkey.read_marker(project)
    assert marker["config"] == {
        "editable": False,
        "hammer": True,
        "source_preference": "wheel",
        "deps_spec": "workspace-default",
        "sources": [],
        "declared_meta": {"paths": [], "globs": []},
        "filter_source": True,
        "extra_source_paths": [],
    }


def test_build_venv_force_rebuilds_even_when_marker_current(
    project, fake_lib, monkeypatch, tmp_path
):
    monkeypatch.delenv("UV_PYTHON", raising=False)
    monkeypatch.setattr(envkey, "_valid_store_venv", lambda path: True)
    store = tmp_path / "store-env"
    store.mkdir()
    # First build establishes a current marker + .venv link.
    _run_build(project, monkeypatch, store_path=str(store))
    (project.root / ".venv").symlink_to(store)

    builds = []

    def counting_build(*a, **k):
        builds.append(a)
        return str(store)

    monkeypatch.setattr(nixrun, "nix_build", counting_build)
    # Control: current marker short-circuits under the lock.
    assert build_venv(
        project,
        editable=False,
        deps_spec="workspace-default",
        hammer=True,
        source_preference="wheel",
    ) == str(store)
    assert builds == []

    # --force must genuinely rebuild despite the current marker.
    assert build_venv(
        project,
        editable=False,
        deps_spec="workspace-default",
        hammer=True,
        source_preference="wheel",
        force=True,
    ) == str(store)
    assert len(builds) == 1


# --- ensure_not_foreign --------------------------------------------------------


def test_ensure_not_foreign_force_removes_regular_file_venv(project):
    # A regular FILE at .venv is foreign; --force must unlink it (rmtree on
    # a file raises NotADirectoryError) instead of crashing.
    venv = project.root / ".venv"
    venv.write_text("not a venv\n")
    with pytest.raises(CliError, match="not managed by uvloom"):
        driver.ensure_not_foreign(project)
    driver.ensure_not_foreign(project, force=True)
    assert not venv.exists()


# --- inline script build: lock + marker re-check ------------------------------


def _make_script(tmp_path):
    script = tmp_path / "s.py"
    script.write_text("print('hi')\n")
    script.with_name("s.py.lock").write_text("version = 1\n")
    return script


def test_script_key_hashes_declared_local_path_sources(tmp_path):
    script = _make_script(tmp_path)
    local = tmp_path / "localpkg"
    local.mkdir()
    (local / "pyproject.toml").write_text("[project]\nname = 'localpkg'\nversion = '0'\n")
    script.with_name("s.py.lock").write_text(
        """
version = 1

[[package]]
name = "localpkg"
version = "0"
source = { directory = "localpkg" }
""".lstrip()
    )

    first = _script_key(script, hammer=True)
    assert _script_key(script, hammer=True) == first

    (local / "module.py").write_text("VALUE = 1\n")
    assert _script_key(script, hammer=True) != first


def test_script_key_ignores_missing_or_malformed_local_sources(tmp_path):
    script = _make_script(tmp_path)
    script.with_name("s.py.lock").write_text(
        """
version = 1

[[package]]
name = "missing"
source = { editable = "missing" }

[[package]]
name = "malformed"
source = "not a table"
""".lstrip()
    )

    assert _script_key(script, hammer=True) == _script_key(script, hammer=True)


def test_script_key_distinguishes_absent_and_empty_lock(tmp_path):
    # _hash_file frames absent files distinctly from empty ones: truncating
    # script.lock to zero bytes must not hit the old (lock-less) cache.
    script = tmp_path / "s.py"
    script.write_text("print('hi')\n")
    absent = _script_key(script, hammer=True)
    script.with_name("s.py.lock").write_text("")
    assert _script_key(script, hammer=True) != absent


def test_script_key_hashes_vendored_path_archive_bytes(tmp_path):
    # Script locks record no content hash for `source = { path = ... }`
    # archives: swapping the vendored wheel with the lock unchanged must
    # change the key.
    script = _make_script(tmp_path)
    wheel = tmp_path / "localwheel-0.1.0-py3-none-any.whl"
    wheel.write_bytes(b"wheel-bytes-v1")
    script.with_name("s.py.lock").write_text(
        """
version = 1

[[package]]
name = "localwheel"
version = "0.1.0"
source = { path = "localwheel-0.1.0-py3-none-any.whl" }
""".lstrip()
    )
    first = _script_key(script, hammer=True)
    assert _script_key(script, hammer=True) == first

    wheel.write_bytes(b"wheel-bytes-v2")  # lock untouched
    assert _script_key(script, hammer=True) != first


def test_script_key_tracks_checkout_uvloom_lib_edits(tmp_path, fake_lib):
    # UVLOOM_LIB / a repo checkout lives outside /nix/store, so its contents
    # are mutable: editing any lib/*.nix must change the script key — a
    # stale script venv would otherwise survive library changes (same rule
    # as the project env key).
    script = _make_script(tmp_path)
    first = _script_key(script, hammer=True)
    assert _script_key(script, hammer=True) == first  # stable while untouched

    (fake_lib / "default.nix").write_text(
        "{ lib, uv2nix, pyproject-nix, pyproject-build-systems }: { edited = true; }\n"
    )
    edited = _script_key(script, hammer=True)
    assert edited != first

    # A new *.nix file directly under the lib (e.g. inline.nix) counts too.
    (fake_lib / "inline.nix").write_text("{ }: { }\n")
    assert _script_key(script, hammer=True) != edited


def test_script_key_incorporates_inline_template(tmp_path, monkeypatch):
    # The script driver is rendered from _INLINE_TEMPLATE, which lives in
    # code, not in any hashed data file: a template change (new CLI build)
    # must invalidate cached script venvs.
    script = _make_script(tmp_path)
    first = _script_key(script, hammer=True)
    monkeypatch.setattr(
        driver, "_INLINE_TEMPLATE", driver._INLINE_TEMPLATE + "\n# changed\n"
    )
    assert _script_key(script, hammer=True) != first


def test_script_build_holds_lock_during_build(tmp_path, fake_lib, monkeypatch):
    script = _make_script(tmp_path)
    lock_path = tmp_path / ".uvloom" / f"{driver._script_stem(script)}.lock"

    def fake_nix_build(args, *, out_link=None, verbose=False, cwd=None):
        # The advisory lock must be held while nix runs: a second flock on an
        # independent fd conflicts even within one process.
        assert lock_path.exists()
        fd = os.open(lock_path, os.O_RDWR)
        try:
            with pytest.raises(BlockingIOError):
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        finally:
            os.close(fd)
        return "/nix/store/abc-script-venv"

    monkeypatch.setattr(nixrun, "nix_build", fake_nix_build)
    assert build_script_venv(script) == "/nix/store/abc-script-venv"
    marker = json.loads((tmp_path / "s.py.uvloom.json").read_text())
    assert marker["store_path"] == "/nix/store/abc-script-venv"


def test_script_lock_creation_and_key_check_are_inside_script_lock(tmp_path, fake_lib, monkeypatch):
    script = _make_script(tmp_path)
    script.with_name(script.name + ".lock").unlink()
    lock_path = tmp_path / ".uvloom" / f"{driver._script_stem(script)}.lock"
    seen = []

    def assert_locked():
        fd = os.open(lock_path, os.O_RDWR)
        try:
            with pytest.raises(BlockingIOError):
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        finally:
            os.close(fd)

    def fake_run(argv, *, cwd, env):
        assert_locked()
        seen.append("lock")
        script.with_name(script.name + ".lock").write_text("version = 1\n")
        return subprocess.CompletedProcess(argv, 0)

    def fake_key(_script, *, hammer):
        assert_locked()
        seen.append("key")
        return "locked-key"

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(driver, "_script_key_from_snapshot", lambda script, script_bytes, lock_bytes, *, hammer, local_sources=(): fake_key(script, hammer=hammer))
    monkeypatch.setattr(nixrun, "nix_build", lambda *a, **k: "/nix/store/locked-script")
    assert build_script_venv(script) == "/nix/store/locked-script"
    assert seen == ["lock", "key"]


def test_script_build_rechecks_marker_under_lock(tmp_path, monkeypatch):
    import contextlib

    script = _make_script(tmp_path)
    racer_store = tmp_path / "racer-venv"
    racer_store.mkdir()
    key = _script_key(script, hammer=True)

    @contextlib.contextmanager
    def racing_lock(s):
        # Simulate a concurrent build completing while we waited for the
        # lock: it wrote the marker AND rooted the store path via the
        # out-link (a hit requires both — see _script_marker_hit).
        driver.script_marker_path(script).write_text(
            json.dumps({"key": key, "store_path": str(racer_store), "cli_version": "x"})
        )
        driver._script_out_link(script).symlink_to(racer_store)
        yield

    monkeypatch.setattr(driver, "_script_build_lock", racing_lock)
    monkeypatch.setattr(
        nixrun,
        "nix_build",
        lambda *a, **k: pytest.fail("marker re-check must short-circuit the build"),
    )
    assert build_script_venv(script) == str(racer_store)


def _seed_script_hit(tmp_path, *, out_link="current"):
    """Script + marker + store dir; out_link: current | missing | stale | file."""
    script = _make_script(tmp_path)
    store = tmp_path / "script-venv"
    store.mkdir()
    key = _script_key(script, hammer=True)
    driver.script_marker_path(script).write_text(
        json.dumps({"key": key, "store_path": str(store), "cli_version": "x"})
    )
    link = driver._script_out_link(script)
    if out_link == "current":
        link.symlink_to(store)
    elif out_link == "stale":
        other = tmp_path / "other-venv"
        other.mkdir()
        link.symlink_to(other)
    elif out_link == "file":
        link.write_text("not a symlink\n")
    return script, str(store), key


def test_script_marker_hit_requires_current_out_link(tmp_path):
    # A key-matching marker whose store path exists is only trustworthy
    # while the GC root still points at it: an unrooted store path can be
    # collected mid-run (same discipline as envkey.venv_is_current).
    script, store, key = _seed_script_hit(tmp_path, out_link="current")
    assert driver._script_marker_hit(script, driver.script_marker_path(script), key) == store


@pytest.mark.parametrize("out_link", ["missing", "stale", "file"])
def test_script_marker_miss_when_out_link_gone_or_wrong(tmp_path, out_link):
    script, _, key = _seed_script_hit(tmp_path, out_link=out_link)
    assert driver._script_marker_hit(script, driver.script_marker_path(script), key) is None


def test_script_build_rebuilds_when_out_link_missing(tmp_path, fake_lib, monkeypatch):
    # End to end through build_script_venv: valid marker + live store path
    # but no GC root -> the rebuild path (nix_build) must be taken.
    script, _, _ = _seed_script_hit(tmp_path, out_link="missing")
    builds = []

    def fake_nix_build(args, *, out_link=None, verbose=False, cwd=None):
        builds.append(out_link)
        return "/nix/store/rebuilt-script-venv"

    monkeypatch.setattr(nixrun, "nix_build", fake_nix_build)
    assert build_script_venv(script) == "/nix/store/rebuilt-script-venv"
    assert builds == [str(driver._script_out_link(script))]


def test_script_build_retries_if_script_changes_during_build(tmp_path, fake_lib, monkeypatch):
    script = _make_script(tmp_path)
    calls = []

    def fake_nix_build(args, *, out_link=None, verbose=False, cwd=None):
        calls.append(args)
        if len(calls) == 1:
            script.write_text("print('changed')\n")
            return "/nix/store/old-script-venv"
        return "/nix/store/new-script-venv"

    monkeypatch.setattr(nixrun, "nix_build", fake_nix_build)
    assert build_script_venv(script) == "/nix/store/new-script-venv"
    marker = json.loads(driver.script_marker_path(script).read_text())
    lock_bytes = script.with_name(script.name + ".lock").read_bytes()
    assert marker["key"] == driver._script_key_from_snapshot(
        script, script.read_bytes(), lock_bytes, hammer=True
    )
    assert marker["store_path"] == "/nix/store/new-script-venv"
    assert len(calls) == 2


def test_script_build_uses_snapshot_driver_and_retries(tmp_path, fake_lib, monkeypatch):
    script = _make_script(tmp_path)
    rendered = []

    def fake_nix_build(args, *, out_link=None, verbose=False, cwd=None):
        text = Path(args[0]).read_text()
        rendered.append(text)
        assert str(script) not in text
        assert ".attempt-" in text
        if len(rendered) == 1:
            script.write_text("print('changed')\n")
            return "/nix/store/old-script-venv"
        return "/nix/store/new-script-venv"

    monkeypatch.setattr(nixrun, "nix_build", fake_nix_build)
    assert build_script_venv(script) == "/nix/store/new-script-venv"
    assert len(rendered) == 2


def test_script_projection_reanchors_relative_sources_for_snapshot(tmp_path, fake_lib, monkeypatch):
    script = _make_script(tmp_path)
    local = tmp_path / "localpkg"
    local.mkdir()
    script.with_name(script.name + ".lock").write_text(
        'version = 1\n[[package]]\nname = "localpkg"\nsource = { directory = "localpkg" }\n'
    )
    projected = []

    def fake_nix_build(args, *, out_link=None, verbose=False, cwd=None):
        text = Path(args[0]).read_text()
        match = re.search(r'lockPath = \(/\. \+ "([^"]+)"\);', text)
        assert match is not None
        lock_path = Path(match.group(1))
        projected.append(tomllib.loads(lock_path.read_text()))
        projected_source = projected[-1]["package"][0]["source"]["directory"]
        expected_prefix = os.path.join("local-sources", "0-directory-localpkg")
        assert projected_source == expected_prefix
        return "/nix/store/script-venv"

    monkeypatch.setattr(nixrun, "nix_build", fake_nix_build)
    assert build_script_venv(script) == "/nix/store/script-venv"
    assert script.with_name(script.name + ".lock").read_text().endswith('"localpkg" }\n')


def test_script_build_snapshots_local_source_and_retries_on_edit(tmp_path, fake_lib, monkeypatch):
    script = _make_script(tmp_path)
    local = tmp_path / "localpkg"
    local.mkdir()
    (local / "pyproject.toml").write_text("[project]\nname = 'localpkg'\nversion = '0'\n")
    (local / ".hidden-package-file").write_text("keep\n")
    (local / "mod.py").write_text("VALUE = 1\n")
    script.with_name(script.name + ".lock").write_text(
        'version = 1\n[[package]]\nname = "localpkg"\nsource = { directory = "localpkg" }\n'
    )
    calls = []

    def fake_nix_build(args, *, out_link=None, verbose=False, cwd=None):
        lock_path = Path(re.search(r'lockPath = \(/\. \+ "([^"]+)"\);', Path(args[0]).read_text()).group(1))
        source = lock_path.parent / tomllib.loads(lock_path.read_text())["package"][0]["source"]["directory"]
        assert source.is_relative_to(lock_path.parent / "local-sources")
        assert (source / ".hidden-package-file").read_text() == "keep\n"
        calls.append(source)
        if len(calls) == 1:
            (local / "mod.py").write_text("VALUE = 2\n")
            return "/nix/store/old-local-source"
        return "/nix/store/new-local-source"

    monkeypatch.setattr(nixrun, "nix_build", fake_nix_build)
    assert build_script_venv(script) == "/nix/store/new-local-source"
    assert len(calls) == 2
    marker = json.loads(driver.script_marker_path(script).read_text())
    assert marker["key"] == _script_key(script, hammer=True)


def test_script_path_file_source_snapshotted_and_retried(tmp_path, fake_lib, monkeypatch):
    script = _make_script(tmp_path)
    wheel = tmp_path / "local.whl"
    wheel.write_bytes(b"v1")
    script.with_name(script.name + ".lock").write_text(
        'version = 1\n[[package]]\nname = "local"\nsource = { path = "local.whl" }\n'
    )
    calls = 0

    def fake_nix_build(args, *, out_link=None, verbose=False, cwd=None):
        nonlocal calls
        calls += 1
        lock_path = Path(re.search(r'lockPath = \(/\. \+ "([^"]+)"\);', Path(args[0]).read_text()).group(1))
        source = lock_path.parent / tomllib.loads(lock_path.read_text())["package"][0]["source"]["path"]
        assert source.read_bytes() == (b"v1" if calls == 1 else b"v2")
        if calls == 1:
            wheel.write_bytes(b"v2")
            return "/nix/store/old-wheel"
        return "/nix/store/new-wheel"

    monkeypatch.setattr(nixrun, "nix_build", fake_nix_build)
    assert build_script_venv(script) == "/nix/store/new-wheel"
    assert calls == 2


def test_script_local_source_symlink_rejected(tmp_path, fake_lib, monkeypatch):
    script = _make_script(tmp_path)
    local = tmp_path / "localpkg"
    local.mkdir()
    (local / "target.py").write_text("x = 1\n")
    (local / "link.py").symlink_to(local / "target.py")
    script.with_name(script.name + ".lock").write_text(
        'version = 1\n[[package]]\nname = "localpkg"\nsource = { directory = "localpkg" }\n'
    )
    monkeypatch.setattr(nixrun, "nix_build", lambda *a, **k: pytest.fail("must not build"))
    with pytest.raises(CliError, match="contains symlink"):
        build_script_venv(script)


def test_script_build_repeated_churn_errors_without_marker(tmp_path, fake_lib, monkeypatch):
    script = _make_script(tmp_path)
    count = 0

    def fake_nix_build(args, *, out_link=None, verbose=False, cwd=None):
        nonlocal count
        count += 1
        script.with_name(script.name + ".lock").write_text(f"version = {count + 1}\n")
        return f"/nix/store/churn-{count}"

    monkeypatch.setattr(driver, "_SCRIPT_BUILD_MAX_ATTEMPTS", 3)
    monkeypatch.setattr(nixrun, "nix_build", fake_nix_build)
    with pytest.raises(CliError, match="changed repeatedly"):
        build_script_venv(script)
    assert count == 3
    assert not driver.script_marker_path(script).exists()
