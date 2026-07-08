"""Interpreter resolution.

Version request mapping (request -> nixpkgs attribute):
  "3.12"   -> python312
  "3.12.4" -> python312, with a stderr warning naming both versions
             (exact-patch parity is a spec non-goal; degrade deliberately)
  None     -> null in the driver template; the library infers the interpreter
             from requires-python (lib/interpreter.nix) and picks the newest
             matching pkgs.pythonInterpreters entry.
"""

import hashlib
import os
import re
import sys
from pathlib import Path

from . import envkey
from .errors import CliError

# Keep in sync with config._valid_python_request.
_VERSION_RE = re.compile(r"^(\d+)\.(\d+)(?:\.(\d+))?$")


def _requires_python(project) -> str | None:
    """[project].requires-python — canonical parser lives in envkey."""
    return envkey.requires_python(project)


def interpreter_attr(request: str | None) -> str | None:
    """Map a version request to a nixpkgs interpreter attribute name."""
    if request is None:
        return None
    request = request.strip()
    m = _VERSION_RE.match(request)
    if not m:
        raise CliError(
            f"cannot map python request '{request}' to a nixpkgs interpreter — use e.g. '3.12'"
        )
    major, minor, patch = m.group(1), m.group(2), m.group(3)
    attr = f"python{major}{minor}"
    if patch is not None:
        print(
            f"uvloom: warning: exact interpreter {request} is not available from nixpkgs — "
            f"using {major}.{minor} ({attr}) instead",
            file=sys.stderr,
        )
    return attr


def resolve_interpreter(project) -> str:
    """Absolute /nix/store path of the python executable Nix builds against.

    Realizes the driver's ``interpreter`` attribute (a writeText file holding
    ``lib.getExe scope.interpreter``, so realizing it also realizes the
    interpreter). Cached in the marker sidecar under ``interpreter`` together
    ``interpreter_request`` (the effective public version request in effect
    when it was resolved) and ``interpreter_requires_python`` (the project
    requires-python string in effect). The cache is a hit only when both
    recorded inputs still match and the cached path is a regular executable
    file, so editing either input or invalidating the executable forces a
    re-resolve. Rendering, the build, and the marker update run under the
    project build lock so a concurrent sync never sees a half-rewritten
    driver.nix or loses its marker update.
    """
    from .config import python_version_request

    from . import driver, nixrun

    with envkey.build_lock(project):
        current_request = python_version_request(project)
        current_requires_python = _requires_python(project)
        driver_path = driver.render_driver(project)
        fingerprint = _cache_fingerprint(driver_path)
        marker = envkey.read_marker(project)
        if marker:
            cached = marker.get("interpreter")
            if (
                cached
                and marker.get("interpreter_fingerprint") == fingerprint
                and "interpreter_requires_python" in marker
                and marker.get("interpreter_request") == current_request
                and marker.get("interpreter_requires_python") == current_requires_python
                and isinstance(cached, str)
                and os.path.isfile(cached)
                and os.access(cached, os.X_OK)
            ):
                return cached
        try:
            out = nixrun.nix_build(
                [str(driver_path), "-A", "interpreter"],
                out_link=None,
                cwd=project.root,
            )
        except nixrun.NixBuildError as err:
            from . import failures  # lazy: only on failure

            failures.raise_translated(err, project)
        exe = Path(out).read_text().strip()
        if not exe or not os.path.isfile(exe) or not os.access(exe, os.X_OK):
            raise CliError(
                f"resolved interpreter path '{exe}' is not a regular executable file"
            )

        marker = envkey.read_marker(project) or {}
        marker["interpreter"] = exe
        marker["interpreter_fingerprint"] = fingerprint
        marker["interpreter_request"] = current_request
        marker["interpreter_requires_python"] = current_requires_python
        envkey.write_marker(project, marker)
    return exe


def _hash_file(h: "hashlib._Hash", label: str, path: Path) -> None:
    data = path.read_bytes()
    h.update(f"\0{label}:{len(data)}\0".encode())
    h.update(data)


def _cache_fingerprint(driver_path: Path) -> str:
    """Fingerprint every mutable input to interpreter resolution.

    Store-resident libraries are immutable, so their path is sufficient.
    Checkout/UVLOOM_LIB overrides are mutable: hash their complete recursive
    file closure, not only top-level ``*.nix`` files, because Nix imports may
    be nested arbitrarily.
    """
    from . import __version__, nixrun

    try:
        h = hashlib.sha256()
        h.update(b"uvloom-interpreter-cache-v1")
        h.update(f"\0cli:{__version__}\0".encode())
        _hash_file(h, "driver", driver_path)
        for name in ("pins.json", "pins.nix"):
            _hash_file(h, f"pin:{name}", nixrun.data_path(name))
        lib = nixrun.uvloom_lib_path()
        h.update(f"\0uvloom-lib:{lib}\0".encode())
        if str(lib).startswith("/nix/store/"):
            return h.hexdigest()
        # A mutable checkout can change between directory enumeration and
        # reads. Treat that as a cache miss/clean CLI failure, never traceback.
        paths = sorted(
            (p for p in lib.rglob("*") if p.is_file()), key=lambda p: str(p.relative_to(lib))
        )
        for path in paths:
            _hash_file(h, f"uvloom-lib:{path.relative_to(lib)}", path)
        return h.hexdigest()
    except OSError as exc:
        raise CliError(
            f"cannot fingerprint mutable UVLOOM_LIB '{locals().get('lib', '<unknown>')}': {exc}"
        ) from exc
