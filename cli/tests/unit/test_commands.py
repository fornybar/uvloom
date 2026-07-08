"""commands.py: argv splitting, env flag parsing, lock bootstrap, hot-path key."""

import os
import subprocess
import types

import pytest

from uvloom_cli import commands, driver, envkey, failures, nixrun
from uvloom_cli.errors import CliError


class _Exec(Exception):
    """Raised by the fake _exec_in_venv — the real one never returns."""

    def __init__(self, root, cmd, interpreter):
        super().__init__("exec")
        self.root = root
        self.cmd = cmd
        self.interpreter = interpreter


def _patch_build_seams(monkeypatch, root):
    """Intercept cmd_run's cold build and its exec; no Nix is ever invoked.

    Returns a dict: calls["build"] = (opts, kwargs) once _load_and_build ran.
    """
    calls = {}

    def fake_build(opts, **kwargs):
        calls["build"] = (opts, kwargs)
        stub = commands._paths_stub(root)
        store = str(root / "fake-store")
        envkey.write_marker(stub, {"store_path": store})
        return stub, store

    def fake_exec(exec_root, cmd, *, interpreter=None, store_path=None):
        raise _Exec(exec_root, cmd, interpreter)

    monkeypatch.setattr(commands, "_load_and_build", fake_build)
    monkeypatch.setattr(commands, "_exec_in_venv", fake_exec)
    return calls


# --- cmd_run: argv splitting ---------------------------------------------------


@pytest.mark.parametrize(
    ("argv", "msg"),
    [
        (["--group", "--", "echo"], "--group requires a value"),
        (["--group"], "--group requires a value"),
        (["--extra", "--", "echo"], "--extra requires a value"),
        (["--extra"], "--extra requires a value"),
    ],
)
def test_run_value_flag_without_value_errors(argv, msg):
    with pytest.raises(CliError, match=msg):
        commands.cmd_run(argv)


def test_environment_command_rejects_malformed_lock_package_array(project, monkeypatch):
    project.lock_path.write_text('version = 1\npackage = ["bad"]\n')
    monkeypatch.chdir(project.root)
    with pytest.raises(CliError, match="package entry 1 is not a table"):
        commands.cmd_venv([])


def test_run_flags_only_argv_requires_a_command():
    with pytest.raises(CliError, match="provide a command to run"):
        commands.cmd_run(["--group", "x"])


def test_run_two_token_group_with_double_dash_splits(project, monkeypatch):
    monkeypatch.chdir(project.root)
    calls = _patch_build_seams(monkeypatch, project.root)
    # Dash tokens after '--' belong to the command, never to uvloom.
    with pytest.raises(_Exec) as exc:
        commands.cmd_run(["--group", "x", "--", "pytest", "--extra", "pg"])
    assert exc.value.cmd == ["pytest", "--extra", "pg"]
    opts, _ = calls["build"]
    assert opts["groups"] == ["x"]
    assert opts["extras"] == []


def test_run_equals_group_then_first_non_dash_token_starts_command(project, monkeypatch):
    monkeypatch.chdir(project.root)
    calls = _patch_build_seams(monkeypatch, project.root)
    # Dash tokens after the first non-dash token are command args, not flags.
    with pytest.raises(_Exec) as exc:
        commands.cmd_run(["--group=x", "cmd", "--flag", "-v"])
    assert exc.value.cmd == ["cmd", "--flag", "-v"]
    assert calls["build"][0]["groups"] == ["x"]


@pytest.mark.parametrize("module_flag", ["-m", "--module"])
def test_run_module_flag_starts_command_after_env_flags(project, monkeypatch, module_flag):
    monkeypatch.chdir(project.root)
    calls = _patch_build_seams(monkeypatch, project.root)

    with pytest.raises(_Exec) as exc:
        commands.cmd_run(["--group", "dev", module_flag, "pytest", "-q"])

    assert exc.value.cmd == [module_flag, "pytest", "-q"]
    assert calls["build"][0]["groups"] == ["dev"]


def test_run_unknown_dash_flag_before_module_still_errors(project, monkeypatch):
    monkeypatch.chdir(project.root)
    _patch_build_seams(monkeypatch, project.root)

    with pytest.raises(CliError, match="unknown flag '--wat' for 'uvloom run'"):
        commands.cmd_run(["--wat", "-m", "pytest"])


def test_deps_spec_includes_config_defaults_and_explicit_selectors():
    opts = commands._parse_env_flags(["--group", "lint", "--extra", "cli"], command="sync")
    assert commands._deps_spec(opts, ("docs",)) == "default=docs;groups=lint;extras=cli"


def test_env_source_flags_parse_and_conflict():
    opts = commands._parse_env_flags(["--include", "assets", "--include=data"], command="sync")
    assert opts["include"] == ["assets", "data"]
    assert opts["filter_source"] is None
    opts = commands._parse_env_flags(["--no-filter-source"], command="venv")
    assert opts["filter_source"] is False
    with pytest.raises(CliError, match="--include cannot be used with --no-filter-source"):
        commands._parse_env_flags(["--no-filter-source", "--include", "assets"], command="run")


def test_deps_spec_empty_and_all_defaults():
    opts = commands._parse_env_flags([], command="sync")
    assert commands._deps_spec(opts, ("dev",), default_groups_explicit=False) == "workspace-default"
    assert commands._deps_spec(opts, ("dev",), default_groups_explicit=True) == "default=dev;groups=;extras="
    assert commands._deps_spec(opts, ()) == "default=;groups=;extras="
    assert commands._deps_spec(opts, "all") == "default=all;groups=;extras="


def test_deps_spec_absent_defaults_with_selectors_uses_legacy_spec():
    opts = commands._parse_env_flags(["--group", "docs"], command="sync")
    assert commands._deps_spec(opts, ("dev",), default_groups_explicit=False) == "groups=docs;extras="

    opts = commands._parse_env_flags(["--extra", "cli"], command="sync")
    assert commands._deps_spec(opts, ("dev",), default_groups_explicit=False) == "groups=;extras=cli"


def test_deps_spec_all_groups_preserves_explicit_extras_only():
    opts = commands._parse_env_flags(["--all-groups", "--extra", "cli"], command="sync")
    assert commands._deps_spec(opts, ("dev",)) == "all-groups;extras=cli"
    assert commands._deps_spec(opts, ("dev",), default_groups_explicit=False) == "all-groups;extras=cli"


# --- cmd_run: hot-path staleness ------------------------------------------------


def _seed_current_marker(
    project, tmp_path, monkeypatch, *, request=None, interpreter=None, interpreter_request=None
):
    """Marker + live .venv symlink that the hot path should hit as-is."""
    # Test cache logic with a temporary fake store path; dedicated envkey
    # tests cover strict /nix/store venv validation.
    monkeypatch.setattr(envkey, "_valid_store_venv", lambda path: True)
    stub = commands._paths_stub(project.root)
    cached_config = {
        "editable": True,
        "deps_spec": "workspace-default",
        "hammer": True,
        "sources": [],
        "source_preference": "wheel",
        "declared_meta": {"paths": [], "globs": []},
    }
    key = envkey.compute_key(
        stub,
        editable=True,
        deps_spec="workspace-default",
        hammer=True,
        source_preference="wheel",
        interpreter_request=request,
        sources=[],
        declared_meta={"paths": [], "globs": []},
    )
    store = tmp_path / "store-env"
    store.mkdir()
    envkey.write_marker(
        stub,
        {
            "key": key,
            "store_path": str(store),
            "interpreter": interpreter,
            "interpreter_request": interpreter_request,
            "config": cached_config,
        },
    )
    (project.root / ".venv").symlink_to(store)


def test_run_hot_path_misses_when_uv_no_binary_beats_cached_preference(
    project, monkeypatch, tmp_path
):
    monkeypatch.chdir(project.root)
    monkeypatch.delenv("UV_PYTHON", raising=False)
    monkeypatch.delenv("UV_NO_BINARY", raising=False)

    _seed_current_marker(project, tmp_path, monkeypatch)
    calls = _patch_build_seams(monkeypatch, project.root)

    # Control: env agrees with the cached preference -> hot hit, no build.
    with pytest.raises(_Exec) as exc:
        commands.cmd_run(["true"])
    assert exc.value.cmd == ["true"]
    assert "build" not in calls

    # UV_NO_BINARY=1 forces sdist; the recomputed key must differ from the
    # marker's wheel-preference key -> cache miss -> cold rebuild.
    monkeypatch.setenv("UV_NO_BINARY", "1")
    with pytest.raises(_Exec):
        commands.cmd_run(["true"])
    assert "build" in calls


def test_run_hot_path_rejects_package_specific_no_binary(project, monkeypatch, tmp_path):
    monkeypatch.chdir(project.root)
    _seed_current_marker(project, tmp_path, monkeypatch)
    monkeypatch.setenv("UV_NO_BINARY_PACKAGE", "requests")
    with pytest.raises(CliError, match="UV_NO_BINARY_PACKAGE is not supported"):
        commands.cmd_run(["true"])


def test_find_root_returns_single_project_root(tmp_path):
    root = tmp_path / "root"
    deep = root / "src" / "pkg"
    deep.mkdir(parents=True)
    (root / "pyproject.toml").write_text("[project]\nname='root'\nversion='0'\n")
    assert commands._find_root(deep) == root


def test_find_root_returns_none_for_nested_pyprojects(tmp_path):
    outer = tmp_path / "outer"
    inner = outer / "inner"
    inner.mkdir(parents=True)
    (outer / "pyproject.toml").write_text("[project]\nname='outer'\nversion='0'\n")
    (inner / "pyproject.toml").write_text("[project]\nname='inner'\nversion='0'\n")
    assert commands._find_root(inner) is None


def test_find_root_returns_none_for_nested_pyproject_with_inner_lock(tmp_path):
    outer = tmp_path / "outer"
    inner = outer / "inner"
    inner.mkdir(parents=True)
    (outer / "pyproject.toml").write_text("[project]\nname='outer'\nversion='0'\n")
    (inner / "pyproject.toml").write_text("[project]\nname='inner'\nversion='0'\n")
    (inner / "uv.lock").write_text("version = 1\n")
    assert commands._find_root(inner) is None


def test_find_root_returns_none_without_pyproject(tmp_path):
    assert commands._find_root(tmp_path) is None


def test_run_workspace_member_uses_workspace_root_for_hot_cache_and_cold_path(
    tmp_path, monkeypatch
):
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "pyproject.toml").write_text(
        "[project]\nname='root'\nversion='0'\nrequires-python='>=3.11'\n"
        "[tool.uv.workspace]\nmembers=['members/*']\n"
    )
    (root / "uv.lock").write_text("version = 1\n")
    member = root / "members" / "one"
    member.mkdir(parents=True)
    (member / "pyproject.toml").write_text(
        "[project]\nname='one'\nversion='0'\nrequires-python='>=3.11'\n"
    )
    (member / "uv.lock").write_text("version = 1\n")
    from uvloom_cli.config import load_project

    workspace = load_project(root)
    monkeypatch.chdir(member)
    _seed_current_marker(workspace, tmp_path, monkeypatch)
    calls = _patch_build_seams(monkeypatch, root)
    with pytest.raises(_Exec) as exc:
        commands.cmd_run(["true"])
    assert exc.value.root == root
    assert "build" not in calls

    # Remove valid cache state: cold build must still target workspace root,
    # not discard config.load_project() and fail from member directory.
    (root / ".venv").unlink()
    with pytest.raises(_Exec) as exc:
        commands.cmd_run(["true"])
    assert exc.value.root == root
    assert calls["build"][1]["deps_spec"] == "workspace-default"


def test_run_standalone_locked_nested_project_uses_child_hot_cache(tmp_path, monkeypatch):
    outer = tmp_path / "outer"
    child = outer / "tools" / "child"
    child.mkdir(parents=True)
    (outer / "pyproject.toml").write_text(
        "[project]\nname='outer'\nversion='0'\nrequires-python='>=3.11'\n"
    )
    (outer / "uv.lock").write_text("version = 1\n")
    (child / "pyproject.toml").write_text(
        "[project]\nname='child'\nversion='0'\nrequires-python='>=3.11'\n"
    )
    (child / "uv.lock").write_text("version = 1\n")
    from uvloom_cli.config import load_project

    project = load_project(child)
    monkeypatch.chdir(child)
    _seed_current_marker(project, tmp_path, monkeypatch)
    calls = _patch_build_seams(monkeypatch, child)
    with pytest.raises(_Exec) as exc:
        commands.cmd_run(["true"])
    assert exc.value.root == child
    assert "build" not in calls


def test_exec_in_venv_overwrites_inherited_repo_root(project, monkeypatch, tmp_path):
    store = tmp_path / "store"
    (store / "bin").mkdir(parents=True)
    monkeypatch.setenv("REPO_ROOT", "/wrong/project")
    monkeypatch.setattr(envkey, "_valid_store_venv", lambda path: True)

    def fake_exec(_cmd, env):
        raise _Execed([], env)

    monkeypatch.setattr(commands, "execvpe", fake_exec)
    with pytest.raises(_Execed) as exc:
        commands._exec_in_venv(project.root, ["true"], interpreter=None, store_path=str(store))
    assert exc.value.env["REPO_ROOT"] == str(project.root)


def test_exec_in_venv_rejects_tampered_non_store_marker_path(project, tmp_path):
    with pytest.raises(CliError, match="valid Nix-store virtual environment"):
        commands._exec_in_venv(
            project.root, ["true"], interpreter=None, store_path=str(tmp_path / "not-store")
        )


@pytest.mark.parametrize(
    "sources",
    [
        pytest.param(None, id="old-schema-source-dirs"),
        pytest.param(["x"], id="flat-strings"),
        pytest.param([[1, 2]], id="non-string-pair"),
        pytest.param([["tree"]], id="short-pair"),
        pytest.param("pkgs/a", id="not-a-list"),
    ],
)
def test_run_hot_path_falls_through_on_malformed_sources(
    project, monkeypatch, tmp_path, sources
):
    # A marker written by an older CLI (source_dirs, no sources) or corrupted
    # on disk must take the cold path — never crash the hot path, never hit
    # stale.
    monkeypatch.chdir(project.root)
    monkeypatch.delenv("UV_PYTHON", raising=False)
    monkeypatch.delenv("UV_NO_BINARY", raising=False)

    _seed_current_marker(project, tmp_path, monkeypatch)
    stub = commands._paths_stub(project.root)
    marker = envkey.read_marker(stub)
    if sources is None:
        del marker["config"]["sources"]
        marker["config"]["source_dirs"] = []
    else:
        marker["config"]["sources"] = sources
    envkey.write_marker(stub, marker)
    calls = _patch_build_seams(monkeypatch, project.root)

    with pytest.raises(_Exec):
        commands.cmd_run(["true"])
    assert "build" in calls


def test_run_hot_hit_trusts_cached_interpreter_while_request_matches(
    project, monkeypatch, tmp_path
):
    # The cached interpreter was resolved against the request still in
    # effect -> a key hit may keep exporting it.
    monkeypatch.chdir(project.root)
    monkeypatch.delenv("UV_PYTHON", raising=False)
    monkeypatch.delenv("UV_NO_BINARY", raising=False)
    (project.root / ".python-version").write_text("3.12\n")
    python = tmp_path / "python3.12"
    python.write_text("#!/bin/sh\n")
    python.chmod(0o755)

    _seed_current_marker(
        project,
        tmp_path,
        monkeypatch,
        request="3.12",
        interpreter=str(python),
        interpreter_request="3.12",
    )
    calls = _patch_build_seams(monkeypatch, project.root)

    with pytest.raises(_Exec) as exc:
        commands.cmd_run(["true"])
    assert exc.value.interpreter == str(python)
    assert "build" not in calls


def test_run_hot_hit_drops_cached_interpreter_after_request_drift(
    project, monkeypatch, tmp_path
):
    # resolve_interpreter (passthrough UV_PYTHON=...) rewrites the marker's
    # interpreter fields WITHOUT changing the env key: a later plain run
    # still key-hits, but the cached interpreter belongs to the other
    # request and must not be handed on for UV_PYTHON export.
    monkeypatch.chdir(project.root)
    monkeypatch.delenv("UV_PYTHON", raising=False)
    monkeypatch.delenv("UV_NO_BINARY", raising=False)
    (project.root / ".python-version").write_text("3.12\n")

    _seed_current_marker(
        project,
        tmp_path,
        monkeypatch,
        request="3.12",
        interpreter="/nix/store/fake/bin/python3.13",
        interpreter_request="3.13",
    )
    calls = _patch_build_seams(monkeypatch, project.root)

    with pytest.raises(_Exec) as exc:
        commands.cmd_run(["true"])
    assert exc.value.interpreter is None  # distrusted, not the 3.13 path
    assert "build" not in calls  # still a hot hit — only the interpreter drops


@pytest.mark.parametrize("bogus", [42, ["x"], {"path": "x"}], ids=["int", "list", "dict"])
def test_run_hot_hit_ignores_non_string_cached_interpreter(
    project, monkeypatch, tmp_path, bogus
):
    # Marker JSON is user-writable: a non-string interpreter must never be
    # exported and never crash the hot path.
    monkeypatch.chdir(project.root)
    monkeypatch.delenv("UV_PYTHON", raising=False)
    monkeypatch.delenv("UV_NO_BINARY", raising=False)

    _seed_current_marker(project, tmp_path, monkeypatch, interpreter=bogus)
    calls = _patch_build_seams(monkeypatch, project.root)

    with pytest.raises(_Exec) as exc:
        commands.cmd_run(["true"])
    assert exc.value.interpreter is None
    assert "build" not in calls


@pytest.mark.parametrize("config", ["corrupted", 7, ["editable"]], ids=["string", "int", "list"])
def test_run_falls_through_on_non_dict_marker_config(
    project, monkeypatch, tmp_path, config
):
    # Marker JSON is user-writable: a config of the wrong type must take the
    # cold path with pristine defaults — never crash cmd_run.
    monkeypatch.chdir(project.root)
    monkeypatch.delenv("UV_PYTHON", raising=False)
    monkeypatch.delenv("UV_NO_BINARY", raising=False)

    _seed_current_marker(project, tmp_path, monkeypatch)
    stub = commands._paths_stub(project.root)
    marker = envkey.read_marker(stub)
    marker["config"] = config
    envkey.write_marker(stub, marker)
    calls = _patch_build_seams(monkeypatch, project.root)

    with pytest.raises(_Exec):
        commands.cmd_run(["true"])
    assert "build" in calls
    # The bogus config must not leak into the sticky selections.
    assert calls["build"][1]["deps_spec"] is None
    assert calls["build"][1]["editable"] is None


@pytest.mark.parametrize(
    ("field", "value"),
    [
        pytest.param("deps_spec", 42, id="int-deps_spec"),
        pytest.param("sources", {"kind": "tree"}, id="dict-sources"),
        pytest.param("editable", "yes", id="string-editable"),
        pytest.param("declared_meta", ["README.md"], id="list-declared_meta"),
        pytest.param(
            "declared_meta", {"paths": [1], "globs": []}, id="non-string-meta-paths"
        ),
    ],
)
def test_run_falls_through_on_wrong_typed_cached_field(
    project, monkeypatch, tmp_path, field, value
):
    # Marker JSON is user-writable: a wrong-typed cached field (e.g.
    # "deps_spec": 42) must read as a cache miss and take the cold path —
    # a raw TypeError from compute_key or driver._deps_line is a crash on
    # the hot path. The bogus value must also not leak into the sticky
    # selections the cold path replays.
    monkeypatch.chdir(project.root)
    monkeypatch.delenv("UV_PYTHON", raising=False)
    monkeypatch.delenv("UV_NO_BINARY", raising=False)

    _seed_current_marker(project, tmp_path, monkeypatch)
    stub = commands._paths_stub(project.root)
    marker = envkey.read_marker(stub)
    marker["config"][field] = value
    envkey.write_marker(stub, marker)
    calls = _patch_build_seams(monkeypatch, project.root)

    with pytest.raises(_Exec):
        commands.cmd_run(["true"])
    assert "build" in calls
    if field == "deps_spec":
        assert calls["build"][1]["deps_spec"] is None
    else:
        assert calls["build"][1]["deps_spec"] == "workspace-default"
    if field == "editable":
        assert calls["build"][1]["editable"] is None


# --- cmd_check: flag parsing -----------------------------------------------------


@pytest.mark.parametrize(
    ("argv", "msg"),
    [
        (["--group", "--"], "--group requires a value"),
        (["--group="], "invalid --group name ''"),
        (["--group"], "--group requires a value"),
        (["--paths", "--"], "--paths requires a value"),
        (["--paths="], "--paths requires a value"),
        (["--paths"], "--paths requires a value"),
    ],
)
def test_check_value_flag_without_value_errors(argv, msg):
    with pytest.raises(CliError, match=msg):
        commands.cmd_check(argv)


def test_check_boolean_with_equals_is_unknown():
    with pytest.raises(CliError, match="unknown flag '--no-hammer=x' for 'uvloom check'"):
        commands.cmd_check(["--no-hammer=x"])


def test_check_equals_forms_match_two_token_forms(project, monkeypatch):
    monkeypatch.chdir(project.root)
    project.lock_path.write_text("version = 1\n")
    captured = []

    def fake_render(proj, **kwargs):
        captured.append(kwargs)
        return proj.root / "check.driver.nix"

    monkeypatch.setattr(driver, "render_driver", fake_render)
    monkeypatch.setattr(nixrun, "nix_build", lambda *args, **kwargs: None)

    rc = commands.cmd_check(["--group=g1", "--paths=tests/x", "--", "-k", "foo"])
    assert rc == 0
    assert captured[0]["check_groups"] == ("g1",)
    assert captured[0]["check_paths"] == ("tests/x",)
    assert captured[0]["check_flags"] == ("-k", "foo")

    rc = commands.cmd_check(["--group", "g1", "--paths", "tests/x", "--", "-k", "foo"])
    assert rc == 0
    assert captured[1] == captured[0]


@pytest.mark.parametrize(
    "argv",
    [
        ["--include=utils", "--include", "extra_dir"],
        ["--include", "utils", "--include=extra_dir"],
    ],
    ids=["equals-then-two-token", "two-token-then-equals"],
)
def test_check_include_widens_source_but_not_pytest_paths(project, monkeypatch, argv):
    monkeypatch.chdir(project.root)
    project.lock_path.write_text("version = 1\n")
    captured = []

    def fake_render(proj, **kwargs):
        captured.append(kwargs)
        return proj.root / "check.driver.nix"

    monkeypatch.setattr(driver, "render_driver", fake_render)
    monkeypatch.setattr(nixrun, "nix_build", lambda *args, **kwargs: None)

    rc = commands.cmd_check(argv)
    assert rc == 0
    # --include only widens the filtered source; pytest still runs the
    # default tests/ path.
    assert captured[0]["check_paths"] == ("tests",)
    assert captured[0]["extra_source_paths"] == ("tests", "utils", "extra_dir")


@pytest.mark.parametrize(
    ("argv", "msg"),
    [
        (["--include", "--"], "--include requires a value"),
        (["--include="], "--include requires a value"),
        (["--include"], "--include requires a value"),
    ],
)
def test_check_include_without_value_errors(argv, msg):
    with pytest.raises(CliError, match=msg):
        commands.cmd_check(argv)


def test_parse_env_flags_accepts_equals_values_like_two_token_forms():
    equals = commands._parse_env_flags(
        ["--group=dev", "--extra=pg"], command="sync"
    )
    two_token = commands._parse_env_flags(
        ["--group", "dev", "--extra", "pg"], command="sync"
    )
    assert equals == two_token
    assert equals["groups"] == ["dev"]
    assert equals["extras"] == ["pg"]


def test_parse_env_flags_equals_empty_value_is_invalid_name():
    with pytest.raises(CliError, match="invalid --group name ''"):
        commands._parse_env_flags(["--group="], command="sync")


@pytest.mark.parametrize("bad", ["a;b", "a,b", "with space", "quote'"])
def test_parse_env_flags_rejects_names_outside_charset(bad):
    with pytest.raises(CliError, match="allowed characters"):
        commands._parse_env_flags(["--group", bad], command="sync")


def test_parse_env_flags_boolean_with_equals_is_unknown():
    with pytest.raises(CliError, match="unknown flag '--force=x' for 'uvloom sync'"):
        commands._parse_env_flags(["--force=x"], command="sync")


def test_ensure_lock_signal_exit_uses_shell_status(tmp_path, monkeypatch):
    project = types.SimpleNamespace(root=tmp_path, lock_path=tmp_path / "uv.lock")
    monkeypatch.setattr(nixrun, "uv_binary", lambda: "/fake/uv")

    def fake_run(args, *, cwd, env):
        assert args == ["/fake/uv", "lock"]
        assert cwd == tmp_path
        assert env["UV_NO_SYNC"] == "1"
        assert env["UV_PYTHON_DOWNLOADS"] == "never"
        return subprocess.CompletedProcess(args, -2)

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(SystemExit) as exc:
        commands._ensure_lock(project)
    assert exc.value.code == 130


def test_ensure_lock_strips_uv_project_selectors(tmp_path, monkeypatch):
    root = tmp_path / "selected"
    other = tmp_path / "selector-target"
    root.mkdir()
    other.mkdir()
    project = types.SimpleNamespace(root=root, lock_path=root / "uv.lock")
    monkeypatch.setattr(nixrun, "uv_binary", lambda: "/fake/uv")
    monkeypatch.setenv("UV_PROJECT", str(other))
    monkeypatch.setenv("UV_WORKING_DIR", str(other.parent))
    captured = {}

    def fake_run(args, *, cwd, env):
        captured.update(args=args, cwd=cwd, env=env)
        (cwd / "uv.lock").write_text("version = 1\n")
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)

    commands._ensure_lock(project, quiet=True)

    assert captured["args"] == ["/fake/uv", "lock"]
    assert captured["cwd"] == root
    assert "UV_PROJECT" not in captured["env"]
    assert "UV_WORKING_DIR" not in captured["env"]
    assert captured["env"]["UV_NO_SYNC"] == "1"
    assert captured["env"]["UV_PYTHON_DOWNLOADS"] == "never"
    assert project.lock_path.exists()
    assert not (other / "uv.lock").exists()


def test_ensure_lock_existing_lock_does_not_strip_or_run(tmp_path, monkeypatch):
    project = types.SimpleNamespace(root=tmp_path, lock_path=tmp_path / "uv.lock")
    project.lock_path.write_text("version = 1\n")
    monkeypatch.setenv("UV_PROJECT", str(tmp_path / "other"))
    monkeypatch.setenv("UV_WORKING_DIR", str(tmp_path))
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: pytest.fail("ran uv lock"))

    commands._ensure_lock(project, quiet=True)


# --- cmd_sync: editable refresh orchestration ----------------------------------


def test_sync_refreshes_editable_but_preserves_non_editable_cache_semantics(
    project, monkeypatch
):
    monkeypatch.chdir(project.root)
    project.lock_path.write_text("version = 1\n")
    builds = []

    monkeypatch.setattr(driver, "ensure_not_foreign", lambda project, *, force: None)

    def fake_build(project, **kwargs):
        builds.append(kwargs)
        return "/nix/store/fake-env"

    monkeypatch.setattr(driver, "build_venv", fake_build)

    assert commands.cmd_sync([]) == 0
    assert builds[-1]["editable"] is True
    assert builds[-1]["force"] is True

    assert commands.cmd_sync(["--no-editable"]) == 0
    assert builds[-1]["editable"] is False
    assert builds[-1]["force"] is False


# --- cmd_venv ------------------------------------------------------------------


def test_cmd_venv_prints_store_path_to_stdout(project, monkeypatch, capsys):
    monkeypatch.chdir(project.root)

    def fake_build(opts, **kwargs):
        return commands._paths_stub(project.root), "/nix/store/abc-demo-env"

    monkeypatch.setattr(commands, "_load_and_build", fake_build)
    assert commands.cmd_venv([]) == 0
    captured = capsys.readouterr()
    # stdout carries ONLY the store path (scriptable); nothing on stderr.
    assert captured.out == "/nix/store/abc-demo-env\n"
    assert captured.err == ""


# --- cmd_run: PEP 723 scripts reject project-env flags --------------------------


@pytest.mark.parametrize(
    "flags",
    [["--group", "dev"], ["--extra", "pg"], ["--all-groups"], ["--no-editable"], ["--force"]],
)
def test_run_script_rejects_project_env_flags(tmp_path, monkeypatch, flags):
    script = tmp_path / "script.py"
    script.write_text("# /// script\n# dependencies = []\n# ///\nprint('hi')\n")
    monkeypatch.chdir(tmp_path)
    with pytest.raises(CliError, match="only apply to project environments"):
        commands.cmd_run([*flags, str(script)])


def test_run_script_exec_env_carries_uv_guards(tmp_path, monkeypatch):
    # _run_script's exec must ship the same hygiene as _exec_in_venv: a
    # nested uv inside a PEP 723 script would otherwise sync into a project
    # .venv (UV_NO_SYNC) or download an interpreter (UV_PYTHON_DOWNLOADS),
    # and inherited PYTHONPATH would shadow the script venv's site-packages.
    script = tmp_path / "script.py"
    script.write_text("# /// script\n# dependencies = []\n# ///\nprint('hi')\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("UV_NO_SYNC", "0")
    monkeypatch.setenv("PYTHONPATH", "/elsewhere")
    monkeypatch.setenv("UV_PYTHON_DOWNLOADS", "automatic")

    store = tmp_path / "script-store"
    (store / "bin").mkdir(parents=True)
    monkeypatch.setattr(
        driver, "build_script_venv", lambda s, **kwargs: str(store)
    )

    def fake_execvpe(cmd, env):
        raise _Execed(cmd, env)

    monkeypatch.setattr(commands, "execvpe", fake_execvpe)
    with pytest.raises(_Execed) as exc:
        commands.cmd_run([str(script), "arg"])
    env = exc.value.env
    assert exc.value.cmd == [f"{store}/bin/python", str(script), "arg"]
    assert env["UV_NO_SYNC"] == "1"
    assert env["UV_PYTHON_DOWNLOADS"] == "never"
    assert "PYTHONPATH" not in env
    assert env["VIRTUAL_ENV"] == str(store)
    assert env["PATH"].startswith(f"{store}/bin{os.pathsep}")



@pytest.mark.parametrize(
    ("source", "is_script"),
    [
        pytest.param(
            "# /// script\n# dependencies = []\n# ///\nprint('hi')\n",
            True,
            id="complete-top-level-block",
        ),
        pytest.param(
            'marker = """# /// script\n# ///"""\n',
            False,
            id="marker-in-string",
        ),
        pytest.param(
            "if True:\n    # /// script\n    # dependencies = []\n    # ///\n",
            False,
            id="indented-marker",
        ),
        pytest.param(
            "# /// script\n# dependencies = []\nprint('hi')\n",
            False,
            id="unmatched-block",
        ),
        pytest.param(
            b"# coding: definitely-not-a-codec\n# /// script\n# ///\n",
            False,
            id="malformed-source",
        ),
    ],
)
def test_run_routes_only_complete_top_level_pep723_block(
    project, monkeypatch, source, is_script
):
    script = project.root / "routing.py"
    if isinstance(source, bytes):
        script.write_bytes(source)
    else:
        script.write_text(source)
    monkeypatch.chdir(project.root)
    calls = _patch_build_seams(monkeypatch, project.root)
    routed = []

    def fake_run_script(path, args, opts):
        routed.append((path, args, opts))
        return 17

    monkeypatch.setattr(commands, "_run_script", fake_run_script)

    if is_script:
        assert commands.cmd_run([str(script), "arg"]) == 17
        assert routed[0][:2] == (script, ["arg"])
        assert "build" not in calls
    else:
        with pytest.raises(_Exec) as exc:
            commands.cmd_run([str(script), "arg"])
        assert exc.value.cmd == [str(script), "arg"]
        assert not routed
        assert "build" in calls



def test_run_script_threads_quiet_to_build(tmp_path, monkeypatch):
    # -q on `uvloom run script.py` must reach build_script_venv so its
    # informational lock-bootstrap line is suppressed (same contract as
    # _ensure_lock on the project path).
    script = tmp_path / "script.py"
    script.write_text("# /// script\n# dependencies = []\n# ///\nprint('hi')\n")
    monkeypatch.chdir(tmp_path)
    seen = {}

    def fake_build(s, *, hammer, verbose, quiet):
        seen["quiet"] = quiet
        return str(tmp_path / "store")

    monkeypatch.setattr(driver, "build_script_venv", fake_build)
    monkeypatch.setattr(
        commands, "execvpe", lambda cmd, env: (_ for _ in ()).throw(_Exec(None, cmd, None))
    )
    with pytest.raises(_Exec):
        commands.cmd_run(["-q", str(script)])
    assert seen["quiet"] is True


# --- _exec_in_venv -------------------------------------------------------------


class _Execed(Exception):
    def __init__(self, cmd, env):
        super().__init__("execed")
        self.cmd = cmd
        self.env = env


@pytest.fixture
def capture_exec(monkeypatch):
    def fake_execvpe(cmd, env):
        raise _Execed(cmd, env)

    monkeypatch.setattr(commands, "execvpe", fake_execvpe)
    monkeypatch.setattr(envkey, "_valid_store_venv", lambda _path: True)


def test_exec_in_venv_runs_plain_py_file_under_venv_python(project, monkeypatch, capture_exec):
    # A plain script (no shebang, not executable, no PEP 723 marker) must run
    # under the venv's python — uv run semantics — not be exec'd via PATH.
    script = project.root / "script.py"
    script.write_text("print('hi')\n")
    monkeypatch.chdir(project.root)
    with pytest.raises(_Execed) as exc:
        commands._exec_in_venv(project.root, [str(script), "--flag"], interpreter=None, store_path=str(project.root / ".venv"))
    python = str(project.root / ".venv" / "bin" / "python")
    assert exc.value.cmd == [python, str(script), "--flag"]


@pytest.mark.parametrize("module_flag", ["-m", "--module"])
def test_exec_in_venv_runs_module_under_venv_python(project, capture_exec, module_flag):
    with pytest.raises(_Execed) as exc:
        commands._exec_in_venv(
            project.root, [module_flag, "pytest", "-q"], interpreter=None, store_path=str(project.root / ".venv")
        )
    python = str(project.root / ".venv" / "bin" / "python")
    assert exc.value.cmd == [python, "-m", "pytest", "-q"]


def test_exec_in_venv_leaves_non_py_commands_alone(project, capture_exec):
    with pytest.raises(_Execed) as exc:
        commands._exec_in_venv(project.root, ["pytest", "-x"], interpreter=None, store_path=str(project.root / ".venv"))
    assert exc.value.cmd == ["pytest", "-x"]


def test_exec_in_venv_uses_validated_store_path_not_replaceable_venv_symlink(
    project, capture_exec, tmp_path
):
    old = tmp_path / "old-store"
    new = tmp_path / "new-store"
    old.mkdir()
    new.mkdir()
    (project.root / ".venv").symlink_to(new)

    with pytest.raises(_Execed) as exc:
        commands._exec_in_venv(
            project.root, ["pytest"], interpreter=None, store_path=str(old)
        )

    assert exc.value.env["VIRTUAL_ENV"] == str(old)
    assert exc.value.env["PATH"].split(os.pathsep)[0] == str(old / "bin")


def test_exec_in_venv_leaves_nonexistent_py_token_alone(project, capture_exec):
    # 'missing.py' that is not a file on disk is treated as a PATH command.
    with pytest.raises(_Execed) as exc:
        commands._exec_in_venv(project.root, ["missing.py"], interpreter=None, store_path=str(project.root / ".venv"))
    assert exc.value.cmd == ["missing.py"]


def test_exec_in_venv_forces_uv_no_sync_over_user_export(project, monkeypatch, capture_exec):
    # A user-exported UV_NO_SYNC=0 must not let nested uv clobber the
    # store-symlink venv (matches passthrough.py).
    monkeypatch.setenv("UV_NO_SYNC", "0")
    with pytest.raises(_Execed) as exc:
        commands._exec_in_venv(project.root, ["true"], interpreter=None, store_path=str(project.root / ".venv"))
    assert exc.value.env["UV_NO_SYNC"] == "1"


def test_exec_in_venv_exports_live_interpreter_as_public_and_private_python(
    project, monkeypatch, capture_exec, tmp_path
):
    monkeypatch.setenv("UV_PYTHON", "3.10")
    monkeypatch.setenv("UVLOOM_RESOLVED_PYTHON", "/hostile/python")
    python = tmp_path / "python3"
    python.write_text("#!/bin/sh\n")
    python.chmod(0o755)
    with pytest.raises(_Execed) as exc:
        commands._exec_in_venv(project.root, ["true"], interpreter=str(python), store_path=str(project.root / ".venv"))
    assert exc.value.env["UV_PYTHON"] == str(python)
    assert exc.value.env["UVLOOM_RESOLVED_PYTHON"] == str(python)


@pytest.mark.parametrize(
    "kind",
    ["missing", "directory", "non-executable", "empty", "int", "list"],
)
def test_exec_in_venv_removes_invalid_interpreter_exports_and_forbids_downloads(
    project, monkeypatch, capture_exec, tmp_path, kind
):
    # Cached marker data is user-writable and store paths can be GC'd. Neither
    # it nor hostile inherited exports may poison nested uv/uvloom execution.
    candidates = {
        "missing": str(tmp_path / "missing-python"),
        "directory": str(tmp_path / "python-dir"),
        "non-executable": str(tmp_path / "python-file"),
        "empty": "",
        "int": 42,
        "list": ["python"],
    }
    (tmp_path / "python-dir").mkdir()
    (tmp_path / "python-file").write_text("#!/bin/sh\n")
    monkeypatch.setenv("UV_PYTHON", "/hostile/public-python")
    monkeypatch.setenv("UVLOOM_RESOLVED_PYTHON", "/hostile/private-python")
    monkeypatch.setenv("UV_PYTHON_DOWNLOADS", "automatic")

    with pytest.raises(_Execed) as exc:
        commands._exec_in_venv(
            project.root, ["true"], interpreter=candidates[kind], store_path=str(project.root / ".venv")
        )
    assert "UV_PYTHON" not in exc.value.env
    assert "UVLOOM_RESOLVED_PYTHON" not in exc.value.env
    assert exc.value.env["UV_PYTHON_DOWNLOADS"] == "never"


def test_run_plain_py_file_execs_under_venv_python_end_to_end(project, monkeypatch):
    # Through cmd_run's cold path: the file has no PEP 723 marker, so it goes
    # to the project env — and lands on the venv's python inside _exec_in_venv.
    script = project.root / "tool.py"
    script.write_text("print('hi')\n")
    monkeypatch.chdir(project.root)

    def fake_build(opts, **kwargs):
        stub = commands._paths_stub(project.root)
        store = str(project.root / "fake-store")
        envkey.write_marker(stub, {"store_path": store})
        return stub, store

    def fake_execvpe(cmd, env):
        raise _Execed(cmd, env)

    monkeypatch.setattr(commands, "_load_and_build", fake_build)
    monkeypatch.setattr(envkey, "_valid_store_venv", lambda path: path.endswith("/fake-store"))
    monkeypatch.setattr(commands, "execvpe", fake_execvpe)
    with pytest.raises(_Execed) as exc:
        commands.cmd_run(["tool.py", "arg1"])
    python = str(project.root / "fake-store" / "bin" / "python")
    assert exc.value.cmd == [python, "tool.py", "arg1"]


# --- cmd_check: failure reporting ----------------------------------------------


def _fail_check_build(stderr):
    def fake_nix_build(*args, **kwargs):
        raise nixrun.NixBuildError("check build failed", stderr)

    return fake_nix_build


def _patch_check_build(project, monkeypatch, stderr):
    project.lock_path.write_text("version = 1\n")
    monkeypatch.chdir(project.root)
    monkeypatch.setattr(
        driver, "render_driver", lambda proj, **kwargs: proj.root / "check.driver.nix"
    )
    monkeypatch.setattr(nixrun, "nix_build", _fail_check_build(stderr))


def test_check_prints_final_pytest_derivation_log(project, monkeypatch, capsys):
    dependency_drv = "/nix/store/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa-dependency-1.0.drv"
    pytest_drv = "/nix/store/bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb-demo-pytest.drv"
    build_stderr = (
        f"error: builder for '{dependency_drv}' failed with exit code 1;\n"
        "       while evaluating an unrelated dependency\n"
        f"error: builder for '{pytest_drv}' failed with exit code 1;\n"
        "       last 1 log lines:\n"
        "       > stale pytest output from nix-build\n"
    )
    _patch_check_build(project, monkeypatch, build_stderr)
    log_calls = []

    def fake_nix_log(drv, *, cwd):
        log_calls.append((drv, cwd))
        return "pytest failure summary\nE       assert False\n"

    monkeypatch.setattr(nixrun, "nix_log", fake_nix_log)

    assert commands.cmd_check([]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "pytest failure summary\nE       assert False\n"
    assert log_calls == [(pytest_drv, project.root)]


def test_check_falls_back_to_nix_build_stderr_when_pytest_log_is_missing(
    project, monkeypatch, capsys
):
    pytest_drv = "/nix/store/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa-demo-pytest.drv"
    build_stderr = (
        f"error: builder for '{pytest_drv}' failed with exit code 1;\n"
        "       last 2 log lines:\n"
        "       > FAILED tests/test_demo.py::test_demo\n"
        "       > E       assert False\n"
    )
    _patch_check_build(project, monkeypatch, build_stderr)
    monkeypatch.setattr(nixrun, "nix_log", lambda drv, *, cwd: None)

    assert commands.cmd_check([]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == build_stderr.strip() + "\n"


def test_check_limits_pytest_log_to_last_200_lines(project, monkeypatch, capsys):
    pytest_drv = "/nix/store/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa-demo-pytest.drv"
    build_stderr = f"error: builder for '{pytest_drv}' failed with exit code 1;\n"
    _patch_check_build(project, monkeypatch, build_stderr)
    full_log = "\n".join(f"pytest log line {number:03d}" for number in range(205))
    monkeypatch.setattr(nixrun, "nix_log", lambda drv, *, cwd: full_log)

    assert commands.cmd_check([]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.splitlines() == full_log.splitlines()[-200:]
    assert "pytest log line 004" not in captured.err
    assert "pytest log line 005" in captured.err


def test_check_modern_failure_selects_pytest_log_and_limits_tail(
    project, monkeypatch, capsys
):
    dependency_drv = "/nix/store/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa-dependency-1.0.drv"
    pytest_drv = "/nix/store/bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb-demo-pytest.drv"
    build_stderr = (
        f"error: Cannot build '{dependency_drv}'.\n"
        "       Reason: builder failed with exit code 1.\n"
        f"error: Cannot build '{pytest_drv}'.\n"
        "       Reason: builder failed with exit code 1.\n"
        "       Last 1 log lines:\n"
        "       > stale embedded pytest output\n"
    )
    _patch_check_build(project, monkeypatch, build_stderr)
    log_calls = []
    full_log = "\n".join(f"modern pytest line {number:03d}" for number in range(205))

    def fake_nix_log(drv, *, cwd):
        log_calls.append((drv, cwd))
        return full_log

    monkeypatch.setattr(nixrun, "nix_log", fake_nix_log)

    assert commands.cmd_check([]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.splitlines() == full_log.splitlines()[-200:]
    assert "stale embedded pytest output" not in captured.err
    assert log_calls == [(pytest_drv, project.root)]


def test_check_modern_failure_falls_back_to_raw_embedded_log(
    project, monkeypatch, capsys
):
    pytest_drv = "/nix/store/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa-demo-pytest.drv"
    build_stderr = (
        f"error: Cannot build '{pytest_drv}'.\n"
        "       Reason: builder failed with exit code 1.\n"
        "       Last 2 log lines:\n"
        "       > FAILED tests/test_demo.py::test_demo\n"
        "       > E       assert False\n"
    )
    _patch_check_build(project, monkeypatch, build_stderr)
    monkeypatch.setattr(nixrun, "nix_log", lambda drv, *, cwd: None)

    assert commands.cmd_check([]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == build_stderr.strip() + "\n"


def test_check_modern_dependency_failure_translates_package_and_version(
    project, monkeypatch, no_nix
):
    dependency_drv = (
        "/nix/store/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa-"
        "python3.12-needs-pkgconf-2.4.1.drv"
    )
    build_stderr = (
        f"error: Cannot build '{dependency_drv}'.\n"
        "       Reason: builder failed with exit code 1.\n"
        "       Last 1 log lines:\n"
        "       > error: Program 'pkg-config' not found\n"
    )
    _patch_check_build(project, monkeypatch, build_stderr)

    with pytest.raises(CliError) as exc:
        commands.cmd_check([])

    msg = str(exc.value)
    assert "build of needs-pkgconf 2.4.1 failed" in msg
    assert "detected: 'pkg-config' is missing at build time" in msg
    assert '"needs-pkgconf" = prev."needs-pkgconf".overrideAttrs' in msg


def test_check_delegates_dependency_build_failure_to_translator(
    project, monkeypatch
):
    dependency_drv = "/nix/store/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa-dependency-1.0.drv"
    build_stderr = (
        f"error: builder for '{dependency_drv}' failed with exit code 1;\n"
        "       > dependency compilation failed\n"
    )
    _patch_check_build(project, monkeypatch, build_stderr)
    delegated = []

    class TranslatedFailure(Exception):
        pass

    def fake_raise_translated(err, translated_project):
        delegated.append((err, translated_project))
        raise TranslatedFailure

    monkeypatch.setattr(failures, "raise_translated", fake_raise_translated)

    with pytest.raises(TranslatedFailure):
        commands.cmd_check([])
    assert len(delegated) == 1
    err, translated_project = delegated[0]
    assert isinstance(err, nixrun.NixBuildError)
    assert err.stderr == build_stderr
    assert translated_project.root == project.root


# --- cmd_check: locking ----------------------------------------------------------
def test_check_lock_is_exclusive_flock(project):
    import fcntl
    import os

    with commands._check_lock(project):
        path = project.root / ".venv-uvloom-check.lock"
        fd = os.open(path, os.O_RDWR)
        try:
            # A second open file description cannot take the flock while held.
            with pytest.raises(BlockingIOError):
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        finally:
            os.close(fd)
