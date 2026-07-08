"""`uvloom flakify` — graduate a project to a standalone flake.nix."""

import contextlib
import glob
import json
import os
import re
import shlex
import sys
import tempfile
import tomllib
from importlib import resources
from pathlib import Path

from . import envkey
from .config import Project, load_project
from .errors import CliError

_HAMMER_PIN = "uv2nix_hammer_overrides"


def _pins() -> dict:
    """Vendored pins (name -> {owner, repo, rev, narHash}) shipped as package data."""
    data = (resources.files("uvloom_cli") / "data" / "pins.json").read_bytes()
    return json.loads(data)


def _pyproject(project: Project) -> dict:
    try:
        with project.pyproject_path.open("rb") as f:
            return tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def _project_name(project: Project) -> str:
    name = _pyproject(project).get("project", {}).get("name")
    if not (isinstance(name, str) and name):
        name = project.root.name  # virtual root / directory fallback
    # The name lands inside Nix string literals (description, venv names);
    # keep it inert: no quotes, backslashes, or ${} interpolation. Stricter
    # than driver.project_name's charset (store names legitimately allow
    # '?='; string literals must not) — an intentional divergence.
    return re.sub(r"[^A-Za-z0-9+._-]", "-", name)


def _interpreter_attr(project: Project) -> str | None:
    """Map the interpreter request to a nixpkgs attr literal (None: let the library infer).

    Derived from the committed .python-version only: UV_PYTHON is a
    per-invocation override and must not be baked into the generated flake.
    """
    request = envkey.python_version_request(project.root, project.discovery_start)
    env_request = os.environ.get("UV_PYTHON")
    if env_request and env_request.strip() != (request or ""):
        print(
            f"uvloom: warning: UV_PYTHON={env_request} ignored — the generated "
            "flake pins the interpreter from discovered .python-version",
            file=sys.stderr,
        )
    from .interpreter import interpreter_attr

    attr = interpreter_attr(request)
    return f"pkgs.{attr}" if attr else None


def _source_preference(project: Project) -> str:
    """uv2nix source preference for the generated flake.

    Derived from project config only: UV_NO_BINARY is a per-invocation
    override and must not be baked into the generated flake.
    """
    config_pref = "sdist" if project.config.no_binary else "wheel"
    # Never parse these environment values here.  flakify deliberately
    # serializes project configuration, not per-invocation overrides, so an
    # invalid inherited value must not prevent generating that project flake.
    # Normal CLI environment builds still validate/reject both variables in
    # config.source_preference.
    if "UV_NO_BINARY" in os.environ:
        print(
            f"uvloom: warning: UV_NO_BINARY={os.environ.get('UV_NO_BINARY')} ignored — "
            "the generated flake pins source preference from project configuration",
            file=sys.stderr,
        )
    if "UV_NO_BINARY_PACKAGE" in os.environ:
        print(
            "uvloom: warning: UV_NO_BINARY_PACKAGE ignored — the generated flake "
            "does not use per-invocation package-source overrides",
            file=sys.stderr,
        )
    return config_pref


def _render(project: Project, pins: dict, *, hammer: bool = True) -> str:
    template = (resources.files("uvloom_cli") / "data" / "flake.nix.tmpl").read_text()

    nixpkgs = pins.get("nixpkgs")
    if not isinstance(nixpkgs, dict) or "rev" not in nixpkgs:
        raise CliError("vendored pins.json is missing a nixpkgs revision")

    interpreter = _interpreter_attr(project)
    interpreter_line = f"\n          interpreter = {interpreter};" if interpreter else ""

    hammer_input = ""
    hammer_arg = ""
    overlay_items: list[str] = []
    if hammer:
        hammer_pin = pins.get(_HAMMER_PIN)
        if not isinstance(hammer_pin, dict) or "rev" not in hammer_pin:
            raise CliError("vendored pins.json is missing the uv2nix_hammer_overrides revision")
        hammer_input = (
            "    uv2nix-hammer-overrides.url = "
            f"\"github:{hammer_pin['owner']}/{hammer_pin['repo']}/{hammer_pin['rev']}\";\n"
            "    uv2nix-hammer-overrides.inputs.nixpkgs.follows = \"nixpkgs\";\n"
        )
        hammer_arg = ", uv2nix-hammer-overrides"
        overlay_items += [
            "# Pinned batteries-included build fixes; adjust if the upstream API differs.",
            "(uv2nix-hammer-overrides.overrides pkgs)",
        ]
    if project.overlay_path.exists():
        overlay_items += [
            "# Project-local overrides, applied last so they win.",
            "(import ./uv.nix)",
        ]
    if overlay_items:
        body = "\n".join(f"            {item}" for item in overlay_items)
        overlays = f"\n{body}\n          "
    else:
        overlays = " "

    rendered = template
    for key, value in {
        "name": _project_name(project),
        "nixpkgsRev": nixpkgs["rev"],
        "hammerInput": hammer_input,
        "hammerArg": hammer_arg,
        "interpreter": interpreter_line,
        "sourcePreference": _source_preference(project),
        "overlays": overlays,
    }.items():
        rendered = rendered.replace(f"@{key}@", value)
    return rendered


def _readme_path(project: Project) -> str | None:
    """Declared readme from pyproject `project.readme` (string or {file=...})."""
    readme = _pyproject(project).get("project", {}).get("readme")
    if isinstance(readme, dict):
        readme = readme.get("file")
    return readme if isinstance(readme, str) and readme else None


def _inside_root(project: Project, value: str, *, what: str) -> str:
    """Return a root-relative path, rejecting paths which escape project root.

    flakify prints these paths for `git add`, while filterSource later reads
    them from a Git snapshot.  Never let a manifest turn that command into an
    instruction to add arbitrary files outside the project.
    """
    if not isinstance(value, str) or not value:
        raise CliError(f"{what} must be a non-empty root-relative path")
    root = project.root.resolve()
    candidate = (root / value).resolve()
    try:
        relative = candidate.relative_to(root)
    except ValueError:
        raise CliError(f"{what} '{value}' is outside the project root") from None
    if relative == Path("."):
        raise CliError(f"{what} '{value}' cannot be the project root")
    return relative.as_posix()


def _glob_inside_root(project: Project, pattern: str) -> str:
    """Validate a root-relative glob before expansion."""
    # Resolve its non-glob prefix. This catches absolute and `..` forms while
    # preserving normal glob expansion below.
    prefix = re.split(r"[*?[]", pattern, maxsplit=1)[0].rstrip("/") or "."
    if os.path.isabs(pattern):
        raise CliError(f"[project].license-files pattern '{pattern}' is outside the project root")
    if prefix != ".":
        _inside_root(project, prefix, what="[project].license-files pattern")
    if any(part == ".." for part in pattern.replace("\\", "/").split("/")):
        raise CliError(f"[project].license-files pattern '{pattern}' is outside the project root")
    return pattern


def _license_targets(project: Project) -> list[str]:
    """Declared license files: `project.license.file` plus PEP 639 license-files.

    license-files entries are glob patterns relative to the root. A pattern
    that matches nothing is skipped silently here — the Nix side fails loudly
    at build time, and flakify's job is only to assemble the `git add` line.
    """
    proj = _pyproject(project).get("project", {})
    out: list[str] = []
    license = proj.get("license")
    if isinstance(license, dict):
        path = license.get("file")
        if isinstance(path, str) and path:
            path = _inside_root(project, path, what="[project].license.file")
            if (project.root / path).is_file():
                out.append(path)
    patterns = proj.get("license-files")
    if isinstance(patterns, list):
        for pattern in patterns:
            if not isinstance(pattern, str):
                continue
            pattern = _glob_inside_root(project, pattern)
            for match in sorted(glob.glob(pattern, root_dir=project.root)):
                src = _inside_root(
                    project, match.replace(os.sep, "/"), what="[project].license-files match"
                )
                # Backends glob files only; a matching directory is skipped.
                if (project.root / src).is_file() and src not in out:
                    out.append(src)
    return out


def _git_add_targets(project: Project) -> tuple[list[str], bool]:
    """Everything the flake build reads, as `git add` arguments.

    Flakes evaluate only git-tracked files: every input — manifests plus the
    source trees the library's filterSource whitelists — must be added or the
    first `nix build` fails. The bool is False when the root package is a
    flat layout (a "." local source without src/): its module dirs cannot be
    derived, so the caller tells the user to add them by hand.
    """
    tracked = ["flake.nix", "pyproject.toml", "uv.lock"]
    if project.overlay_path.exists():
        tracked.append("uv.nix")
    version_file = envkey.python_version_file(project.root, project.discovery_start)
    if version_file is not None:
        tracked.append(version_file.relative_to(project.root).as_posix())
    readme = _readme_path(project)
    if readme:
        readme = _inside_root(project, readme, what="[project].readme")
        if (project.root / readme).exists():
            tracked.append(readme)
    # Root metadata scan mirrors filter-source.nix: README* plus the PEP 639
    # default license names, regular files only (readDir reports a symlink as
    # "symlink", so a symlinked LICENSE is not whitelisted — nor added here;
    # a LICENSES/ directory is not a metadata file either).
    prefixes = ("README", "LICENSE", "LICENCE", "COPYING", "NOTICE", "AUTHORS")
    with os.scandir(project.root) as entries:
        for entry in sorted(entries, key=lambda e: e.name):
            if entry.name.startswith(prefixes) and entry.is_file(follow_symlinks=False):
                if entry.name not in tracked:
                    tracked.append(entry.name)
    for src in _license_targets(project):
        if src not in tracked:
            tracked.append(src)
    complete = True
    for kind, src in envkey.local_sources(project):
        if kind == "tree" and src == ".":
            if (project.root / "src").is_dir():
                src = "src"
            else:
                complete = False
                continue
        elif kind == "virtual":
            # Manifest-only source: only its pyproject.toml feeds the build.
            src = f"{src}/pyproject.toml"
        src = _inside_root(project, src, what="local source from uv.lock")
        # tree members and path archives (vendored wheels/sdists) are
        # tracked verbatim — the flake build reads them from the git tree.
        if src not in tracked:
            tracked.append(src)
    return tracked, complete


def _write_flake_exclusively(path, rendered: str) -> None:
    """Atomically publish complete content, refusing an existing flake.

    Temporary file is fully written before hard-linking it into final name.
    `link` is atomic and fails when another flakify invocation won race.
    """
    fd, tmp_name = tempfile.mkstemp(prefix=".uvloom-flakify-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as f:
            f.write(rendered)
            f.flush()
            os.fsync(f.fileno())
        try:
            os.link(tmp_name, path)
        except FileExistsError:
            raise CliError("flake.nix already exists — refusing to overwrite") from None
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp_name)


def cmd_flakify(argv: list[str]) -> int:
    hammer = True
    for arg in argv:
        if arg == "--no-hammer":
            hammer = False
        else:
            raise CliError(f"unknown flag '{arg}' for 'uvloom flakify'")
    project = load_project()
    flake_path = project.root / "flake.nix"
    # Refuse before lock bootstrap: a lockless project with an existing flake
    # is still an existing flake, not permission to mutate its lockfile.
    if flake_path.exists():
        raise CliError("flake.nix already exists — refusing to overwrite")
    # A lockless project would render a flake that can never evaluate;
    # reuse the sync/run/venv/check bootstrap (clear CliError on failure).
    from .commands import _ensure_lock

    _ensure_lock(project)
    # Do all fallible discovery before creating output. This leaves no partial
    # flake if malformed metadata or an escaping lock source is found.
    rendered = _render(project, _pins(), hammer=hammer)
    targets, complete = _git_add_targets(project)
    _write_flake_exclusively(flake_path, rendered)
    print(f"wrote {flake_path}")
    print("next steps:")
    print(
        f"  git -C {shlex.quote(str(project.root))} add -- "
        f"{' '.join(shlex.quote(target) for target in targets)}"
    )
    if not complete:
        print("  also git add the package's module directories (flat layout — uvloom cannot derive them)")
    if project.overlay_path.exists():
        print("  any files uv.nix imports or reads must also be git-tracked")
    print("  nix build")
    return 0
