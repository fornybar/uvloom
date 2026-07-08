"""driver.nix rendering + environment builds.

The project driver is rendered from ``data/driver.nix.tmpl`` into
``<root>/.uvloom/driver.nix`` (with ``.uvloom/.gitignore`` = ``*``).
Substitution placeholders (``@name@``):

  @pins@             path expr of the installed data/pins.nix
  @uvloomLib@        path expr of the uvloom Nix library (nixrun.uvloom_lib_path())
  @projectRoot@      path expr of the project root
  @interpreter@      nix expr: ``pkgs.python312`` or ``null`` (library infers
                     from requires-python via lib/interpreter.nix)
  @sourcePreference@ nix string: "wheel" | "sdist"
  @dependencies@     whole ``dependencies = <expr>;`` line, or "" (empty =
                     library default, i.e. workspace.deps.default):
                       deps_spec "workspace-default" -> ""
                       deps_spec "all-groups"        -> project.workspace.deps.all
                       deps_spec "groups=..;extras=.." -> { "<projname>" = [ "dev" .. ]; }
  @editable@         ``true`` | ``false``
  @hammerOverlay@    ``[ ]`` or ``[ (pins.hammer.overrides pkgs) ]``
                     (shape confirmed with the Pins agent: pins.hammer is the
                     uv2nix_hammer_overrides flake outputs attrset)
  @userOverlay@      ``[ ]`` or ``[ (import (<root> + "/uv.nix")) ]``
  @editableOverlay@  ``[ ]``, or (editable renders only) an overlay list
                     element injecting the ``editables`` build requirement
                     into every local workspace member — hatchling needs it
                     to build editable wheels and the CLI must work with
                     zero user changes
  @venvName@         nix string "<projname>-env"
  @checkGroups@      whole ``groups = [ .. ];`` line or "" (library default: [ "test" ])
  @checkPaths@       nix list of strings, default [ "tests" ]
  @checkFlags@       nix list of strings, default [ ]
  @extraSourcePaths@ nix list of strings, default [ ] — extra root-relative
                     paths whitelisted into the filtered source (check
                     renders pass the pytest paths)

The pyproject-build-systems overlay is applied by the library internally
(lib/python-set.nix); the driver only layers hammer + user overlays, in that
order, so the user's uv.nix wins.

deps_spec grammar (canonical strings, also stored in the marker's cached
config and hashed into the environment key):
  "workspace-default"                      uv sync defaults (dev group)
  "all-groups"                             --all-groups
  "groups=g1,g2;extras=e1,e2"              --group/--extra selection (sorted),
                                           applied to the root project name on
                                           top of the default "dev" group
"""

import contextlib
import fcntl
import json
import os
import re
import shutil
import tempfile
import tomllib
from dataclasses import dataclass
from pathlib import Path

from . import envkey, nixrun
from .errors import CliError

# ---------------------------------------------------------------------------
# Nix literal rendering


def _nix_str(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"').replace("${", "\\${") + '"'


def _nix_path(p: Path | str) -> str:
    # Path literals cannot contain spaces; build the path from a string.
    p = os.path.abspath(str(p))
    return f"(/. + {_nix_str(p)})"


def _nix_str_list(items) -> str:
    if not items:
        return "[ ]"
    return "[ " + " ".join(_nix_str(i) for i in items) + " ]"


def _render(template: str, subs: dict[str, str]) -> str:
    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        try:
            return subs[name]
        except KeyError:
            raise RuntimeError(f"unsubstituted driver placeholder @{name}@") from None

    text = re.sub(r"@([A-Za-z]\w*)@", replace, template)
    # Empty placeholder values (e.g. omitted dependencies) leave an indented
    # blank line behind; drop whitespace-only lines.
    return "".join(
        line for line in text.splitlines(keepends=True) if line.strip() or line == "\n"
    )


# ---------------------------------------------------------------------------
# Project metadata (cold path only — parses toml)


def project_name(project) -> str:
    import tomllib

    try:
        with open(project.pyproject_path, "rb") as f:
            data = tomllib.load(f)
        name = data.get("project", {}).get("name")
    except (OSError, tomllib.TOMLDecodeError):
        name = None
    if not name:
        name = project.root.name  # virtual root without [project].name
    return re.sub(r"[^A-Za-z0-9+._?=-]", "-", name)


def _root_lock_package(project) -> dict | None:
    """Canonical root package name from uv.lock, falling back before lock exists.

    uv normalizes package names in its lock.  Dependency maps are keyed by
    that normalized name, not necessarily the spelling in pyproject.toml.
    """
    import tomllib

    try:
        with open(project.lock_path, "rb") as f:
            packages = tomllib.load(f).get("package", [])
    except (OSError, tomllib.TOMLDecodeError):
        packages = []
    for package in packages:
        if not isinstance(package, dict):
            continue
        source = package.get("source")
        if not isinstance(source, dict):
            continue
        if any(source.get(kind) == "." for kind in ("editable", "directory", "virtual")):
            name = package.get("name")
            if isinstance(name, str) and name:
                return package
    return None


def _root_lock_package_name(project) -> str:
    package = _root_lock_package(project)
    name = package.get("name") if package else None
    return name if isinstance(name, str) and name else project_name(project)


def _deps_line(project, deps_spec: str) -> str:
    root_package = _root_lock_package(project) or {}
    declared_groups = root_package.get("dev-dependencies", {})
    has_dev_group = isinstance(declared_groups, dict) and "dev" in declared_groups
    # uv sync enables root project's configured dev group by default. Keep it
    # explicit in every CLI driver, including --no-editable: library defaults
    # only add dev for editable venvs. Projects without dev retain workspace
    # defaults unchanged.
    root = _nix_str(_root_lock_package_name(project))
    default_with_dev = (
        "project.workspace.deps.default // { "
        f"{root} = lib.unique ((project.workspace.deps.default.{root} or [ ]) ++ [ \"dev\" ]); "
        "};"
    )
    if deps_spec == "workspace-default":
        return f"dependencies = {default_with_dev}" if has_dev_group else ""

    def all_groups_expr() -> str:
        # `all` also enables optional extras. uv's --all-groups does not.
        return "lib.zipAttrsWith (_: groups: lib.unique (lib.concatLists groups)) [ project.workspace.deps.default project.workspace.deps.groups ]"

    def extend_root_expr(base: str, selection: list[str]) -> str:
        if not selection:
            return f"{base};"
        names = " ".join(_nix_str(n) for n in selection)
        attr_base = base if base == "project.workspace.deps.default" else f"({base})"
        return (
            f"{base} // {{ "
            f"{root} = lib.unique (({attr_base}.{root} or [ ]) ++ [ {names} ]); "
            "};"
        )

    if deps_spec == "all-groups":
        return f"dependencies = {all_groups_expr()};"
    m_all = re.fullmatch(r"all-groups;extras=([^;]*)", deps_spec)
    if m_all is not None:
        extras = [e for e in m_all.group(1).split(",") if e]
        return f"dependencies = {extend_root_expr(all_groups_expr(), extras)}"

    m = re.fullmatch(r"(?:default=([^;]*);)?groups=([^;]*);extras=([^;]*)", deps_spec)
    if m is None:
        raise CliError(f"internal: malformed deps_spec '{deps_spec}'")
    defaults_raw = m.group(1)
    defaults = [g for g in (defaults_raw or "").split(",") if g]
    groups = [g for g in m.group(2).split(",") if g]
    extras = [e for e in m.group(3).split(",") if e]
    overlap = (set(defaults) | set(groups)) & set(extras)
    if overlap:
        names = ", ".join(sorted(overlap))
        raise CliError(
            f"cannot select {names} as both --group and --extra: uvloom cannot represent same-name group/extra selectors"
        )
    declared_extras = root_package.get("optional-dependencies", {})
    declared_groups = set(declared_groups) if isinstance(declared_groups, dict) else set()
    declared_extras = set(declared_extras) if isinstance(declared_extras, dict) else set()
    ambiguous = (set(defaults) | set(groups) | set(extras)) & declared_groups & declared_extras
    if ambiguous:
        names = ", ".join(sorted(ambiguous))
        raise CliError(
            f"cannot select {names}: root package defines it as both dependency group and extra, which uvloom cannot represent separately"
        )
    if defaults_raw == "all":
        return f"dependencies = {extend_root_expr(all_groups_expr(), extras)}"
    selection: list[str] = []
    legacy_default = ["dev"] if defaults_raw is None and has_dev_group else []
    for name in legacy_default + defaults + groups + extras:
        if name not in selection:
            selection.append(name)
    # Keep dependencies selected by the workspace default (including other
    # workspace packages) and only extend the canonical locked root package.
    return f"dependencies = {extend_root_expr('project.workspace.deps.default', selection)}"


# ---------------------------------------------------------------------------
# Rendering


def _uvloom_dir(root: Path) -> Path:
    d = root / ".uvloom"
    d.mkdir(exist_ok=True)
    gitignore = d / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text("*\n")
    return d


def render_driver(
    project,
    *,
    editable: bool | None = None,
    deps_spec: str = "workspace-default",
    hammer: bool = True,
    source_preference: str | None = None,
    check_groups: tuple[str, ...] = (),
    check_paths: tuple[str, ...] = ("tests",),
    check_flags: tuple[str, ...] = (),
    filter_source: bool = True,
    extra_source_paths: tuple[str, ...] = (),
    filename: str = "driver.nix",
) -> Path:
    """Render a driver into <root>/.uvloom/<filename>; returns its path.

    ``None`` flag values fall back to project config / defaults.
    ``filename`` isolates concurrent renders: the venv/interpreter driver
    (driver.nix) and the check driver (check.driver.nix) never clobber each
    other while a nix-build is still evaluating one of them.
    ``extra_source_paths`` widens the library's filtered source (check
    drivers pass the pytest paths so the store copy carries the tests).
    """
    from . import interpreter as interp
    from .config import python_version_request, source_preference as derive_preference

    cfg = project.config
    if editable is None:
        editable = True
    if source_preference is None:
        source_preference = derive_preference(cfg)

    attr = interp.interpreter_attr(python_version_request(project))
    root_expr = _nix_path(project.root)

    subs = {
        "pins": _nix_path(nixrun.data_path("pins.nix")),
        "uvloomLib": _nix_path(nixrun.uvloom_lib_path()),
        "projectRoot": root_expr,
        "interpreter": f"pkgs.{attr}" if attr else "null",
        "sourcePreference": _nix_str(source_preference),
        "dependencies": _deps_line(project, deps_spec),
        "editable": "true" if editable else "false",
        "hammerOverlay": "[ (pins.hammer.overrides pkgs) ]" if hammer else "[ ]",
        "userOverlay": (
            f'[ (import ({root_expr} + "/uv.nix")) ]'
            if project.overlay_path.exists()
            else "[ ]"
        ),
        "venvName": _nix_str(f"{project_name(project)}-env"),
        "checkGroups": (f"groups = {_nix_str_list(check_groups)};" if check_groups else ""),
        "checkPaths": _nix_str_list(check_paths),
        "checkFlags": _nix_str_list(check_flags),
        "filterSource": "true" if filter_source else "false",
        "extraSourcePaths": _nix_str_list(extra_source_paths),
    }
    text = _render(nixrun.data_path("driver.nix.tmpl").read_text(), subs)

    driver_path = _uvloom_dir(project.root) / filename
    driver_path.write_text(text)
    return driver_path


# ---------------------------------------------------------------------------
# Foreign .venv guard


def ensure_not_foreign(project, *, force: bool = False) -> None:
    if not envkey.venv_is_foreign(project):
        return
    if not force:
        raise CliError(
            ".venv exists and is not managed by uvloom — remove it or run 'uvloom sync --force'"
        )
    import shutil

    venv = project.root / ".venv"
    if venv.is_symlink() or not venv.is_dir():
        venv.unlink()
    else:
        shutil.rmtree(venv)


# ---------------------------------------------------------------------------
# Builds


def build_venv(
    project,
    *,
    editable: bool,
    deps_spec: str,
    hammer: bool,
    source_preference: str,
    filter_source: bool = True,
    extra_source_paths: tuple[str, ...] = (),
    verbose: bool = False,
    force: bool = False,
) -> str:
    """Build the venv (GC-rooted at <root>/.venv), write the marker; returns store path.

    ``force`` skips the under-lock marker-current early return so the build
    genuinely reruns even when the key matches.
    """

    with envkey.build_lock(project):
        sources = envkey.local_sources(project)
        # Cached verbatim in the marker so the hot path replays it into
        # compute_key toml-free; compute_key re-expands the globs itself.
        declared_meta = envkey.declared_metadata_spec(project)
        key = envkey.compute_key(
            project,
            editable=editable,
            deps_spec=deps_spec,
            hammer=hammer,
            source_preference=source_preference,
            sources=sources,
            declared_meta=declared_meta,
            filter_source=filter_source,
            extra_source_paths=extra_source_paths,
        )
        # Re-check under the lock: a racing build may have done the work.
        # --force bypasses it: the user asked for a real rebuild.
        if not force and envkey.venv_is_current(project, key):
            marker = envkey.read_marker(project)
            assert marker is not None
            return marker["store_path"]

        driver_path = render_driver(
            project,
            editable=editable,
            deps_spec=deps_spec,
            hammer=hammer,
            source_preference=source_preference,
            filter_source=filter_source,
            extra_source_paths=extra_source_paths,
        )
        try:
            store_path = nixrun.nix_build(
                [str(driver_path), "-A", "venv"],
                out_link=str(project.root / ".venv"),
                verbose=verbose,
                cwd=project.root,
            )
        except nixrun.NixBuildError as err:
            from . import failures  # lazy: only on failure

            failures.raise_translated(err, project)

        current_request = envkey.effective_python_request(
            project.root, getattr(project, "discovery_start", None)
        )
        current_requires = envkey.requires_python(project)
        # `driver_path` is exact interpreter-resolution input for this build;
        # persist its fingerprint so a following passthrough can reuse a
        # matching resolved interpreter without a second Nix eval.
        from .interpreter import _cache_fingerprint

        interpreter_fingerprint = _cache_fingerprint(driver_path)
        previous = envkey.read_marker(project) or {}
        # Carry the cached interpreter forward only while BOTH inputs it was
        # resolved against — the effective request (UV_PYTHON, else
        # .python-version) and [project].requires-python (which drives
        # inference when the request is None) — are still in effect;
        # otherwise drop it so the next resolve_interpreter call
        # re-resolves. The requires_python field must survive the rewrite:
        # resolve_interpreter treats its absence as a cache miss.
        interpreter_current = (
            previous.get("interpreter_request") == current_request
            and previous.get("interpreter_requires_python") == current_requires
        )
        envkey.write_marker(
            project,
            {
                "key": key,
                "interpreter": previous.get("interpreter") if interpreter_current else None,
                "interpreter_fingerprint": interpreter_fingerprint if interpreter_current else None,
                "interpreter_request": current_request if interpreter_current else None,
                "interpreter_requires_python": current_requires if interpreter_current else None,
                "cli_version": _cli_version(),
                "store_path": store_path,
                "config": {
                    "editable": editable,
                    "hammer": hammer,
                    "source_preference": source_preference,
                    "deps_spec": deps_spec,
                    "sources": sources,
                    "declared_meta": declared_meta,
                    "filter_source": filter_source,
                    "extra_source_paths": list(extra_source_paths),
                },
            },
        )
        return store_path


def _cli_version() -> str:
    from . import __version__

    return __version__


# ---------------------------------------------------------------------------
# PEP 723 inline scripts
#
# Scripts get a separate, smaller driver rendered from the template below into
# <scriptdir>/.uvloom/<stem>.driver.nix, a GC root at
# <scriptdir>/.uvloom/<stem>.venv, and a cache marker at <script>.uvloom.json
# (beside <script>.lock): {"key", "store_path", "cli_version"}. The key is a
# sha256 of the script bytes, lock bytes, pins.json bytes, CLI version, the
# hammer flag (it changes the rendered overlays), the inline template, and
# the resolved uvloom Nix library (see _script_key). Render, build, and
# marker write run under an advisory flock at <scriptdir>/.uvloom/<stem>.lock
# so concurrent runs with different flags never interleave and record the
# wrong store path under the wrong key.

_INLINE_TEMPLATE = """\
# Generated by uvloom — do not edit; regenerated on every run.
let
  pins = import @pins@;
  pkgs = import pins.nixpkgs { };
  inherit (pkgs) lib;

  uvloomLib = import @uvloomLib@ {
    inherit lib;
    inherit (pins) uv2nix pyproject-nix pyproject-build-systems;
  };

  script = uvloomLib.inline.load {
    path = @scriptPath@;
    lockPath = @lockPath@;
  };

  scope = script.forPython {
    inherit pkgs;
    overlays = @hammerOverlay@;
  };
in
{
  venv = scope.venv { };
  interpreter = pkgs.writeText "uvloom-interpreter-path" (lib.getExe scope.interpreter);
}
"""


def script_marker_path(script: Path) -> Path:
    return script.with_name(script.name + ".uvloom.json")


def _script_stem(script: Path) -> str:
    """Sidecar stem: sanitized stem + 8 hex of the FULL filename's sha256.

    The digest disambiguates scripts whose stems collide (foo.py vs foo.sh)
    so they never share a lock, driver, or out-link.
    """
    import hashlib

    digest = hashlib.sha256(script.name.encode()).hexdigest()[:8]
    return f"{re.sub(r'[^A-Za-z0-9._-]', '-', script.stem)}-{digest}"


def _script_projection_path(script: Path) -> Path:
    """Private uv2nix-compatible lock projection; never user script.lock."""
    return _uvloom_dir(script.parent) / f"{_script_stem(script)}.uv2nix.lock"


_SCRIPT_BUILD_MAX_ATTEMPTS = 3
_SCRIPT_LOCAL_SOURCE_EXCLUDED_DIRS = frozenset({".git", ".hg", ".svn", ".venv", ".uvloom", "__pycache__", "node_modules"})


@dataclass(frozen=True)
class ScriptLocalSourceSnapshot:
    package_index: int
    key: str
    lock_value: str
    live_path: Path
    snapshot_path: Path
    manifest: tuple[tuple[str, int, bytes], ...]


@dataclass(frozen=True)
class ScriptSnapshot:
    live_script: Path
    live_lock: Path
    script_parent: Path
    script_bytes: bytes
    lock_bytes: bytes
    key: str
    attempt_dir: Path
    script_path: Path
    projected_lock_path: Path
    local_sources: tuple[ScriptLocalSourceSnapshot, ...]


def _project_script_lock_text(
    lock_text: str, *, lock_name: str, source_base: Path, output_base: Path,
    source_overrides: dict[tuple[int, str], Path] | None = None,
) -> str:
    """Project script-lock local sources for an output directory.

    uv records local PEP 723 sources as absolute paths, while uv2nix resolves
    lock source paths relative to ``workspaceRoot``. Keep uv's lock untouched
    and rewrite ``source.path``, ``source.directory``, and ``source.editable``
    values to lexical paths relative to the snapshot script
    parent. Parsing before and after replacement proves projection changed no
    other TOML meaning; any unexpected lock syntax fails before private output
    is replaced.
    """
    import copy
    import tomllib

    try:
        parsed = tomllib.loads(lock_text)
    except tomllib.TOMLDecodeError as exc:
        raise CliError(f"cannot read script lock '{lock_name}': {exc}") from exc

    packages = parsed.get("package", [])
    if not isinstance(packages, list):
        raise CliError(f"script lock '{lock_name}' has an invalid package array")
    expected = copy.deepcopy(parsed)
    expected_packages = expected.get("package", [])
    replacements: list[dict[str, str]] = []
    for package in expected_packages:
        if not isinstance(package, dict):
            raise CliError(f"script lock '{lock_name}' has a non-table package entry")
        source = package.get("source")
        wanted: dict[str, str] = {}
        if isinstance(source, dict):
            for key in ("path", "directory", "editable"):
                value = source.get(key)
                if isinstance(value, str):
                    # relpath is deliberately lexical: resolving a source
                    # symlink changes user lock semantics.
                    target = (source_overrides or {}).get((len(replacements), key))
                    if target is None:
                        target = Path(value) if os.path.isabs(value) else source_base / value
                    relative = os.path.relpath(target, start=output_base)
                    source[key] = relative
                    wanted[key] = value
        replacements.append(wanted)

    headers = list(re.finditer(r"(?m)^\[\[package\]\][ \t]*(?:#.*)?$", lock_text))
    if len(headers) != len(packages):
        raise CliError(f"cannot safely project script lock '{lock_name}': package layout changed")

    source_line = re.compile(
        r"(?ms)^(?P<indent>[ \t]*)source[ \t]*=[ \t]*\{(?P<body>.*?)\}[ \t]*(?:#.*)?$"
    )
    string_value = re.compile(
        r'(?P<key>path|directory|editable)(?P<equals>[ \t]*=[ \t]*)(?P<value>"(?:[^"\\]|\\.)*")'
    )
    projected_blocks: list[str] = [lock_text[: headers[0].start()]] if headers else [lock_text]
    for index, header in enumerate(headers):
        start = header.start()
        end = headers[index + 1].start() if index + 1 < len(headers) else len(lock_text)
        block = lock_text[start:end]
        wanted = replacements[index]
        if not wanted:
            projected_blocks.append(block)
            continue
        matches = list(source_line.finditer(block))
        if len(matches) != 1:
            raise CliError(
                f"cannot safely project script lock '{lock_name}': package {index + 1} source is not a single inline table"
            )
        seen: dict[str, int] = {key: 0 for key in wanted}

        def replace_value(match: re.Match[str]) -> str:
            key = match.group("key")
            if key not in wanted:
                return match.group(0)
            try:
                actual = tomllib.loads(f"value = {match.group('value')}")["value"]
            except tomllib.TOMLDecodeError as exc:
                raise CliError(f"cannot safely project script lock '{lock_name}': invalid source string") from exc
            if actual != wanted[key]:
                return match.group(0)
            seen[key] += 1
            return f"{key}{match.group('equals')}{json.dumps(expected_packages[index]['source'][key], ensure_ascii=False)}"

        source_match = matches[0]
        rewritten_body = string_value.sub(replace_value, source_match.group("body"))
        if any(count != 1 for count in seen.values()):
            raise CliError(
                f"cannot safely project script lock '{lock_name}': source paths do not match parsed lock"
            )
        projected_blocks.append(
            block[: source_match.start("body")] + rewritten_body + block[source_match.end("body") :]
        )

    projected = "".join(projected_blocks)
    try:
        if tomllib.loads(projected) != expected:
            raise CliError(f"cannot safely project script lock '{lock_name}': projection validation failed")
    except tomllib.TOMLDecodeError as exc:
        raise CliError(f"cannot safely project script lock '{lock_name}': projection is invalid TOML") from exc
    return projected


def _project_script_lock(script: Path) -> Path:
    """Atomically project local sources into a private script lock."""
    script = script.resolve()
    lock = script.with_name(script.name + ".lock")
    destination = _script_projection_path(script)
    try:
        original = lock.read_text()
    except OSError as exc:
        raise CliError(f"cannot read script lock '{lock}': {exc}") from exc
    projected = _project_script_lock_text(
        original, lock_name=str(lock), source_base=script.parent, output_base=script.parent
    )

    # Same-directory unique temp: concurrent script locks from old CLI
    # processes, manual cleanup, or a second script can never clobber it.
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w") as f:
            f.write(projected)
        os.replace(temporary, destination)
    except OSError as exc:
        with contextlib.suppress(OSError):
            temporary.unlink()
        raise CliError(f"cannot write private script lock '{destination}': {exc}") from exc
    return destination


@contextlib.contextmanager
def _script_build_lock(script: Path):
    """Advisory flock held while (re)building a script venv (see envkey.build_lock)."""
    path = _uvloom_dir(script.parent) / f"{_script_stem(script)}.lock"
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_CLOEXEC, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _script_out_link(script: Path) -> Path:
    """GC-root symlink for a script venv: <scriptdir>/.uvloom/<stem>.venv."""
    return _uvloom_dir(script.parent) / f"{_script_stem(script)}.venv"


def _script_marker_hit(script: Path, marker_file: Path, key: str) -> str | None:
    """Store path from a valid, current script marker, else None.

    Mirrors envkey.venv_is_current's discipline: the store path must not
    only exist, the out-link GC root must still point at it — an unrooted
    path (out-link deleted or retargeted) can be GC'd mid-run, so a hit
    without the root would exec from a doomed store path.
    """
    try:
        marker = json.loads(marker_file.read_text())
    except (OSError, ValueError):
        return None
    if not (
        isinstance(marker, dict)
        and isinstance(marker.get("store_path"), str)
        and marker.get("key") == key
        and os.path.exists(marker["store_path"])
    ):
        return None
    out_link = _script_out_link(script)
    try:
        if os.readlink(out_link) != marker["store_path"]:
            return None
    except OSError:  # missing, or not a symlink
        return None
    return marker["store_path"]


def _script_local_source_entries(script: Path, lock_bytes: bytes) -> list[tuple[int, str, str, Path]]:
    try:
        data = tomllib.loads(lock_bytes.decode())
    except (UnicodeDecodeError, tomllib.TOMLDecodeError):
        return []
    entries: list[tuple[int, str, str, Path]] = []
    for index, pkg in enumerate(data.get("package", [])):
        if not isinstance(pkg, dict):
            continue
        source = pkg.get("source", {})
        if not isinstance(source, dict):
            continue
        for key in ("directory", "editable", "path"):
            value = source.get(key)
            if isinstance(value, str):
                live = Path(value) if os.path.isabs(value) else script.parent / value
                entries.append((index, key, value, Path(os.path.abspath(live))))
    return entries


def _script_local_source_manifest(path: Path) -> tuple[tuple[str, int, bytes], ...]:
    import hashlib

    def one(file: Path, rel: str) -> tuple[str, int, bytes]:
        data = file.read_bytes()
        return (rel, len(data), hashlib.sha256(data).digest())

    if path.is_symlink():
        raise CliError(f"local script source contains symlink '{path}'; immutable script snapshots do not support symlinks")
    if path.is_file():
        return (one(path, ""),)
    if not path.is_dir():
        raise CliError(f"local script source '{path}' does not exist")
    rows: list[tuple[str, int, bytes]] = []
    for dirpath, dirnames, filenames in os.walk(path):
        current = Path(dirpath)
        rel_dir = os.path.relpath(current, path)
        dirnames[:] = sorted(d for d in dirnames if d not in _SCRIPT_LOCAL_SOURCE_EXCLUDED_DIRS)
        for dirname in dirnames:
            child = current / dirname
            if child.is_symlink():
                rel = os.path.normpath(os.path.join(rel_dir, dirname)) if rel_dir != "." else dirname
                raise CliError(f"local script source contains symlink '{rel}'; immutable script snapshots do not support symlinks")
        for name in sorted(filenames):
            if name.endswith(".pyc"):
                continue
            file = current / name
            rel = os.path.normpath(os.path.join(rel_dir, name)) if rel_dir != "." else name
            if file.is_symlink():
                raise CliError(f"local script source contains symlink '{rel}'; immutable script snapshots do not support symlinks")
            rows.append(one(file, rel))
    return tuple(rows)


def _copy_script_local_source(src: Path, dst: Path) -> tuple[tuple[str, int, bytes], ...]:
    if src.is_symlink():
        raise CliError(f"local script source contains symlink '{src}'; immutable script snapshots do not support symlinks")
    if src.is_file():
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
        dst.chmod(dst.stat().st_mode | 0o444)
        return _script_local_source_manifest(dst)
    if not src.is_dir():
        raise CliError(f"local script source '{src}' does not exist")
    for dirpath, dirnames, filenames in os.walk(src):
        current = Path(dirpath)
        rel_dir = os.path.relpath(current, src)
        out_dir = dst if rel_dir == "." else dst / rel_dir
        out_dir.mkdir(parents=True, exist_ok=True)
        dirnames[:] = sorted(d for d in dirnames if d not in _SCRIPT_LOCAL_SOURCE_EXCLUDED_DIRS)
        for dirname in dirnames:
            child = current / dirname
            if child.is_symlink():
                rel = os.path.normpath(os.path.join(rel_dir, dirname)) if rel_dir != "." else dirname
                raise CliError(f"local script source contains symlink '{rel}'; immutable script snapshots do not support symlinks")
        for name in sorted(filenames):
            if name.endswith(".pyc"):
                continue
            file = current / name
            rel = os.path.normpath(os.path.join(rel_dir, name)) if rel_dir != "." else name
            if file.is_symlink():
                raise CliError(f"local script source contains symlink '{rel}'; immutable script snapshots do not support symlinks")
            shutil.copyfile(file, out_dir / name)
    return _script_local_source_manifest(dst)


def _script_local_sources_unchanged(sources: tuple[ScriptLocalSourceSnapshot, ...]) -> bool:
    try:
        return all(_script_local_source_manifest(src.live_path) == src.manifest for src in sources)
    except (OSError, CliError):
        return False


def _script_local_sources_from_lock_bytes(script: Path, lock_bytes: bytes) -> list[Path]:
    """Local sources from <script>.lock: package trees AND path archives.

    Script locks record no content hash for either, so both kinds must
    feed the script key (same parity rule as envkey.local_sources for
    project locks). Resolved absolute — script deps are relative to the
    script's directory, not a project root, so there is no inside-root
    invariant to enforce here.
    """
    paths: list[Path] = []
    for _, _, _, path in _script_local_source_entries(script, lock_bytes):
        if path.exists() and path not in paths:
            paths.append(path)
    return sorted(paths)


def _script_local_sources(script: Path) -> list[Path]:
    lock = script.with_name(script.name + ".lock")
    try:
        lock_bytes = lock.read_bytes()
    except OSError:
        return []
    return _script_local_sources_from_lock_bytes(script, lock_bytes)


def _hash_bytes(h, label: str, data: bytes) -> None:
    h.update(f"\0{label}:{len(data)}\0".encode())
    h.update(data)


def _script_key(script: Path, *, hammer: bool) -> str:
    try:
        script_bytes = script.read_bytes()
    except OSError:
        script_bytes = None
    try:
        lock_bytes = script.with_name(script.name + ".lock").read_bytes()
    except OSError:
        lock_bytes = None
    if script_bytes is None or lock_bytes is None:
        import hashlib

        h = hashlib.sha256()
        _script_key_common_prefix(h, script, hammer=hammer)
        if script_bytes is None:
            h.update(b"\0script:absent\0")
        else:
            _hash_bytes(h, "script", script_bytes)
        if lock_bytes is None:
            h.update(b"\0lock:absent\0")
        else:
            _hash_bytes(h, "lock", lock_bytes)
        envkey._hash_file(h, "pins", nixrun.data_path("pins.json"))
        return h.hexdigest()
    return _script_key_from_snapshot(script, script_bytes, lock_bytes, hammer=hammer)


def _script_key_common_prefix(h, script: Path, *, hammer: bool) -> None:
    # v4: private uv2nix lock projection; bind both the resolved script
    # parent and projection routing so old markers cannot skip it.
    h.update(b"uvloom-script-key-v4")
    h.update(f"\0script-parent:{script.resolve().parent}\0".encode())
    h.update(b"\0script-lock-routing:private-uv2nix-v1\0")
    h.update(f"\0cli:{_cli_version()}\0".encode())
    h.update(f"\0hammer:{int(bool(hammer))}\0".encode())
    h.update(f"\0inline-template:{_INLINE_TEMPLATE}\0".encode())
    envkey._hash_uvloom_lib(h)


def _script_key_from_snapshot(
    script: Path, script_bytes: bytes, lock_bytes: bytes, *, hammer: bool,
    local_sources: tuple[ScriptLocalSourceSnapshot, ...] = ()
) -> str:
    import hashlib

    h = hashlib.sha256()
    _script_key_common_prefix(h, script, hammer=hammer)
    _hash_bytes(h, "script", script_bytes)
    _hash_bytes(h, "lock", lock_bytes)
    envkey._hash_file(h, "pins", nixrun.data_path("pins.json"))
    if local_sources:
        for source in local_sources:
            h.update(f"\0local-src:{source.package_index}:{source.key}:{source.lock_value}\0".encode())
            for rel, size, digest in source.manifest:
                h.update(f"\0{rel}:{size}\0".encode())
                h.update(digest)
    else:
        for pkg_index, key_name, lock_value, path in _script_local_source_entries(script, lock_bytes):
            if not path.exists():
                continue
            h.update(f"\0local-src:{pkg_index}:{key_name}:{lock_value}\0".encode())
            for rel, size, digest in _script_local_source_manifest(path):
                h.update(f"\0{rel}:{size}\0".encode())
                h.update(digest)
    return h.hexdigest()


def render_inline_driver(
    script: Path, *, lock_path: Path | None = None, hammer: bool = True
) -> Path:
    script = script.resolve()
    lock_path = lock_path if lock_path is not None else _script_projection_path(script)
    subs = {
        "pins": _nix_path(nixrun.data_path("pins.nix")),
        "uvloomLib": _nix_path(nixrun.uvloom_lib_path()),
        "scriptPath": _nix_path(script),
        "lockPath": _nix_path(lock_path),
        "hammerOverlay": "[ (pins.hammer.overrides pkgs) ]" if hammer else "[ ]",
    }
    text = _render(_INLINE_TEMPLATE, subs)
    stem = _script_stem(script)
    path = _uvloom_dir(script.parent) / f"{stem}.driver.nix"
    path.write_text(text)
    return path


def _write_attempt_file(path: Path, data: bytes) -> None:
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(temporary, path)
    except OSError:
        with contextlib.suppress(OSError):
            temporary.unlink()
        raise


def _script_snapshot(script: Path, lock: Path, *, hammer: bool, attempt: int) -> ScriptSnapshot:
    try:
        script_bytes = script.read_bytes()
        lock_bytes = lock.read_bytes()
    except OSError as exc:
        raise CliError(f"cannot read script or script lock for '{script.name}': {exc}") from exc
    attempt_dir = (
        _uvloom_dir(script.parent)
        / f"{_script_stem(script)}.attempt-{os.getpid()}-{attempt}"
    )
    if attempt_dir.exists():
        shutil.rmtree(attempt_dir)
    attempt_dir.mkdir(mode=0o755, exist_ok=True)
    script_path = attempt_dir / script.name
    projected_lock_path = attempt_dir / f"{script.name}.uv2nix.lock"
    _write_attempt_file(script_path, script_bytes)
    local_root = attempt_dir / "local-sources"
    source_snapshots: list[ScriptLocalSourceSnapshot] = []
    source_overrides: dict[tuple[int, str], Path] = {}
    for source_number, (pkg_index, key_name, lock_value, live_path) in enumerate(
        _script_local_source_entries(script, lock_bytes)
    ):
        safe_base = re.sub(r"[^A-Za-z0-9._-]", "-", live_path.name or "source")
        if live_path.is_file():
            snapshot_path = local_root / f"{source_number}-{key_name}" / safe_base
        else:
            snapshot_path = local_root / f"{source_number}-{key_name}-{safe_base}"
        manifest = _copy_script_local_source(live_path, snapshot_path)
        source_snapshots.append(
            ScriptLocalSourceSnapshot(
                package_index=pkg_index,
                key=key_name,
                lock_value=lock_value,
                live_path=live_path,
                snapshot_path=snapshot_path,
                manifest=manifest,
            )
        )
        source_overrides[(pkg_index, key_name)] = snapshot_path
    local_sources = tuple(source_snapshots)
    key = _script_key_from_snapshot(script, script_bytes, lock_bytes, hammer=hammer, local_sources=local_sources)
    try:
        lock_text = lock_bytes.decode()
    except UnicodeDecodeError as exc:
        raise CliError(f"cannot read script lock '{lock}': {exc}") from exc
    projected = _project_script_lock_text(
        lock_text, lock_name=str(lock), source_base=script.parent, output_base=attempt_dir,
        source_overrides=source_overrides,
    )
    _write_attempt_file(projected_lock_path, projected.encode())
    return ScriptSnapshot(
        live_script=script,
        live_lock=lock,
        script_parent=script.parent,
        script_bytes=script_bytes,
        lock_bytes=lock_bytes,
        key=key,
        attempt_dir=attempt_dir,
        script_path=script_path,
        projected_lock_path=projected_lock_path,
        local_sources=local_sources,
    )


def build_script_venv(
    script: Path, *, hammer: bool = True, verbose: bool = False, quiet: bool = False
) -> str:
    """Build (or reuse) the venv for a PEP 723 script; returns its store path.

    ``quiet`` suppresses the informational lock-bootstrap line, matching
    how -q silences _ensure_lock on the project path.
    """
    import subprocess
    import sys

    script = script.resolve()
    marker_file = script_marker_path(script)
    with _script_build_lock(script):
        # Lock creation, lockfile mutation, cache-key calculation, marker
        # validation, projection, and build are one critical section.  A
        # concurrent uv lock must never leave us building a driver for a
        # different key than marker we just checked.
        lock = script.with_name(script.name + ".lock")
        if not lock.exists():
            uv = nixrun.uv_binary()
            if not quiet:
                print(
                    f"uvloom: no {lock.name} — creating it via 'uv lock --script {script.name}'",
                    file=sys.stderr,
                )
            env = os.environ.copy()
            env["UV_NO_SYNC"] = "1"
            env["UV_PYTHON_DOWNLOADS"] = "never"
            rc = subprocess.run(
                [uv, "lock", "--script", str(script)], cwd=script.parent, env=env
            ).returncode
            if rc < 0:
                raise SystemExit(128 + (-rc))
            if rc != 0 or not lock.exists():
                raise CliError(f"'uv lock --script {script.name}' failed")

        for attempt in range(_SCRIPT_BUILD_MAX_ATTEMPTS):
            snapshot = _script_snapshot(script, lock, hammer=hammer, attempt=attempt)
            cached = _script_marker_hit(script, marker_file, snapshot.key)
            if cached is not None:
                return cached

            driver_path = render_inline_driver(
                snapshot.script_path, lock_path=snapshot.projected_lock_path, hammer=hammer
            )
            out_link = _script_out_link(script)
            try:
                store_path = nixrun.nix_build(
                    [str(driver_path), "-A", "venv"],
                    out_link=str(out_link),
                    verbose=verbose,
                    cwd=script.parent,
                )
            except nixrun.NixBuildError as err:
                from . import failures

                # Deliberately NOT failures.raise_translated: its build-failure
                # branch prescribes a `uv.nix` overlay at the project root, but
                # inline scripts have no project root and _INLINE_TEMPLATE wires
                # no userOverlay — that advice would be unactionable here. Eval
                # errors still translate; builds get a bounded log tail.
                msg = failures.translate_eval_failure(err.stderr)
                if msg is None:
                    tail = "\n".join(err.stderr.splitlines()[-15:])
                    msg = f"building the environment for {script.name} failed:\n{tail}"
                raise CliError(msg) from None

            try:
                live_same = (
                    script.read_bytes() == snapshot.script_bytes
                    and lock.read_bytes() == snapshot.lock_bytes
                    and _script_local_sources_unchanged(snapshot.local_sources)
                )
            except OSError:
                live_same = False
            if not live_same:
                continue

            # Atomic like envkey.write_marker: never leave a torn marker behind.
            tmp = marker_file.with_name(marker_file.name + ".tmp")
            tmp.write_text(
                json.dumps(
                    {"key": snapshot.key, "store_path": store_path, "cli_version": _cli_version()},
                    indent=2,
                )
                + "\n"
            )
            os.replace(tmp, marker_file)
            return store_path

        raise CliError("script, script lock, or local script source changed repeatedly during build; retry when edits/uv lock finish")
