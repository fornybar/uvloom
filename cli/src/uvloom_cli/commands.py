"""Environment commands: sync / run / venv / check.

Hot-path discipline: module-level imports are cheap stdlib only
(contextlib, fcntl, os, sys, types, pathlib) plus envkey (hashlib/json/fcntl). The cache-hit path
of cmd_run never parses toml and never spawns a process before exec: the
marker caches the config fields the key needs (editable/hammer/
source_preference/deps_spec/python request from .python-version); pyproject.toml itself is hashed
as raw bytes, so any config edit invalidates the key without parsing.
"""

import contextlib
import fcntl
import os
import sys
import types
from pathlib import Path

from . import envkey
from .errors import CliError, execvpe

_LOCK_FAILED_MSG = "'uv lock' failed — cannot build an environment without uv.lock"


# ---------------------------------------------------------------------------
# Hot-path helpers (stdlib only)


def _find_root(start: Path | None = None) -> Path | None:
    """Nearest project root, toml-free (hot path).

    Preserve fast path for ordinary one-project trees. Nested pyprojects need
    [tool.uv.workspace] membership parsing, so return None and let cold-path
    config.load_project decide. A nearest own lock is not enough: ancestor
    workspace membership can override it.
    """
    d = (start or Path.cwd()).resolve()
    candidates: list[Path] = []
    for p in (d, *d.parents):
        if not (p / "pyproject.toml").is_file():
            continue
        candidates.append(p)
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]
    return None


def _paths_stub(root: Path, discovery_start: Path | None = None) -> types.SimpleNamespace:
    """Duck-typed stand-in for config.Project carrying only paths (hot path)."""
    return types.SimpleNamespace(
        root=root,
        discovery_start=discovery_start or root,
        pyproject_path=root / "pyproject.toml",
        uv_toml_path=root / "uv.toml",
        lock_path=root / "uv.lock",
        overlay_path=root / "uv.nix",
    )


def _venv_env(venv: str) -> dict:
    """os.environ copy activating a store venv (project .venv or script env).

    PYTHONPATH is dropped for hermeticity — inherited entries would shadow
    the venv's site-packages. The UV guards keep a nested uv (run from
    inside the venv) from syncing into the store symlink or downloading an
    interpreter — same discipline as passthrough.py.
    """
    env = os.environ.copy()
    env["PATH"] = f"{os.path.join(venv, 'bin')}{os.pathsep}{env.get('PATH', '')}"
    env["VIRTUAL_ENV"] = venv
    env["UV_NO_SYNC"] = "1"  # a user-exported '0' must not let nested uv clobber the venv
    env["UV_PYTHON_DOWNLOADS"] = "never"
    env.pop("PYTHONPATH", None)
    env.pop("UV_PYTHON", None)
    env.pop("UVLOOM_RESOLVED_PYTHON", None)
    return env


def _exec_in_venv(
    root: Path, cmd: list[str], *, interpreter: str | None, store_path: str
) -> None:
    """exec cmd with the venv activated (PATH, VIRTUAL_ENV, REPO_ROOT).

    uv parity: an existing `.py` file (non-PEP-723 — inline scripts never
    reach here; cmd_run routes them to _run_script) runs under the venv's
    python rather than being exec'd via PATH, so it needs neither a
    shebang nor the executable bit.
    """
    # Validate again immediately before canonical exec. Cache validation can
    # race with marker tampering or store GC; never execute through a path the
    # marker did not prove to be a live Nix-built venv.
    if not envkey._valid_store_venv(store_path):
        raise CliError("environment marker does not reference a valid Nix-store virtual environment")
    # Use canonical store path, never mutable `.venv` GC-root symlink:
    # concurrent sync may atomically replace link between validation and exec.
    venv = Path(store_path)
    env = _venv_env(str(venv))
    # CLI execution owns this value.  Preserving REPO_ROOT inherited from a
    # different activated project makes editable .pth entries import that
    # other project's checkout.
    env["REPO_ROOT"] = str(root)
    # Guard against a dangling/non-executable cached path (store path GC'd
    # since the marker was written) and malformed user-writable marker data.
    # Override an inherited request with the interpreter this environment was
    # actually built for, and carry the same value privately so nested uvloom
    # can distinguish the resolved path from a public version request.
    if (
        isinstance(interpreter, str)
        and interpreter
        and os.path.isfile(interpreter)
        and os.access(interpreter, os.X_OK)
    ):
        env["UV_PYTHON"] = interpreter
        env["UVLOOM_RESOLVED_PYTHON"] = interpreter
    if cmd[0] in ("-m", "--module"):
        cmd = [str(venv / "bin" / "python"), "-m", *cmd[1:]]
    elif cmd[0].endswith(".py") and os.path.isfile(cmd[0]):
        cmd = [str(venv / "bin" / "python"), *cmd]
    execvpe(cmd, env)


def _ensure_lock(project, *, quiet: bool = False) -> None:
    """uv parity: sync/run/venv/check auto-create a missing uv.lock.

    Runs before any driver render/eval or key computation so nothing ever
    sees the lock-less state. Invokes uv directly (never the passthrough
    path, which would try to resolve UV_PYTHON via a Nix eval that itself
    needs the lock).
    """
    if project.lock_path.exists():
        return
    import subprocess

    from . import nixrun

    uv = nixrun.uv_binary()
    if not quiet:
        print("uvloom: no uv.lock — creating it via 'uv lock'", file=sys.stderr)
    env = os.environ.copy()
    # Native uvloom commands already selected `project`; inherited uv global
    # selectors must not redirect only the bootstrap lock to another project.
    env.pop("UV_PROJECT", None)
    env.pop("UV_WORKING_DIR", None)
    env["UV_NO_SYNC"] = "1"
    env["UV_PYTHON_DOWNLOADS"] = "never"
    rc = subprocess.run([uv, "lock"], cwd=project.root, env=env).returncode
    if rc < 0:
        raise SystemExit(128 + (-rc))
    if rc != 0 or not project.lock_path.exists():
        raise CliError(_LOCK_FAILED_MSG)


# ---------------------------------------------------------------------------
# Flag parsing (no argparse; keep the hot path lean)

# Group/extra names are spliced into the deps_spec grammar (';'/',' are its
# separators) and rendered into the driver; validate at parse time. Charset
# check without `re` — this runs on the hot path.
_NAME_CHARS = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-"
)


def _validate_name(flag: str, value: str) -> str:
    if not value or not _NAME_CHARS.issuperset(value):
        raise CliError(
            f"invalid {flag} name {value!r} — allowed characters: A-Z a-z 0-9 . _ -"
        )
    return value


def _validate_path(flag: str, value: str) -> str:
    # An empty path would render as "" in the driver's checkPaths /
    # extraSourcePaths lists and silently match nothing.
    if value == "":
        raise CliError(f"{flag} requires a value")
    return value


# Flag spec row: (takes_value, apply). `apply` mutates the opts dict; `value`
# is the flag's argument for value-taking rows and None for boolean rows.


def _set(key: str, const) -> tuple:
    return (False, lambda opts, _value: opts.__setitem__(key, const))


def _append(key: str, flag: str, validate) -> tuple:
    return (True, lambda opts, value: opts[key].append(validate(flag, value)))


def _parse_flags(
    argv: list[str], *, command: str, spec: dict, opts: dict, dashdash: str | None = None
) -> dict:
    """Table-driven flag parser shared by sync/run/venv (env flags) and check.

    Handles '--flag=value' and two-token '--flag value' forms, consumes the
    value token for value-taking flags, and rejects unknown flags (and '='
    values on boolean flags) with the command name in the message. When
    ``dashdash`` is set, a bare '--' stops parsing and stores the remaining
    tokens verbatim under that key (check's pytest passthrough).
    """
    i = 0
    while i < len(argv):
        arg = argv[i]
        raw_arg = arg
        value = None
        if dashdash is not None and arg == "--":
            opts[dashdash] = argv[i + 1 :]
            break
        if arg.startswith("--") and "=" in arg:
            arg, value = arg.split("=", 1)
        row = spec.get(arg)
        if value is not None and (row is None or not row[0]):
            raise CliError(f"unknown flag '{raw_arg}' for 'uvloom {command}'")
        if row is None:
            raise CliError(f"unknown flag '{arg}' for 'uvloom {command}'")
        takes_value, apply = row
        if takes_value and value is None:
            i += 1
            if i >= len(argv) or argv[i] == "--":
                raise CliError(f"{arg} requires a value")
            value = argv[i]
        apply(opts, value)
        i += 1
    return opts


# sync/run/venv share one flag surface (docs/cli.md: venv "takes the same
# flags as sync"); check has its own below (cmd_check).
_ENV_FLAG_SPEC = {
    "--all-groups": _set("all_groups", True),
    "--group": _append("groups", "--group", _validate_name),
    "--extra": _append("extras", "--extra", _validate_name),
    "--no-editable": _set("editable", False),
    "--include": _append("include", "--include", _validate_path),
    "--no-filter-source": _set("filter_source", False),
    "--no-hammer": _set("hammer", False),
    "--force": _set("force", True),
    "-v": _set("verbose", True),
    "--verbose": _set("verbose", True),
    "-q": _set("quiet", True),
    "--quiet": _set("quiet", True),
}

# Value-taking env flags — cmd_run's splitter needs them to consume the value
# token so 'run --group x -- cmd' parses.
_ENV_VALUE_FLAGS = frozenset(
    flag for flag, (takes_value, _) in _ENV_FLAG_SPEC.items() if takes_value
)


def _parse_env_flags(argv: list[str], *, command: str) -> dict:
    opts = {
        "all_groups": False,
        "groups": [],
        "extras": [],
        "editable": None,
        "hammer": None,
        "filter_source": None,
        "include": [],
        "force": False,
        "verbose": False,
        "quiet": False,
    }
    opts = _parse_flags(argv, command=command, spec=_ENV_FLAG_SPEC, opts=opts)
    if opts["filter_source"] is False and opts["include"]:
        raise CliError("--include cannot be used with --no-filter-source")
    return opts


def _deps_spec(opts: dict, default_groups=("dev",), *, default_groups_explicit: bool = True) -> str:
    extras = ",".join(sorted(set(opts["extras"])))
    if opts["all_groups"]:
        return "all-groups" if not extras else f"all-groups;extras={extras}"
    groups = ",".join(sorted(set(opts["groups"])))
    if not default_groups_explicit:
        if not groups and not extras:
            return "workspace-default"
        return f"groups={groups};extras={extras}"
    default = "all" if default_groups == "all" else ",".join(sorted(set(default_groups)))
    return f"default={default};groups={groups};extras={extras}"


# ---------------------------------------------------------------------------
# Cold-path build helper


def _load_and_build(
    opts: dict,
    *,
    deps_spec: str | None = None,
    editable: bool | None = None,
    hammer: bool | None = None,
    refresh_editable: bool = False,
) -> tuple:
    """load_project + guards + build_venv; returns (project, store_path)."""
    from . import driver
    from .config import load_project, source_preference

    project = load_project()
    _ensure_lock(project, quiet=opts["quiet"])
    driver.ensure_not_foreign(project, force=opts["force"])

    if opts["editable"] is not None:
        editable = opts["editable"]
    elif editable is None:
        editable = True
    if opts["hammer"] is not None:
        hammer = opts["hammer"]
    elif hammer is None:
        hammer = True
    spec = (
        _deps_spec(
            opts,
            project.config.default_groups,
            default_groups_explicit=project.config.default_groups_explicit,
        )
        if deps_spec is None
        else deps_spec
    )
    filter_source = True if opts.get("filter_source") is None else opts["filter_source"]
    extra_source_paths = tuple(opts.get("include") or []) if filter_source else ()

    store_path = driver.build_venv(
        project,
        editable=editable,
        deps_spec=spec,
        hammer=hammer,
        source_preference=source_preference(project.config),
        filter_source=filter_source,
        extra_source_paths=extra_source_paths,
        verbose=opts["verbose"],
        force=opts["force"] or refresh_editable,
    )
    return project, store_path


# ---------------------------------------------------------------------------
# sync


def cmd_sync(argv: list[str]) -> int:
    opts = _parse_env_flags(argv, command="sync")
    _, store_path = _load_and_build(
        opts, refresh_editable=opts["editable"] is not False
    )
    if not opts["quiet"]:
        print(f"synced .venv -> {store_path}", file=sys.stderr)
    return 0


# ---------------------------------------------------------------------------
# run


def _has_pep723_script_block(path: Path) -> bool:
    """Recognize a complete top-level PEP 723 script metadata block."""
    import tokenize

    try:
        source = tokenize.open(path)
    except (OSError, SyntaxError, UnicodeError):
        return False

    block_line: int | None = None
    try:
        with source:
            for token in tokenize.generate_tokens(source.readline):
                row, column = token.start
                if block_line is None:
                    if (
                        token.type == tokenize.COMMENT
                        and column == 0
                        and token.string == "# /// script"
                    ):
                        block_line = row
                    continue

                if row == block_line:
                    continue
                if (
                    row == block_line + 1
                    and token.type == tokenize.COMMENT
                    and column == 0
                ):
                    if token.string == "# ///":
                        return True
                    block_line = row
                    continue

                # Every metadata line must itself be a top-level comment.
                # Reconsider the current token as a possible new opener.
                block_line = (
                    row
                    if token.type == tokenize.COMMENT
                    and column == 0
                    and token.string == "# /// script"
                    else None
                )
    except (tokenize.TokenError, IndentationError, SyntaxError, UnicodeError):
        return False
    return False


def cmd_run(argv: list[str]) -> int:
    # Split uvloom flags from the command: '--' always separates; otherwise
    # the first token not starting with '-' begins the command. Value-taking
    # flags (from _ENV_FLAG_SPEC) consume their argument so
    # 'run --group x -- cmd' parses; _parse_env_flags does the real parsing.
    flags: list[str] = []
    cmd: list[str] = []
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--":
            cmd = argv[i + 1 :]
            break
        if arg in ("-m", "--module"):
            cmd = argv[i:]
            break
        if arg.startswith("-"):
            flags.append(arg)
            if arg in _ENV_VALUE_FLAGS:
                i += 1
                if i >= len(argv) or argv[i] == "--":
                    raise CliError(f"{arg} requires a value")
                flags.append(argv[i])
            i += 1
            continue
        cmd = argv[i:]
        break
    opts = _parse_env_flags(flags, command="run")

    if not cmd:
        raise CliError("provide a command to run")

    # PEP 723 inline script?  Tokenization keeps marker-looking bytes inside
    # strings from changing routing; the recognizer also requires a complete,
    # unindented comment block.
    if (
        cmd[0].endswith(".py")
        and os.path.isfile(cmd[0])
        and _has_pep723_script_block(Path(cmd[0]))
    ):
        # These flags shape project environments; _run_script only
        # honors --no-hammer/-v/-q. Reject the rest loudly instead of
        # silently ignoring them.
        if (
            opts["all_groups"]
            or opts["groups"]
            or opts["extras"]
            or opts["editable"] is not None
            or opts["include"]
            or opts["filter_source"] is not None
            or opts["force"]
        ):
            raise CliError(
                "--group/--extra/--all-groups/--no-editable/--include/--no-filter-source/--force only apply "
                "to project environments, not PEP 723 scripts"
            )
        return _run_script(Path(cmd[0]), cmd[1:], opts)

    start = Path.cwd().resolve()
    root = _find_root(start)
    if root is None:
        # Nested pyprojects need the cold parser to decide actual workspace
        # membership.  Keep its returned root for both cache lookup and exec.
        from .config import load_project

        root = load_project(start).root

    # Explicit dependency selection on `run` overrides the sticky sync-time
    # choice and, once built, becomes the new sticky selection for later
    # plain runs (same as sync).
    explicit_selection = bool(opts["all_groups"] or opts["groups"] or opts["extras"])
    explicit_source_selection = bool(opts["include"] or opts["filter_source"] is not None)

    stub = _paths_stub(root, start)
    marker = envkey.read_marker(stub)
    cached = marker.get("config") if marker else None
    # Marker JSON is user-writable: a malformed config (wrong type) must
    # fall through to the cold path, never crash the hot path.
    if not isinstance(cached, dict):
        cached = None
    # Typed field gate: the marker is user-writable JSON, so a wrong-typed
    # cached field (e.g. "deps_spec": 42) must read as a cache miss — it
    # would otherwise crash compute_key or the driver render. Absent and
    # malformed read the same: fall through to the cold path.
    required = {
        "editable": bool,
        "deps_spec": str,
        "hammer": bool,
        "sources": list,
        "source_preference": str,
        "declared_meta": dict,
    }
    if (
        cached
        and not opts["force"]
        and not explicit_selection
        and not explicit_source_selection
        and all(isinstance(cached.get(k), t) for k, t in required.items())
    ):
        # This setting cannot be represented by the cached project-wide
        # preference. Check it before a cache hit avoids TOML parsing.
        from .config import reject_unsupported_env_source_settings

        reject_unsupported_env_source_settings()
        request = envkey.effective_python_request(root, start)
        # Effective source preference, toml-free: UV_NO_BINARY beats the
        # marker's cached pyproject-derived value (the pyproject byte-hash
        # already covers toml edits). A mismatch changes the key and falls
        # through to the cold path.
        source_preference = envkey.env_source_preference() or cached["source_preference"]
        # Explicit --no-editable/--no-hammer must beat the cached values:
        # a differing key falls through to the cold rebuild path below.
        editable = opts["editable"] if opts["editable"] is not None else cached["editable"]
        hammer = opts["hammer"] if opts["hammer"] is not None else cached["hammer"]
        # Defensive shape checks: sources must be [kind, rel] string pairs
        # and declared_meta must mirror envkey.declared_metadata_spec's
        # {"paths": [...], "globs": [...]} (a malformed or old-schema marker
        # must fall through to the cold path, never crash the hot path).
        sources = cached["sources"]
        declared_meta = cached["declared_meta"]
        sources_ok = all(
            isinstance(s, list) and len(s) == 2 and all(isinstance(x, str) for x in s)
            for s in sources
        )
        meta_ok = all(
            isinstance(declared_meta.get(k), list)
            and all(isinstance(x, str) for x in declared_meta[k])
            for k in ("paths", "globs")
        )
        cached_extra_source_paths = cached.get("extra_source_paths")
        extras_ok = cached_extra_source_paths is None or (
            isinstance(cached_extra_source_paths, list)
            and all(isinstance(x, str) for x in cached_extra_source_paths)
        )
        if sources_ok and meta_ok and extras_ok:
            cached_filter_source = cached.get("filter_source")
            if not isinstance(cached_filter_source, bool):
                cached_filter_source = True
            if not isinstance(cached_extra_source_paths, list):
                cached_extra_source_paths = []
            key = envkey.compute_key(
                stub,
                editable=editable,
                deps_spec=cached["deps_spec"],
                hammer=hammer,
                source_preference=source_preference,
                interpreter_request=request,
                sources=sources,
                declared_meta=declared_meta,
                filter_source=cached_filter_source,
                extra_source_paths=cached_extra_source_paths,
            )
            if envkey.venv_is_current(stub, key):
                # The cached interpreter is only trustworthy while the
                # effective request it was resolved against is still in
                # effect: resolve_interpreter (passthrough UV_PYTHON=...)
                # rewrites the marker's interpreter fields WITHOUT changing
                # the env key, so a key hit alone does not vouch for it.
                interpreter = marker.get("interpreter")
                if not isinstance(interpreter, str) or marker.get("interpreter_request") != request:
                    interpreter = None
                _exec_in_venv(
                    root, cmd, interpreter=interpreter, store_path=marker["store_path"]
                )

    # Cache miss: full (cold) path. Without explicit flags the sync-time
    # selections are sticky — reuse the marker's deps_spec, editable, hammer,
    # type-guarded again here: a wrong-typed deps_spec would reach
    # driver._deps_line and TypeError there.
    def _typed(k: str, t: type):
        v = cached.get(k) if cached else None
        return v if isinstance(v, t) else None

    if not explicit_source_selection and cached:
        if opts["filter_source"] is None and isinstance(cached.get("filter_source"), bool):
            opts["filter_source"] = cached["filter_source"]
        if not opts["include"] and all(isinstance(x, str) for x in cached.get("extra_source_paths", [])):
            opts["include"] = list(cached.get("extra_source_paths", []))

    project, built_store_path = _load_and_build(
        opts,
        deps_spec=None if explicit_selection else (_typed("deps_spec", str) or None),
        editable=_typed("editable", bool),
        hammer=_typed("hammer", bool),
    )
    marker = envkey.read_marker(project)
    store_path = marker.get("store_path") if marker else None
    if not isinstance(store_path, str) or store_path != built_store_path:
        raise CliError("environment build completed without a matching store path marker")
    _exec_in_venv(
        project.root,
        cmd,
        interpreter=marker.get("interpreter") if marker else None,
        store_path=store_path,
    )
    raise AssertionError("unreachable")  # execvpe does not return


def _run_script(script: Path, args: list[str], opts: dict) -> int:
    """PEP 723 script: build via the inline driver, exec the script.

    Cache marker: <script>.uvloom.json beside <script>.lock (see driver.py).
    _venv_env supplies the same hygiene as project runs: PYTHONPATH dropped,
    UV_NO_SYNC/UV_PYTHON_DOWNLOADS guards so a nested uv inside the script
    cannot clobber a project .venv or fetch an interpreter.
    """
    from . import driver

    hammer = True if opts["hammer"] is None else opts["hammer"]
    store_path = driver.build_script_venv(
        script, hammer=hammer, verbose=opts["verbose"], quiet=opts["quiet"]
    )

    env = _venv_env(store_path)
    python = f"{store_path}/bin/python"
    execvpe([python, str(script), *args], env)
    raise AssertionError("unreachable")


# ---------------------------------------------------------------------------
# venv


def cmd_venv(argv: list[str]) -> int:
    opts = _parse_env_flags(argv, command="venv")
    _, store_path = _load_and_build(opts)
    print(store_path)
    return 0


# ---------------------------------------------------------------------------
# check


@contextlib.contextmanager
def _check_lock(project):
    """Advisory flock for `uvloom check` renders/builds (cold path).

    Separate from envkey.build_lock so a long pytest derivation build never
    serializes concurrent syncs/runs; it only guards check.driver.nix against
    concurrent checks (same pattern as driver._script_build_lock).
    """
    path = project.root / ".venv-uvloom-check.lock"
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_CLOEXEC, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


# Check's own flag surface: --paths feeds both pytest and the source filter;
# --include only widens the filtered source (see cmd_check below).
_CHECK_FLAG_SPEC = {
    "--group": _append("groups", "--group", _validate_name),
    "--paths": _append("paths", "--paths", _validate_path),
    "--include": _append("include", "--include", _validate_path),
    "--no-filter-source": _set("filter_source", False),
    "--no-hammer": _set("hammer", False),
    "-v": _set("verbose", True),
    "--verbose": _set("verbose", True),
}


def cmd_check(argv: list[str]) -> int:
    opts = {
        "groups": [],
        "paths": [],
        "include": [],
        "pytest_flags": [],
        "verbose": False,
        "hammer": True,
        "filter_source": True,
    }
    _parse_flags(
        argv, command="check", spec=_CHECK_FLAG_SPEC, opts=opts, dashdash="pytest_flags"
    )
    groups = opts["groups"]
    paths = opts["paths"]
    pytest_flags = opts["pytest_flags"]
    verbose = opts["verbose"]
    hammer = opts["hammer"]

    from . import driver, nixrun
    from .config import load_project

    project = load_project()
    _ensure_lock(project)

    # The check driver gets its own file (never clobbers a concurrently
    # evaluating venv driver) and whitelists the test paths into the filtered
    # source — the pytest derivation runs from the store copy. A CHECK-specific
    # lock (never envkey.build_lock) keeps concurrent checks with different
    # flags from clobbering check.driver.nix mid-eval without serializing
    # syncs/runs behind a long pytest build (mirrors driver._script_build_lock).
    check_paths = tuple(paths) if paths else ("tests",)
    # --include widens the filtered source only: on [tool.uv] package = false
    # projects the store copy carries top-level *.py and src/ but drops other
    # directories (lib/filter-source.nix), and abusing --paths to whitelist
    # them would also make pytest collect them.
    extra_source_paths = check_paths + tuple(opts["include"])
    if not opts["filter_source"] and opts["include"]:
        raise CliError("--include cannot be used with --no-filter-source")
    with _check_lock(project):
        driver_path = driver.render_driver(
            project,
            hammer=hammer,
            check_groups=tuple(groups),
            check_paths=check_paths,
            check_flags=tuple(pytest_flags),
            filter_source=opts["filter_source"],
            extra_source_paths=extra_source_paths,
            filename="check.driver.nix",
        )
        try:
            nixrun.nix_build(
                [str(driver_path), "-A", "check"],
                out_link=None,
                verbose=verbose,
                cwd=project.root,
            )
        except nixrun.NixBuildError as err:
            return _report_check_failure(err, project)
    print("uvloom: checks passed", file=sys.stderr)
    return 0


def _report_check_failure(err, project) -> int:
    """Req 13: when the pytest derivation itself fails, print only its log."""
    from . import failures, nixrun

    # The check derivation is named "<package>-pytest" (lib/scope.nix
    # mkPytestCheck); its venv is "<package>-pytest-env" and dependency
    # packages carry versioned names, so only an exact ".drv" suffix match
    # identifies the test run itself. Use the shared Nix-format parser so this
    # path cannot drift from general failure translation.
    pytest_drvs = [
        drv
        for drv in failures._concrete_failing_drvs(err.stderr)
        if drv.endswith("-pytest.drv")
    ]
    if pytest_drvs:
        log = nixrun.nix_log(pytest_drvs[-1], cwd=project.root)
        if log:
            tail = log.splitlines()[-200:]
        else:
            # Fall back to whatever Nix already echoed, with the same bound.
            tail = err.stderr.strip().splitlines()[-200:]
        print("\n".join(tail), file=sys.stderr)
        return 1
    # A dependency (not the test run) failed — translate like any build.
    failures.raise_translated(err, project)
