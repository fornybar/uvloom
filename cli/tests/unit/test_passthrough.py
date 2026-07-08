"""main.py dispatch + passthrough mutating-command behavior (fake uv stub)."""

import os
import subprocess
from pathlib import Path
import sys

import pytest

from uvloom_cli import envkey, passthrough
from uvloom_cli.errors import CliError
from uvloom_cli.main import _UNSUPPORTED, main
from uvloom_cli.passthrough import _build_source, _target, _version_mutates, _with_no_sync

from conftest import make_project, write_stub


def run_main(monkeypatch, *argv) -> int:
    monkeypatch.setattr(sys, "argv", ["uvloom", *argv])
    with pytest.raises(SystemExit) as exc:
        main()
    return exc.value.code


# --- dispatch: unknown / unsupported ------------------------------------------


def test_unknown_command_lists_supported(monkeypatch, capsys):
    assert run_main(monkeypatch, "frobnicate") == 1
    err = capsys.readouterr().err
    assert "uvloom: unknown command 'frobnicate'" in err
    for cmd in ("lock", "sync", "run", "venv", "check", "flakify"):
        assert cmd in err


@pytest.mark.parametrize("cmd", ["pip", "tool", "uvx", "publish", "self", "python"])
def test_known_unsupported_one_line_error(monkeypatch, capsys, cmd):
    assert run_main(monkeypatch, cmd) == 1
    err = capsys.readouterr().err
    lines = [ln for ln in err.splitlines() if ln]
    assert len(lines) == 1
    assert lines[0] == f"uvloom: {_UNSUPPORTED[cmd]}"


def test_no_args_prints_usage_exit_1(monkeypatch, capsys):
    assert run_main(monkeypatch) == 1
    captured = capsys.readouterr()
    assert "usage: uvloom" in captured.err
    assert captured.out == ""


def test_help_prints_usage_exit_0(monkeypatch, capsys):
    assert run_main(monkeypatch, "--help") == 0
    assert "usage: uvloom" in capsys.readouterr().out


def test_uncaught_oserror_is_one_line_error(monkeypatch, tmp_path):
    # Filesystem surprises must never traceback: one 'uvloom:' line (same
    # prefix as CliError), exit status 1 (SystemExit with a str message →
    # interpreter prints it to stderr and exits 1).
    from uvloom_cli import commands

    def boom(rest):
        raise NotADirectoryError(20, "Not a directory", str(tmp_path / ".venv"))

    monkeypatch.setattr(commands, "cmd_sync", boom)
    monkeypatch.setattr(sys, "argv", ["uvloom", "sync"])
    with pytest.raises(SystemExit) as exc:
        main()
    message = exc.value.code
    assert isinstance(message, str)
    assert message.startswith("uvloom: ")
    assert "\n" not in message


def test_keyboard_interrupt_exits_130(monkeypatch):
    from uvloom_cli import commands

    def interrupted(rest):
        raise KeyboardInterrupt

    monkeypatch.setattr(commands, "cmd_sync", interrupted)
    assert run_main(monkeypatch, "sync") == 130


# --- mutating passthrough (fake uv via UVLOOM_UV) -----------------------------


@pytest.fixture
def mutating_env(tmp_path, monkeypatch):
    """Locked project with a cached-interpreter marker + a recording fake uv."""
    project = make_project(tmp_path / "proj")
    (project.root / "uv.lock").write_text("version = 1\n")
    monkeypatch.chdir(project.root)

    # Cached interpreters are accepted only when they are regular executable files.
    interp = write_stub(tmp_path / "python-stub", "exit 0\n")
    from uvloom_cli import driver, interpreter

    driver_path = driver.render_driver(project)
    envkey.write_marker(
        project,
        {
            "key": "stale-key",
            "store_path": "/nix/store/old",
            "interpreter": str(interp),
            "interpreter_request": None,
            "interpreter_requires_python": ">=3.11",
            "interpreter_fingerprint": interpreter._cache_fingerprint(driver_path),
        },
    )

    record = tmp_path / "record"
    uv = write_stub(
        tmp_path / "uv",
        f'env > "{record}.env"\nprintf \'%s\\n\' "$@" > "{record}.args"\nexit 0\n',
    )
    monkeypatch.setenv("UVLOOM_UV", str(uv))
    return project, record, interp


def _recorded(record):
    env = {}
    for line in (record.parent / (record.name + ".env")).read_text().splitlines():
        k, _, v = line.partition("=")
        env[k] = v
    args = (record.parent / (record.name + ".args")).read_text().splitlines()
    return env, args


def test_mutating_add_invalidates_and_hints(monkeypatch, capsys, mutating_env):
    project, record, interp = mutating_env
    assert run_main(monkeypatch, "add", "requests") == 0

    env, args = _recorded(record)
    assert env["UV_NO_SYNC"] == "1"
    assert env["UV_PYTHON_DOWNLOADS"] == "never"
    assert env["UV_PYTHON"] == str(interp)
    assert args[:2] == ["add", "requests"]
    assert "--no-sync" in args  # add supports it

    # Environment cache invalidated; cached interpreter survives.
    marker = envkey.read_marker(project)
    assert "key" not in marker
    assert "store_path" not in marker
    assert marker["interpreter"] == str(interp)

    assert "environment out of date — run 'uvloom sync'" in capsys.readouterr().err


def test_mutating_add_quiet_suppresses_hint(monkeypatch, capsys, mutating_env):
    project, record, _ = mutating_env
    assert run_main(monkeypatch, "add", "requests", "--quiet") == 0
    assert "out of date" not in capsys.readouterr().err
    marker = envkey.read_marker(project)
    assert "key" not in marker  # still invalidated


def test_mutating_lock_invalidates_without_hint(monkeypatch, capsys, mutating_env):
    project, record, _ = mutating_env
    assert run_main(monkeypatch, "lock") == 0
    env, args = _recorded(record)
    assert env["UV_NO_SYNC"] == "1"
    assert args == ["lock"]
    assert "--no-sync" not in args  # lock does not support it
    assert "out of date" not in capsys.readouterr().err
    assert "key" not in envkey.read_marker(mutating_env[0])


def test_project_selector_uses_selected_project_for_interpreter_and_invalidation(
    monkeypatch, capsys, mutating_env, tmp_path
):
    cwd_project, record, _ = mutating_env
    selected = make_project(tmp_path / "selected")
    (selected.root / "uv.lock").write_text("version = 1\n")
    interp = write_stub(tmp_path / "selected-python", "exit 0\n")
    from uvloom_cli import driver, interpreter

    driver_path = driver.render_driver(selected)
    envkey.write_marker(
        selected,
        {
            "key": "selected-key", "store_path": "/nix/store/selected",
            "interpreter": str(interp), "interpreter_request": None,
                "interpreter_requires_python": ">=3.11",
                "interpreter_fingerprint": interpreter._cache_fingerprint(driver_path),
        },
    )

    assert run_main(monkeypatch, "add", "--project", str(selected.root), "requests") == 0
    env, args = _recorded(record)
    assert args[:4] == ["add", "--project", str(selected.root), "requests"]
    assert env["UV_PYTHON"] == str(interp)
    assert "key" not in envkey.read_marker(selected)
    assert envkey.read_marker(cwd_project)["key"] == "stale-key"
    assert "out of date" in capsys.readouterr().err


def test_directory_and_project_env_select_project(monkeypatch, mutating_env, tmp_path):
    cwd_project, record, _ = mutating_env
    selected = make_project(tmp_path / "base" / "project")
    (selected.root / "uv.lock").write_text("version = 1\n")
    interp = write_stub(tmp_path / "env-python", "exit 0\n")
    from uvloom_cli import driver, interpreter

    driver_path = driver.render_driver(selected)
    envkey.write_marker(selected, {
        "key": "selected-key", "store_path": "/nix/store/selected", "interpreter": str(interp),
        "interpreter_request": None, "interpreter_requires_python": ">=3.11",
        "interpreter_fingerprint": interpreter._cache_fingerprint(driver_path),
    })
    monkeypatch.setenv("UV_WORKING_DIR", str(selected.root.parent))
    monkeypatch.setenv("UV_PROJECT", "project")
    assert run_main(monkeypatch, "lock") == 0
    env = _recorded(record)[0]
    assert env["UV_PYTHON"] == str(interp)
    assert env["UV_WORKING_DIR"] == str(selected.root.parent)
    assert env["UV_PROJECT"] == "project"
    assert "key" not in envkey.read_marker(selected)
    assert envkey.read_marker(cwd_project)["key"] == "stale-key"


def test_script_target_never_invalidates_or_hints(monkeypatch, capsys, mutating_env):
    project, record, _ = mutating_env
    assert run_main(monkeypatch, "lock", "--script", "script.py") == 0
    assert _recorded(record)[1] == ["lock", "--script", "script.py"]
    assert envkey.read_marker(project)["key"] == "stale-key"
    assert "out of date" not in capsys.readouterr().err


def test_init_never_invalidates_cwd_project(monkeypatch, mutating_env):
    project, record, _ = mutating_env
    assert run_main(monkeypatch, "init", "new-project") == 0
    assert _recorded(record)[1] == ["init", "new-project"]
    assert envkey.read_marker(project)["key"] == "stale-key"


@pytest.mark.parametrize(
    "argv",
    [["--project"], ["--project", "one", "--project", "two"], ["--directory="]],
)
def test_invalid_target_syntax_does_not_touch_cwd_project(monkeypatch, mutating_env, argv):
    project, record, _ = mutating_env
    assert run_main(monkeypatch, "lock", *argv) == 0
    assert _recorded(record)[1] == ["lock", *argv]
    assert envkey.read_marker(project)["key"] == "stale-key"


def test_target_parser_preserves_separator_and_resolves_project_from_directory(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    target = _target(["--directory", "base", "--project=project", "--", "--project", "ignored"], {})
    assert target.valid and target.selected and not target.script
    assert target.start == (tmp_path / "base" / "project").resolve()


@pytest.mark.parametrize("cmd", ["lock", "add", "remove"])
def test_lock_add_remove_reach_uv_when_interpreter_resolution_fails(
    monkeypatch, capsys, mutating_env, cmd
):
    project, record, _ = mutating_env

    from uvloom_cli import interpreter

    monkeypatch.setattr(
        interpreter,
        "resolve_interpreter",
        lambda project: (_ for _ in ()).throw(CliError("bad lock")),
    )

    args = [cmd] if cmd == "lock" else [cmd, "requests"]
    assert run_main(monkeypatch, *args) == 0

    env, recorded = _recorded(record)
    assert recorded[: len(args)] == args
    assert "UV_PYTHON" not in env
    assert env["UV_NO_SYNC"] == "1"
    assert "key" not in envkey.read_marker(project)
    if cmd in ("add", "remove"):
        assert "--no-sync" in recorded
        assert "environment out of date — run 'uvloom sync'" in capsys.readouterr().err
    else:
        assert "--no-sync" not in recorded
        assert "out of date" not in capsys.readouterr().err


def test_mutating_add_rejects_invalid_uv_python_before_repair_fallback(
    monkeypatch, capsys, mutating_env
):
    _, record, _ = mutating_env
    monkeypatch.setenv("UV_PYTHON", "/not/a/version")

    assert run_main(monkeypatch, "add", "requests") == 1

    assert (
        "UV_PYTHON must be a MAJOR.MINOR[.PATCH] version like '3.12'"
        in capsys.readouterr().err
    )
    assert not (record.parent / (record.name + ".env")).exists()
    assert not (record.parent / (record.name + ".args")).exists()


def _write_locked_marker(project, interp, key="stale-key"):
    (project.root / "uv.lock").write_text("version = 1\n")
    from uvloom_cli import driver, interpreter

    driver_path = driver.render_driver(project)
    envkey.write_marker(
        project,
        {
            "key": key,
            "store_path": "/nix/store/old",
            "interpreter": str(interp),
            "interpreter_request": None,
            "interpreter_requires_python": ">=3.11",
            "interpreter_fingerprint": interpreter._cache_fingerprint(driver_path),
        },
    )


class _Exec(Exception):
    def __init__(self, cmd, env):
        super().__init__()
        self.cmd = cmd
        self.env = env


@pytest.fixture
def capture_exec(monkeypatch, tmp_path):
    uv = write_stub(tmp_path / "uv", "exit 0\n")
    monkeypatch.setenv("UVLOOM_UV", str(uv))

    def fake_exec(cmd, env):
        raise _Exec(cmd, env)

    monkeypatch.setattr(passthrough, "execvpe", fake_exec)
    return uv


def test_build_outside_project_with_directory_src_reaches_uv(monkeypatch, tmp_path, capture_exec):
    outside = tmp_path / "outside"
    outside.mkdir()
    src = outside / "srcpkg"
    make_project(src)
    monkeypatch.chdir(outside)

    with pytest.raises(_Exec) as exc:
        passthrough.run_passthrough("build", ["srcpkg"])

    assert exc.value.cmd == [str(capture_exec), "build", "srcpkg"]
    assert exc.value.env["UV_NO_SYNC"] == "1"
    assert exc.value.env["UV_PYTHON_DOWNLOADS"] == "never"
    assert "UV_PYTHON" not in exc.value.env


def test_build_uses_src_project_interpreter_not_cwd(monkeypatch, tmp_path, mutating_env, capture_exec):
    cwd_project, _, cwd_interp = mutating_env
    source = make_project(tmp_path / "source")
    src_interp = write_stub(tmp_path / "source-python", "exit 0\n")
    _write_locked_marker(source, src_interp, key="source-key")

    with pytest.raises(_Exec) as exc:
        passthrough.run_passthrough("build", ["../source"])

    assert exc.value.cmd == [str(capture_exec), "build", "../source"]
    assert exc.value.env["UV_PYTHON"] == str(src_interp)
    assert exc.value.env["UV_PYTHON"] != str(cwd_interp)
    assert envkey.read_marker(cwd_project)["key"] == "stale-key"
    assert envkey.read_marker(source)["key"] == "source-key"


@pytest.mark.parametrize("src", ["pkg-1.0.0.tar.gz", "does-not-exist"])
def test_build_archive_or_missing_src_does_not_bind_cwd(monkeypatch, tmp_path, mutating_env, capture_exec, src):
    cwd_project, _, _ = mutating_env
    if src.endswith(".tar.gz"):
        (cwd_project.root / src).write_text("archive")

    with pytest.raises(_Exec) as exc:
        passthrough.run_passthrough("build", [src])

    assert exc.value.cmd == [str(capture_exec), "build", src]
    assert "UV_PYTHON" not in exc.value.env
    assert envkey.read_marker(cwd_project)["key"] == "stale-key"


def test_build_without_src_inside_project_sets_python_without_invalidation(monkeypatch, mutating_env, capture_exec):
    project, _, interp = mutating_env

    with pytest.raises(_Exec) as exc:
        passthrough.run_passthrough("build", [])

    assert exc.value.env["UV_PYTHON"] == str(interp)
    assert envkey.read_marker(project)["key"] == "stale-key"


def test_build_directory_resolves_src_from_workdir(monkeypatch, tmp_path, capture_exec):
    outside = tmp_path / "outside"
    outside.mkdir()
    selected = make_project(tmp_path / "base" / "srcpkg")
    interp = write_stub(tmp_path / "src-python", "exit 0\n")
    _write_locked_marker(selected, interp, key="src-key")
    monkeypatch.chdir(outside)

    with pytest.raises(_Exec) as exc:
        passthrough.run_passthrough("build", ["--directory", str(tmp_path / "base"), "srcpkg"])

    assert exc.value.env["UV_PYTHON"] == str(interp)
    assert exc.value.cmd == [str(capture_exec), "build", "--directory", str(tmp_path / "base"), "srcpkg"]


def test_build_project_selects_interpreter_without_src(monkeypatch, tmp_path, capture_exec):
    outside = tmp_path / "outside"
    outside.mkdir()
    selected = make_project(tmp_path / "selected")
    interp = write_stub(tmp_path / "selected-python", "exit 0\n")
    _write_locked_marker(selected, interp, key="selected-key")
    monkeypatch.chdir(outside)

    with pytest.raises(_Exec) as exc:
        passthrough.run_passthrough("build", ["--project", str(selected.root)])

    assert exc.value.env["UV_PYTHON"] == str(interp)
    assert envkey.read_marker(selected)["key"] == "selected-key"


def test_build_project_plus_archive_prefers_archive_passthrough(monkeypatch, tmp_path, capture_exec):
    selected = make_project(tmp_path / "selected")
    interp = write_stub(tmp_path / "selected-python", "exit 0\n")
    _write_locked_marker(selected, interp, key="selected-key")
    (tmp_path / "pkg.tar.gz").write_text("archive")
    monkeypatch.chdir(tmp_path)

    with pytest.raises(_Exec) as exc:
        passthrough.run_passthrough("build", ["--project", str(selected.root), "pkg.tar.gz"])

    assert "UV_PYTHON" not in exc.value.env
    assert envkey.read_marker(selected)["key"] == "selected-key"


@pytest.mark.parametrize("argv", [["--project"], ["--project", "one", "--project", "two"], ["--directory="]])
def test_build_invalid_target_syntax_does_not_touch_cwd(monkeypatch, mutating_env, capture_exec, argv):
    project, _, _ = mutating_env

    with pytest.raises(_Exec) as exc:
        passthrough.run_passthrough("build", argv)

    assert exc.value.cmd == [str(capture_exec), "build", *argv]
    assert "UV_PYTHON" not in exc.value.env
    assert envkey.read_marker(project)["key"] == "stale-key"


def test_build_interpreter_resolution_failure_falls_back(monkeypatch, tmp_path, capture_exec):
    source = make_project(tmp_path / "source")
    interp = write_stub(tmp_path / "source-python", "exit 0\n")
    _write_locked_marker(source, interp, key="source-key")
    monkeypatch.chdir(tmp_path)
    from uvloom_cli import interpreter

    monkeypatch.setattr(interpreter, "resolve_interpreter", lambda project: (_ for _ in ()).throw(CliError("bad lock")))

    with pytest.raises(_Exec) as exc:
        passthrough.run_passthrough("build", ["source"])

    assert "UV_PYTHON" not in exc.value.env
    assert envkey.read_marker(source)["key"] == "source-key"


def test_build_invalid_public_uv_python_rejected(monkeypatch, tmp_path, capsys, capture_exec):
    source = make_project(tmp_path / "source")
    interp = write_stub(tmp_path / "source-python", "exit 0\n")
    _write_locked_marker(source, interp)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("UV_PYTHON", "/not/a/version")

    assert run_main(monkeypatch, "build", "source") == 1
    assert "UV_PYTHON must be a MAJOR.MINOR[.PATCH] version like '3.12'" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("rest", "source"),
    [
        (["--out-dir", "dist", "srcpkg"], "srcpkg"),
        (["--out-dir=dist", "srcpkg"], "srcpkg"),
        (["--package", "pkg"], None),
        (["--config-setting", "k=v", "srcpkg"], "srcpkg"),
        (["--", "srcpkg"], None),
    ],
)
def test_build_source_parser_skips_value_flags(rest, source):
    assert _build_source(rest) == source


def test_non_mutating_passthrough_still_requires_interpreter_when_lock_present(
    monkeypatch, mutating_env
):
    from uvloom_cli import interpreter

    monkeypatch.setattr(
        interpreter,
        "resolve_interpreter",
        lambda project: (_ for _ in ()).throw(CliError("bad lock")),
    )

    with pytest.raises(CliError, match="bad lock"):
        passthrough.run_passthrough("tree", [])


def test_mutating_failure_skips_invalidate(monkeypatch, tmp_path, mutating_env):
    project, record, _ = mutating_env
    failing = write_stub(tmp_path / "uv-fail", "exit 3\n")
    monkeypatch.setenv("UVLOOM_UV", str(failing))
    assert run_main(monkeypatch, "add", "requests") == 3
    # uv failed -> environment key untouched
    assert envkey.read_marker(project)["key"] == "stale-key"


def test_mutating_signal_exit_translates_and_skips_invalidate(monkeypatch, tmp_path, mutating_env):
    project, _, _ = mutating_env
    interrupting = write_stub(tmp_path / "uv-int", "kill -INT $$\n")
    monkeypatch.setenv("UVLOOM_UV", str(interrupting))

    assert run_main(monkeypatch, "add", "requests") == 130
    assert envkey.read_marker(project)["key"] == "stale-key"


# --- --no-sync placement (uv option space vs positional argument space) -------


def test_no_sync_inserted_before_separator():
    # Tokens after '--' belong to the positional's argument space; a trailing
    # --no-sync there would be parsed by uv as a requirement.
    assert _with_no_sync("uv", "add", ["--", "./pkg"]) == [
        "uv", "add", "--no-sync", "--", "./pkg",
    ]


def test_no_sync_appended_without_separator():
    assert _with_no_sync("uv", "add", ["requests"]) == ["uv", "add", "requests", "--no-sync"]


def test_no_sync_not_duplicated_when_user_passed_it():
    assert _with_no_sync("uv", "add", ["--no-sync", "requests"]) == [
        "uv", "add", "--no-sync", "requests",
    ]


def test_no_sync_after_separator_does_not_count_as_user_supplied():
    # A '--no-sync' AFTER '--' is a requirement, not uv's flag: the real flag
    # still lands in uv's option space.
    assert _with_no_sync("uv", "add", ["--", "--no-sync"]) == [
        "uv", "add", "--no-sync", "--", "--no-sync",
    ]


def test_no_sync_skipped_for_unsupporting_subcommand():
    assert _with_no_sync("uv", "lock", []) == ["uv", "lock"]


# --- uv version: mutation detection --------------------------------------------


@pytest.mark.parametrize(
    ("rest", "mutates"),
    [
        ([], False),
        (["--dry-run", "1.2.3"], False),
        (["--short"], False),
        (["1.2.3"], True),
        (["--bump", "minor"], True),
        (["--bump=minor"], True),
        # Value-less flags never swallow the next token: still a mutation.
        (["-q", "1.2.3"], True),
        (["--frozen", "1.2.3"], True),
        # Value-taking flags do consume their token: still read-only.
        (["--package", "sub"], False),
        (["--output-format", "json"], False),
        (["-p", "3.12"], False),
        (["--directory", "sub", "--short"], False),
        # ...but a positional after the consumed value mutates.
        (["--package", "sub", "1.2.3"], True),
    ],
)
def test_version_mutates(rest, mutates):
    assert _version_mutates(rest) is mutates


def test_version_set_invalidates_and_hints(monkeypatch, capsys, mutating_env):
    project, record, _ = mutating_env
    assert run_main(monkeypatch, "version", "1.2.3") == 0
    _, args = _recorded(record)
    assert args == ["version", "1.2.3"]
    assert "key" not in envkey.read_marker(project)
    assert "environment out of date — run 'uvloom sync'" in capsys.readouterr().err


def test_version_bump_invalidates_and_hints(monkeypatch, capsys, mutating_env):
    project, record, _ = mutating_env
    assert run_main(monkeypatch, "version", "--bump", "minor") == 0
    _, args = _recorded(record)
    assert args == ["version", "--bump", "minor"]
    assert "key" not in envkey.read_marker(project)
    assert "environment out of date — run 'uvloom sync'" in capsys.readouterr().err


def test_bare_version_read_only_execs_without_invalidating(monkeypatch, mutating_env):
    project, _, _ = mutating_env

    class _Exec(Exception):
        pass

    def fake_exec(cmd, env):
        raise _Exec()

    monkeypatch.setattr(passthrough, "execvpe", fake_exec)
    with pytest.raises(_Exec):
        passthrough.run_passthrough("version", [])
    # Read-only: the environment key must survive.
    assert envkey.read_marker(project)["key"] == "stale-key"


def test_lock_bootstrap_without_lockfile_skips_interpreter(monkeypatch, tmp_path):
    """A fresh project (no uv.lock) must reach uv: no Nix eval, no traceback."""
    project = make_project(tmp_path / "proj")
    monkeypatch.chdir(project.root)

    record = tmp_path / "record"
    uv = write_stub(
        tmp_path / "uv",
        f'env > "{record}.env"\nprintf \'%s\\n\' "$@" > "{record}.args"\nexit 0\n',
    )
    monkeypatch.setenv("UVLOOM_UV", str(uv))
    # Any nix invocation would fail loudly: nothing on PATH provides nix.
    assert run_main(monkeypatch, "lock") == 0

    env, args = _recorded(record)
    assert args == ["lock"]
    assert "UV_PYTHON" not in env  # unresolvable without a lock; skipped
    assert env["UV_NO_SYNC"] == "1"


def test_help_outside_project_execs_uv_directly(tmp_path):
    """`uvloom add --help` outside any project must exec uv: no load_project,
    no interpreter resolution, no Nix eval."""
    outside = tmp_path / "outside"
    outside.mkdir()

    record = tmp_path / "record"
    uv = write_stub(
        tmp_path / "uv",
        f'printf \'%s\\n\' "$@" > "{record}.args"\nexit 0\n',
    )

    cli_src = Path(__file__).resolve().parents[2] / "src"
    env = os.environ.copy()
    env["UVLOOM_UV"] = str(uv)
    env["PYTHONPATH"] = (
        str(cli_src)
        if not env.get("PYTHONPATH")
        else f"{cli_src}{os.pathsep}{env['PYTHONPATH']}"
    )

    proc = subprocess.run(
        [sys.executable, "-m", "uvloom_cli.main", "add", "requests", "--help"],
        cwd=outside,
        env=env,
        check=False,
    )

    assert proc.returncode == 0
    assert (record.parent / (record.name + ".args")).read_text().splitlines() == [
        "add",
        "requests",
        "--help",
        "--no-sync",
    ]
