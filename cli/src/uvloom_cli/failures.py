"""Translate Nix build/eval failures into actionable messages.

No raw Nix trace ever reaches a non-``-v`` user: ``translate_build_failure``
turns a failed builder into "package + version + log tail + paste-able fix",
and ``translate_eval_failure`` maps library eval errors to one sentence.

Example translations (input stderr snippet -> output), one per failure class:

1. Missing pkg-config (nativeBuildInputs class)::

      error: builder for '/nix/store/aaaabbbbccccddddeeeeffffgggghhhh-python3.12-pyzmq-26.0.3.drv' failed with exit code 1;
             last 3 log lines:
             > checking for pkg-config...
             > ./configure: line 42: pkg-config: command not found
             > error: Program 'pkg-config' not found

   ->

      build of pyzmq 26.0.3 failed

      last 3 log lines:
        checking for pkg-config...
        ./configure: line 42: pkg-config: command not found
        error: Program 'pkg-config' not found

      detected: 'pkg-config' is missing at build time.
      paste into uv.nix at the project root (create the file if missing):

      final: prev: {
        "pyzmq" = prev."pyzmq".overrideAttrs (old: {
          nativeBuildInputs = (old.nativeBuildInputs or [ ]) ++ [ final.pkgs.pkg-config ];
        });
      }

      full log: nix log /nix/store/aaaabbbbccccddddeeeeffffgggghhhh-python3.12-pyzmq-26.0.3.drv

2. auto-patchelf unsatisfied soname (buildInputs class, via data/sonames.json)::

      error: builder for '/nix/store/aaaabbbbccccddddeeeeffffgggghhhh-python3.12-lxml-5.2.1.drv' failed with exit code 1;
             last 2 log lines:
             > auto-patchelf: 1 dependencies could not be satisfied
             > error: auto-patchelf could not satisfy dependency libxslt.so.1 wanted by /nix/store/...-lxml-5.2.1/lib/etree.so

   ->

      build of lxml 5.2.1 failed

      last 2 log lines:
        auto-patchelf: 1 dependencies could not be satisfied
        error: auto-patchelf could not satisfy dependency libxslt.so.1 wanted by /nix/store/...-lxml-5.2.1/lib/etree.so

      detected: missing shared library libxslt.so.1 (auto-patchelf).
      paste into uv.nix at the project root (create the file if missing):

      final: prev: {
        "lxml" = prev."lxml".overrideAttrs (old: {
          buildInputs = (old.buildInputs or [ ]) ++ [ final.pkgs.libxslt ];
        });
      }

      full log: nix log /nix/store/aaaabbbbccccddddeeeeffffgggghhhh-python3.12-lxml-5.2.1.drv

3. Eval-time failure (library ``fail`` from lib/errors.nix)::

      error: uvloom.project.load: root must contain a pyproject.toml

   -> translate_eval_failure returns:

      project.load: root must contain a pyproject.toml

   and a missing lock file::

      error: getting status of '/nix/store/xxx-source/uv.lock': No such file or directory

   -> "no uv.lock -- run 'uvloom lock' first"
"""

import json
import re
import tomllib
from importlib import resources
from pathlib import Path
from typing import TYPE_CHECKING, NoReturn

if TYPE_CHECKING:
    from .config import Project

# Concrete build failures. Nix < 2.30 used ``builder for ... failed``;
# current Nix uses ``Cannot build ...`` followed by ``Reason: builder failed``.
_FAILED_DRV_START_RE = re.compile(
    r"error: (?:builder for|Cannot build) '(/nix/store/[a-z0-9]+-[^']+\.drv)'"
)
_FAILED_DRV_RE = re.compile(
    r"error: (?:builder for '(/nix/store/[a-z0-9]+-[^']+\.drv)' failed"
    r"|Cannot build '(/nix/store/[a-z0-9]+-[^']+\.drv)'\.\s*\n\s*Reason: builder failed)"
)
# Missing uv.lock: the stat/open error must name the uv.lock path on the same
# line — an unrelated does-not-exist error elsewhere in the trace must not
# match just because uv.lock appears somewhere else.
_MISSING_LOCK_RE = re.compile(
    r"^[^\n]*uv\.lock[^\n]*(?:does not exist|No such file or directory)[^\n]*$"
    r"|^[^\n]*(?:does not exist|No such file or directory)[^\n]*uv\.lock[^\n]*$",
    re.MULTILINE,
)
# Aggregate line: "error: build of '/nix/store/...drv', '/nix/store/...drv' failed"
_BUILD_OF_RE = re.compile(r"error: build of ('(/nix/store/[^']+\.drv)'.*?) failed")
_DRV_PATH_RE = re.compile(r"/nix/store/[a-z0-9]+-[^'\s]+\.drv")
_DIRECT_PKG_CONFIG_RE = re.compile(
    r"^\s*error: pkg-config is required to build (\S+)\s*$",
    re.MULTILINE | re.IGNORECASE,
)

# Failure translation is best-effort and must not turn a corrupt or unexpectedly
# large lock into a second failure.
_MAX_LOCK_BYTES = 16 * 1024 * 1024
_MAX_LOCK_PACKAGES = 100_000

# Log tail embedded in nix stderr: "last N log lines:" followed by "> " lines.
_LOG_LINES_MARKER_RE = re.compile(r"last \d+ log lines?:", re.IGNORECASE)
_LOG_LINE_RE = re.compile(r"^\s*>\s?(.*)$")

# lib/errors.nix: fail = where: message: throw "uvloom.${where}: ${message}";
_UVLOOM_FAIL_RE = re.compile(r"uvloom\.([A-Za-z0-9_.]+): ([^\n]+)")

# pyproject-nix: a selected extra/group name that pyproject.toml does not
# declare. Anchored like the uv.lock eval catch-all below: embedded build-log
# lines are prefixed with "> ", so `^\s*error:` cannot match them and no
# builder-failed guard is needed — this text only ever appears at eval time.
_GROUP_MISMATCH_RE = re.compile(
    r"^\s*error: Extra/group name '([^']+)' does not match either extra or dependency group",
    re.MULTILINE,
)

# Failure classes -> (human description, input list, nixpkgs attr).
_TOOL_CLASSES = [
    (
        re.compile(
            r"pkg-config: (?:command )?not found"
            r"|Program 'pkg-config' not found"
            r"|pkg-config (?:is )?(?:required|not installed)",
            re.IGNORECASE,
        ),
        "'pkg-config' is missing at build time",
        "nativeBuildInputs",
        "pkg-config",
    ),
    (
        re.compile(
            r"cmake: (?:command )?not found"
            r"|CMake must be installed"
            r"|Cannot find CMake"
            r"|Program 'cmake' not found",
            re.IGNORECASE,
        ),
        "'cmake' is missing at build time",
        "nativeBuildInputs",
        "cmake",
    ),
]

# auto-patchelf; message wording has varied across nixpkgs, match both forms.
_AUTOPATCHELF_RE = re.compile(
    r"(?:dependenc(?:y|ies) could not be satisfied:?\s+|could not satisfy dependency\s+)"
    r"(?:\x1b\[[0-9;]*m)?(lib[\w+.-]+?\.so(?:\.[\w.]+)?)"
)


def translate_build_failure(
    stderr: str,
    project: "Project",
    *,
    hammer_path: str | None = None,
    log_tail: int = 30,
) -> str:
    """Turn nix-build stderr for a failed dependency into an actionable message."""
    direct_pkg_config = _DIRECT_PKG_CONFIG_RE.search(stderr)
    if direct_pkg_config:
        package = direct_pkg_config.group(1).rstrip(".")
        fix = _classify(direct_pkg_config.group(0), package)
        if fix:
            version = _locked_package_version(project.lock_path, package)
            title = (
                f"build of {package} {version} failed"
                if version
                else f"build of {package} failed"
            )
            return f"{title}\n\n{fix}"
    drv = _failing_drv(stderr)
    if drv is None:
        # No identifiable builder: this is an eval-time failure. A library
        # `fail` (or another recognized eval error) still translates cleanly;
        # anything else (syntax error in uv.nix, infinite recursion) gets a
        # bounded generic message — the module contract forbids dumping a raw
        # Nix trace on non-verbose users.
        translated = translate_eval_failure(stderr)
        if translated is not None:
            return translated
        return _generic_eval_fallback(stderr)

    package, version = _parse_drv_name(drv)
    log_lines = _log_lines(drv, stderr, log_tail)

    paragraphs: list[str] = []
    title = f"build of {package} {version} failed" if version else f"build of {package} failed"
    paragraphs.append(title)

    if log_lines:
        paragraphs.append(
            f"last {len(log_lines)} log lines:\n"
            + "\n".join("  " + ln for ln in log_lines)
        )

    if hammer_path is not None:
        near_miss = _hammer_near_miss(hammer_path, package, version)
        if near_miss:
            paragraphs.append(near_miss)

    # Classify only the selected derivation's log. If no per-derivation log
    # is available, preserve nix's embedded stderr tail as the fallback source.
    scan_text = "\n".join(log_lines) if log_lines else stderr
    fix = _classify(scan_text, package)
    if fix:
        paragraphs.append(fix)

    paragraphs.append(f"full log: nix log {drv}")
    return "\n\n".join(paragraphs)


def translate_eval_failure(stderr: str) -> str | None:
    """Map eval-time errors to a one-sentence message; None if unrecognized.

    The caller shows a generic message plus a log path when this returns None;
    the raw trace is only ever printed under -v.
    """
    # Missing uv.lock: our library, uv2nix, or Nix itself stat'ing the file.
    # Only when no builder failed — a *package build* whose log mentions
    # uv.lock (e.g. a FileNotFoundError in some setup.py) must fall through
    # to the build translator instead of blaming the project lock.
    if _MISSING_LOCK_RE.search(stderr) and not _concrete_failing_drvs(stderr):
        return "no uv.lock — run 'uvloom lock' first"

    # lib/errors.nix `fail`: throw "uvloom.<where>: <message>". Only when no
    # builder failed — a package build whose log happens to echo an uvloom.*
    # string must fall through to the build translator.
    m = _UVLOOM_FAIL_RE.search(stderr)
    if m and not _concrete_failing_drvs(stderr):
        where, message = m.groups()
        message = message.strip()
        # A trace line quoting the whole throw ('uvloom.x: msg') leaves a
        # dangling closing quote; strip it only when it is unbalanced.
        last = message[-1:]
        if last in ("'", '"') and message.count(last) % 2 == 1:
            message = message[:-1]
        return f"{where}: {message}"

    # pyproject-nix rejects a selected extra/group that pyproject.toml does
    # not declare. `uvloom check` hits this on projects without a `test`
    # group (the library defaults to groups = ["test"], see lib/scope.nix
    # mkPytestCheck) — name the fixes instead of dumping the trace.
    m = _GROUP_MISMATCH_RE.search(stderr)
    if m:
        name = m.group(1)
        return (
            f"dependency group '{name}' is not defined in pyproject.toml; "
            "uvloom check selects group 'test' by default — add "
            "[dependency-groups] test = [...] or pass --group <existing-group>"
        )

    # uv2nix/pyproject-nix eval errors that name the lock file: the lock is
    # present but unusable (corrupt, or written by a newer uv than our pin).
    if re.search(r"^\s*error:.*uv\.lock", stderr, re.MULTILINE):
        return "uv.lock could not be evaluated — re-run 'uvloom lock' (the lock may be corrupt or from a newer uv)"

    return None


def raise_translated(err, project: "Project") -> NoReturn:
    """Shared eval-then-build translation ladder; always raises CliError.

    Every nix-build failure path (venv build, interpreter resolve, check
    dependency failure) funnels through here so the translation order and
    hammer near-miss wiring stay in one place.
    """
    from . import nixrun  # lazy: only on failure
    from .errors import CliError

    msg = translate_eval_failure(err.stderr)
    if msg is None:
        # Best-effort: the hammer checkout enables near-miss hints; resolving
        # it costs one short nix eval on an already-failing (cold) path and
        # silently degrades to None.
        msg = translate_build_failure(
            err.stderr, project, hammer_path=nixrun.hammer_store_path()
        )
    raise CliError(msg) from None


def _generic_eval_fallback(stderr: str) -> str:
    """Short, bounded message for unclassified eval failures.

    Shows the first ``error:`` line (truncated to ~200 chars) when present;
    the full trace is only available under -v.
    """
    first_error = next(
        (ln.strip() for ln in stderr.splitlines() if ln.strip().startswith("error:")),
        None,
    )
    if first_error:
        if len(first_error) > 200:
            first_error = first_error[:200] + "…"
        head = f"nix evaluation failed ({first_error})"
    else:
        head = "nix evaluation failed"
    return head + "\nrerun with -v for the full trace"


def _concrete_failing_drvs(stderr: str) -> list[str]:
    """Concrete failing derivations in Nix stderr, in reported order."""
    return [
        next(group for group in match.groups() if group)
        for match in _FAILED_DRV_RE.finditer(stderr)
    ]


def _failing_drv(stderr: str) -> str | None:
    """First concrete failing builder, else first drv in an aggregate line."""
    drvs = _concrete_failing_drvs(stderr)
    if drvs:
        return drvs[0]
    m = _BUILD_OF_RE.search(stderr)
    if m:
        d = _DRV_PATH_RE.search(m.group(1))
        if d:
            return d.group(0)
    return None


def _parse_drv_name(drv: str) -> tuple[str, str]:
    """/nix/store/<hash>-python3.12-numpy-1.26.4.drv -> ("numpy", "1.26.4").

    Strips the store hash and any pythonX.Y[.Z]- environment prefix, then
    splits name/version the way builtins.parseDrvName does: at the first
    '-' that is followed by a digit. Falls back to the raw name.
    """
    base = drv.rsplit("/", 1)[-1]
    if base.endswith(".drv"):
        base = base[: -len(".drv")]
    # Store hash prefix: 32 base-32 chars + '-'.
    m = re.match(r"^[a-z0-9]{32}-(.+)$", base)
    if m:
        base = m.group(1)
    # Python-set prefix, e.g. "python3.12-" or "python3.12.4-".
    base = re.sub(r"^(?:c?python|pypy)\d[\d.]*-", "", base)
    # parseDrvName: name-version split at first '-' followed by a digit.
    m = re.match(r"^(.+?)-(\d.*)$", base)
    if m:
        return m.group(1), m.group(2)
    return base, ""


def _log_lines(drv: str, stderr: str, log_tail: int) -> list[str]:
    """Last `log_tail` lines of the build log.

    Prefers `nix log <drv>`; falls back to the "> "-prefixed block that
    nix-build embeds in stderr for that same drv.
    """
    from . import nixrun

    log = nixrun.nix_log(drv)
    if log and log.strip():
        return log.splitlines()[-log_tail:]

    # Fallback: the log block Nix prints next to the selected failure. Start
    # matching is deliberately shared across legacy and current formats; the
    # full-stderr extraction above has already validated the modern Reason.
    lines = stderr.splitlines()
    for i, ln in enumerate(lines):
        start = _FAILED_DRV_START_RE.search(ln)
        if start is None or start.group(1) != drv:
            continue
        for marker_idx, candidate in enumerate(lines[i + 1 :], start=i + 1):
            if _FAILED_DRV_START_RE.search(candidate):
                break
            if not _LOG_LINES_MARKER_RE.search(candidate):
                continue
            block: list[str] = []
            for log_ln in lines[marker_idx + 1 :]:
                m = _LOG_LINE_RE.match(log_ln)
                if m is None:
                    break
                block.append(m.group(1))
            if block:
                return block[-log_tail:]
            break
    return []


def _normalize_pkg(name: str) -> str:
    """PEP 503 normalization — hammer override dirs use normalized names."""
    return re.sub(r"[-_.]+", "-", name).lower()


def _locked_package_version(lock_path: Path, package: str) -> str | None:
    """Return a package version from uv.lock, degrading safely on bad input."""
    try:
        with lock_path.open("rb") as lock_file:
            contents = lock_file.read(_MAX_LOCK_BYTES + 1)
        if len(contents) > _MAX_LOCK_BYTES:
            return None
        lock = tomllib.loads(contents.decode("utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError):
        return None

    packages = lock.get("package")
    if not isinstance(packages, list):
        return None

    wanted = _normalize_pkg(package)
    for index, entry in enumerate(packages):
        if index >= _MAX_LOCK_PACKAGES:
            break
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        version = entry.get("version")
        if (
            isinstance(name, str)
            and _normalize_pkg(name) == wanted
            and isinstance(version, str)
            and version
            and version == version.strip()
        ):
            return version
    return None


def _version_key(v: str) -> tuple:
    """Sort key: numeric components numerically, rest lexicographically."""
    return tuple(
        (0, int(part)) if part.isdigit() else (1, part)
        for part in re.split(r"[.\-+]", v)
    )


def _hammer_near_miss(hammer_path: str, package: str, version: str) -> str | None:
    """Near-miss report against the uv2nix_hammer_overrides checkout.

    Real layout of github:TyberiusPrime/uv2nix_hammer_overrides (verified via
    `nix flake prefetch` + listing the store path, rev 8aa81000):

        overrides/<normalized-pkg>/<version>/default.nix   (+ rules.toml)
        manual_overrides/<normalized-pkg>/<version>/default.nix

    i.e. per-package directories containing per-VERSION subdirectories (not
    per-version .nix files); some version dirs carry only a rules.toml. Any
    version subdirectory counts as an available override entry.
    """
    root = Path(hammer_path)
    pkg = _normalize_pkg(package)
    versions: set[str] = set()
    for collection in ("overrides", "manual_overrides"):
        pkg_dir = root / collection / pkg
        if not pkg_dir.is_dir():
            continue
        for entry in pkg_dir.iterdir():
            if entry.is_dir():
                versions.add(entry.name)
    if not versions:
        return None
    listed = ", ".join(sorted(versions, key=_version_key))
    if version and version in versions:
        return (
            f"hint: the hammer override collection has an entry for {package} {version} — "
            "if you disabled it (--no-hammer), re-enabling may fix this."
        )
    return (
        f"hint: the hammer override collection has overrides for {package} at "
        f"version(s) {listed}, but not {version or 'this version'}; "
        "one of those may adapt to your version in uv.nix."
    )


def _load_sonames() -> dict[str, str]:
    try:
        data = (resources.files("uvloom_cli") / "data" / "sonames.json").read_text()
        return json.loads(data)
    except (OSError, ValueError):
        return {}


def _classify(text: str, package: str) -> str | None:
    """Recognized failure classes -> description + paste-able uv.nix stanza."""
    detected: list[str] = []
    native: list[str] = []  # nixpkgs attrs for nativeBuildInputs
    build: list[str] = []  # nixpkgs attrs for buildInputs
    notes: list[str] = []

    for pattern, description, inputs_kind, attr in _TOOL_CLASSES:
        if pattern.search(text):
            detected.append(description)
            (native if inputs_kind == "nativeBuildInputs" else build).append(attr)

    sonames = None
    seen_stems: set[str] = set()
    for m in _AUTOPATCHELF_RE.finditer(text):
        soname = m.group(1)
        stem = soname.split(".so", 1)[0]
        if stem in seen_stems:
            continue
        seen_stems.add(stem)
        if sonames is None:
            sonames = _load_sonames()
        attr = sonames.get(stem)
        detected.append(f"missing shared library {soname} (auto-patchelf)")
        if attr is None:
            notes.append(
                f"note: no known nixpkgs attribute for {soname} — "
                f"search https://search.nixos.org for the library providing it."
            )
        elif not re.fullmatch(r"[A-Za-z_][\w.'-]*", attr):
            # Table value is advice, not an attribute path (e.g. libcuda).
            notes.append(f"note: {soname} is {attr}.")
        else:
            build.append(attr)

    if not detected:
        return None

    parts = ["detected: " + "; ".join(detected) + "."]
    if native or build:
        body: list[str] = []
        if native:
            attrs = " ".join(f"final.pkgs.{a}" for a in native)
            body.append(
                f"    nativeBuildInputs = (old.nativeBuildInputs or [ ]) ++ [ {attrs} ];"
            )
        if build:
            attrs = " ".join(f"final.pkgs.{a}" for a in build)
            body.append(f"    buildInputs = (old.buildInputs or [ ]) ++ [ {attrs} ];")
        stanza = "\n".join(
            [
                "final: prev: {",
                f'  "{package}" = prev."{package}".overrideAttrs (old: {{',
                *body,
                "  });",
                "}",
            ]
        )
        parts.append(
            "paste into uv.nix at the project root (create the file if missing):"
            "\n\n" + stanza
        )
    parts.extend(notes)
    return "\n\n".join(parts)
