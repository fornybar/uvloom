"""Pass-through commands: exec the pinned uv binary.

uv never creates or mutates an environment: UV_NO_SYNC=1 always,
`--no-sync` appended where the subcommand supports it, and UV_PYTHON
points at the interpreter Nix will build against.
"""

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn

from .errors import CliError, execvpe

# Subcommands that rewrite pyproject.toml / uv.lock: run under subprocess so
# uv owns the TTY, then invalidate the environment cache.
MUTATING = frozenset({"add", "remove", "lock"})
# init mutates filesystem but creates a new project, never caller project's
# environment marker. Run it as subprocess for normal return/status handling.
_SUBPROCESS = MUTATING | frozenset({"init"})

# Of the pass-through set, only add/remove accept --no-sync.
_NO_SYNC_FLAG = frozenset({"add", "remove"})

# Commands that must work outside any project (spec req 1: `uvloom init`
# bootstraps one; `uvloom version` is project-independent).
_PROJECT_OPTIONAL = frozenset({"init", "version"})

# Mutators that must still reach pinned uv when an existing uv.lock is too new
# or malformed for uvloom's Nix-side interpreter resolution. Do not generalize:
# read-only passthroughs still require the project interpreter when a lock is
# present, while these commands are exactly how users repair/update the lock.
_INTERPRETER_OPTIONAL_ON_FAILURE = frozenset({"add", "remove", "lock"})

_BUILD_VALUE_FLAGS = frozenset(
    {
        "--project",
        "--directory",
        "--config-file",
        "--cache-dir",
        "--color",
        "--python",
        "-p",
        "--output-format",
        "--out-dir",
        "-o",
        "--package",
        "--build-constraints",
        "-b",
        "--index",
        "--default-index",
        "--index-url",
        "-i",
        "--extra-index-url",
        "--find-links",
        "-f",
        "--index-strategy",
        "--link-mode",
        "--keyring-provider",
        "--resolution",
        "--prerelease",
        "--no-build-isolation-package",
        "--no-build-package",
        "--no-binary-package",
        "--exclude-newer",
        "--exclude-newer-package",
        "--fork-strategy",
        "--config-setting",
        "-C",
        "--config-settings-package",
        "--upgrade-package",
        "-P",
        "--upgrade-group",
        "--no-sources-package",
        "--refresh-package",
        "--allow-insecure-host",
    }
)


def _pre_separator(rest: list[str]) -> list[str]:
    """Tokens before the first '--' separator (uv's own option space)."""
    try:
        return rest[: rest.index("--")]
    except ValueError:
        return rest


def _with_no_sync(uv: str, subcmd: str, rest: list[str]) -> list[str]:
    """argv with --no-sync placed in uv's own option space.

    Tokens after a '--' separator belong to the positional's argument space
    (uv would parse a trailing --no-sync as a requirement), so the flag is
    inserted before the first '--'; skipped when the user already passed it.
    """
    if subcmd not in _NO_SYNC_FLAG:
        return [uv, subcmd, *rest]
    head = _pre_separator(rest)
    if "--no-sync" in head:
        return [uv, subcmd, *rest]
    return [uv, subcmd, *head, "--no-sync", *rest[len(head):]]


# 'uv version' flags that consume a separate value token (from `uv version
# --help`; note -p is --python there, not --package). A bare token after any
# OTHER flag is NOT that flag's value — it is the positional VERSION. Flags
# missing from this list only over-classify as mutation (safe: subprocess +
# invalidate), never the reverse.
_VERSION_VALUE_FLAGS = frozenset(
    {
        "--bump",
        "--package",
        "--project",
        "--directory",
        "-p",
        "--python",
        "--output-format",
        "--color",
        "--config-file",
        "--cache-dir",
    }
)


def _version_mutates(rest: list[str]) -> bool:
    """True when 'uv version' argv sets a new version (positional or --bump).

    Plain 'uv version' (and --dry-run forms) only reads pyproject.toml; a
    positional VERSION or --bump rewrites it. Only tokens before '--' count.
    A bare token counts as a flag's value only after a known value-taking
    flag (_VERSION_VALUE_FLAGS) — value-less flags like -q never swallow the
    next token, so 'version -q 1.2.3' is still a mutation.
    """
    head = _pre_separator(rest)
    if "--dry-run" in head:
        return False
    expect_value = False
    for token in head:
        if expect_value:
            expect_value = False
            continue
        if token == "--bump" or token.startswith("--bump="):
            return True
        if token.startswith("-"):
            expect_value = token in _VERSION_VALUE_FLAGS
            continue
        return True  # positional VERSION
    return False


def _wants_help(rest: list[str]) -> bool:
    """True when -h/--help appears before a '--' separator.

    uv (clap) honors --help anywhere before '--', including after
    positionals ('uv add requests --help' prints help); tokens after
    '--' belong to the positional's own argument space.
    """
    for token in rest:
        if token in ("-h", "--help"):
            return True
        if token == "--":
            return False
    return False


def _build_source(rest: list[str]) -> str | None:
    """Best-effort parser for uv build's optional SRC positional."""
    expect_value = False
    for token in _pre_separator(rest):
        if expect_value:
            expect_value = False
            continue
        if token.startswith("-"):
            expect_value = token in _BUILD_VALUE_FLAGS
            continue
        return token
    return None


@dataclass(frozen=True)
class _Target:
    """Project-discovery target parsed from uv's global command options."""

    start: Path | None
    workdir: Path | None
    selected: bool
    script: bool
    valid: bool


def _target(rest: list[str], env: dict[str, str]) -> _Target:
    """Parse only target flags before ``--``; leave all validation to uv.

    uv 0.11.8 exposes --directory/UV_WORKING_DIR and --project/UV_PROJECT as
    global options. Duplicate or value-less target flags are intentionally not
    interpreted: forwarding untouched argv lets uv produce its native error,
    while preventing us from mutating a project discovered from caller cwd.
    ``--script`` targets a script, never a project environment.
    """
    directory = project = script = None
    seen: set[str] = set()
    head = _pre_separator(rest)
    i = 0
    while i < len(head):
        token = head[i]
        matched = None
        value = None
        for flag, name in (("--directory", "directory"), ("--project", "project"), ("--script", "script")):
            if token == flag:
                matched = name
                i += 1
                if i >= len(head) or head[i] == "--":
                    return _Target(None, None, True, False, False)
                value = head[i]
                break
            if token.startswith(flag + "="):
                matched = name
                value = token[len(flag) + 1 :]
                if not value:
                    return _Target(None, None, True, False, False)
                break
        if matched is not None:
            if matched in seen:
                return _Target(None, None, True, False, False)
            seen.add(matched)
            if matched == "directory":
                directory = value
            elif matched == "project":
                project = value
            else:
                script = value
        i += 1

    # Explicit flags override uv's corresponding environment settings.
    directory = directory if directory is not None else env.get("UV_WORKING_DIR")
    project = project if project is not None else env.get("UV_PROJECT")
    selected = directory is not None or project is not None or script is not None
    if script is not None:
        return _Target(None, None, selected, True, True)
    try:
        cwd = Path.cwd()
        workdir = (cwd / directory).resolve() if directory and not Path(directory).is_absolute() else (
            Path(directory).resolve() if directory else cwd
        )
        start = (workdir / project).resolve() if project and not Path(project).is_absolute() else (
            Path(project).resolve() if project else workdir
        )
    except OSError:
        return _Target(None, None, True, False, False)
    return _Target(start, workdir, selected, False, True)


def _project_for_passthrough(subcmd: str, rest: list[str], env: dict[str, str]):
    target = _target(rest, env)
    if not target.valid or target.script:
        return None

    start = target.start
    if subcmd == "build":
        source = _build_source(rest)
        if source is not None:
            if target.workdir is None:
                return None
            src = Path(source)
            resolved = (target.workdir / src).resolve() if not src.is_absolute() else src.resolve()
            if resolved.is_dir():
                start = resolved
            else:
                return None
        elif start is None:
            return None

    try:
        from .config import load_project

        return load_project(start)
    except CliError:
        if subcmd == "build":
            return None
        if not target.selected and subcmd not in _PROJECT_OPTIONAL:
            raise
        return None


def run_passthrough(subcmd: str, rest: list[str]) -> NoReturn:
    from .nixrun import uv_binary

    uv = uv_binary()
    env = dict(os.environ)
    env["UV_NO_SYNC"] = "1"
    env["UV_PYTHON_DOWNLOADS"] = "never"

    if _wants_help(rest):
        # Help output must never depend on project discovery or a Nix eval:
        # exec uv directly with the safety env only (no project, no UV_PYTHON).
        argv = _with_no_sync(uv, subcmd, rest)
        execvpe(argv, env)

    project = _project_for_passthrough(subcmd, rest, env)

    if project is not None and project.lock_path.exists():
        # Without uv.lock the Nix eval behind resolve_interpreter cannot
        # succeed; skip UV_PYTHON so bootstrap commands ('uvloom lock' on a
        # fresh project, 'uvloom add' before the first lock) still run uv.
        # Public interpreter requests are user input and must be validated
        # before the repair fallback below; only Nix-side lock/eval failures
        # may fall through to pinned uv without UV_PYTHON.
        from .config import python_version_request

        python_version_request(project)
        try:
            from .interpreter import resolve_interpreter

            env["UV_PYTHON"] = resolve_interpreter(project)
        except CliError:
            # Best-effort for project-optional commands; hard requirement
            # otherwise, except lock/add/remove must be able to
            # repair a malformed/newer uv.lock by executing uv without
            # UV_PYTHON rather than failing before uv sees the command.
            if (
                subcmd not in _PROJECT_OPTIONAL
                and subcmd not in _INTERPRETER_OPTIONAL_ON_FAILURE
                and subcmd != "build"
            ):
                raise

    argv = _with_no_sync(uv, subcmd, rest)

    if subcmd in _SUBPROCESS or (subcmd == "version" and _version_mutates(rest)):
        import subprocess

        rc = subprocess.run(argv, env=env).returncode
        if rc == 0 and project is not None and subcmd != "init":
            from .envkey import invalidate

            invalidate(project)
            if subcmd in ("add", "remove", "version") and not {"-q", "--quiet"} & set(
                _pre_separator(rest)
            ):
                print(
                    "uvloom: environment out of date — run 'uvloom sync'",
                    file=sys.stderr,
                )
        sys.exit(rc if rc >= 0 else 128 + (-rc))

    execvpe(argv, env)
