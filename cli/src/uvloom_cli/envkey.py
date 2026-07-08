"""Environment cache key + marker file.

Marker file: ``<project.root>/.venv-uvloom.json``. JSON shape::

    {
      "key": "<sha256 hex>",
      "interpreter": "/nix/store/.../bin/python3.12",
      "interpreter_request": null,   # effective request at resolve time
      "interpreter_requires_python": ">=3.12",  # requires-python at resolve time
      "cli_version": "0.1.0",
      "store_path": "/nix/store/...-env",
      "config": {                # cached so the hot path never parses toml
        "editable": true,
        "hammer": true,
        "source_preference": "wheel",
        "deps_spec": "workspace-default",
        "sources": [["tree", "."]]  # uv.lock local sources, [kind, relpath]
      }
    }

Hot-path discipline: this module imports only cheap stdlib (hashlib, json, os,
fcntl, contextlib, pathlib). ``compute_key`` hashes raw file BYTES — never a
parsed toml view.
"""

import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path

MARKER_NAME = ".venv-uvloom.json"
LOCK_NAME = ".venv-uvloom.lock"

_UNSET = object()


def marker_path(project) -> Path:
    return project.root / MARKER_NAME


def _hash_file(h: "hashlib._Hash", label: str, path: Path) -> None:
    try:
        data = path.read_bytes()
    except OSError:
        h.update(f"\0{label}:absent\0".encode())
        return
    h.update(f"\0{label}:{len(data)}\0".encode())
    h.update(data)


def _start_dir(start: Path) -> Path:
    return start if start.is_dir() else start.parent


def python_version_file(root: Path, start: Path | None = None) -> Path | None:
    """Nearest existing .python-version from start upward, bounded by root."""
    root = root.resolve()
    cur = _start_dir(start or root).resolve()
    try:
        cur.relative_to(root)
    except ValueError:
        cur = root
    for d in (cur, *cur.parents):
        path = d / ".python-version"
        if path.exists():
            return path
        if d == root:
            break
    return None


def python_version_request(root: Path, start: Path | None = None) -> str | None:
    """Interpreter request from nearest .python-version, bounded by root.

    Missing files continue upward. Nearest existing file is terminal: first
    non-blank line wins; blank/unreadable file yields no request.
    """
    path = python_version_file(root, start)
    if path is None:
        return None
    try:
        text = path.read_text()
    except OSError:
        return None
    for line in text.splitlines():
        line = line.strip()
        if line:
            return line
    return None


def effective_python_request(root: Path, start: Path | None = None) -> str | None:
    """Return UV_PYTHON, unless it is uvloom's internal passthrough.

    Nested uvloom processes inherit the resolved interpreter in both
    UV_PYTHON and UVLOOM_RESOLVED_PYTHON.  That private marker prevents the
    resolved path from replacing the project's declared version in its cache
    key.  Every other UV_PYTHON value keeps normal precedence.

    Validation remains on the cold path in config.python_version_request.
    """
    uv_python = os.environ.get("UV_PYTHON")
    resolved_python = os.environ.get("UVLOOM_RESOLVED_PYTHON")
    if uv_python and uv_python != resolved_python:
        return uv_python
    return python_version_request(root, start)


def env_source_preference() -> str | None:
    """Source preference forced by UV_NO_BINARY; None only when unset.

    Canonical parser for the env half of config.source_preference — the
    cmd_run hot path calls it directly so both paths share one precedence
    rule. Package-specific settings are rejected by config.source_preference.
    """
    value = os.environ.get("UV_NO_BINARY")
    if value is None:
        return None
    # uv 0.11.8 uses clap's boolean parser. Deliberately do not strip: uv
    # rejects whitespace-padded values, and accepting them here would make
    # source selection differ between uvloom and its pinned uv.
    normalized = value.lower()
    if normalized in {"1", "t", "true", "y", "yes", "on"}:
        return "sdist"
    if normalized in {"0", "f", "false", "n", "no", "off"}:
        return "wheel"
    from .errors import CliError

    raise CliError(
        "UV_NO_BINARY must be a uv boolean (1/0, true/false, yes/no, on/off, or t/f/y/n), "
        f"got {value!r}"
    )


# Directories never relevant to a build; pruned from every tree walk.
_EXCLUDED_DIRS = frozenset({".git", ".venv", ".uvloom", "__pycache__", "node_modules"})

# Overlays can import/read any project file, including dotfiles.  Do not use
# _EXCLUDED_DIRS for their closure: node_modules and hidden configuration may
# be intentional inputs.  Exclude only generated runtime state.
_OVERLAY_RUNTIME_DIRS = frozenset({".git", ".venv", ".uvloom", "__pycache__"})


def local_sources(project) -> list[list[str]]:
    """Every local source recorded in uv.lock, as ``[kind, relpath]`` pairs.

    Cold path only (parses toml). Mirrors the library's filterSource
    whitelist exactly:

    - ``tree``: editable/directory sources — whole package trees.
    - ``path``: local wheel/sdist archives (a file, or an unpacked dir).
    - ``virtual``: non-root virtual workspace members — manifest-only
      (uv2nix folds their [tool.uv] config into the workspace).

    uv.lock records NO content hash for any of these, so their bytes must
    feed the env key; missing any kind means a stale venv HIT after the
    source changes without uv.lock changing.
    """
    import tomllib

    try:
        with open(project.lock_path, "rb") as f:
            lock = tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError):
        return []
    packages = lock.get("package", [])
    if not isinstance(packages, list):
        from .errors import CliError

        raise CliError("uv.lock has an invalid package array: 'package' must be an array of tables")
    sources: list[list[str]] = []
    for index, pkg in enumerate(packages, start=1):
        if not isinstance(pkg, dict):
            from .errors import CliError

            raise CliError(
                f"uv.lock has an invalid package array: package entry {index} is not a table"
            )
        source = pkg.get("source", {})
        if not isinstance(source, dict):
            continue
        entry = None
        tree = source.get("editable") or source.get("directory")
        if isinstance(tree, str):
            entry = ["tree", tree]
        elif isinstance(source.get("path"), str):
            entry = ["path", source["path"]]
        elif isinstance(source.get("virtual"), str) and source["virtual"] != ".":
            entry = ["virtual", source["virtual"]]
        if entry and entry not in sources:
            sources.append(entry)
    return sorted(sources)


def _escapes_root(rel: str) -> bool:
    """True for entries the Nix library rejects (absolute or ``..`` segments).

    Such an entry still frames the key (as its literal string) but its bytes
    are never read — the key must not depend on files outside the root.
    """
    return rel.startswith("/") or ".." in rel.split("/")


def requires_python(project) -> str | None:
    """[project].requires-python from pyproject.toml, if readable (cold path)."""
    import tomllib

    try:
        with open(project.pyproject_path, "rb") as f:
            data = tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError):
        return None
    project_table = data.get("project", {})
    if not isinstance(project_table, dict):
        return None
    value = project_table.get("requires-python")
    return value if isinstance(value, str) else None


def declared_metadata_spec(project) -> dict:
    """Declared [project] readme/license metadata, as ``{"paths", "globs"}`` (cold path).

    ``paths``: literal root-relative entries from ``[project].readme``
    (string or ``{file=...}`` dict) and ``[project].license.file`` (dict
    form only). ``globs``: the RAW ``[project].license-files`` patterns —
    never their expansion. filterSource exempts exactly these declared
    entries from its hidden-path filter, so a declared ``.github/README.md``
    reaches the store copy while the tree walks here prune all dot-entries —
    they must feed the key explicitly. Globs stay raw because expansion
    depends on filesystem state: compute_key re-expands them at key time,
    so a newly added file matching a cached pattern still flips the key.
    Mirrors the library: non-list license-files and ``**`` patterns are
    skipped (the Nix lib rejects them loudly at build time), and entries
    escaping the root are dropped — the key must not depend on outside
    files. Missing files still count: compute_key frames each path via
    _hash_file, so deleting a declared readme changes the key.
    """
    import tomllib

    empty = {"paths": [], "globs": []}
    try:
        with open(project.pyproject_path, "rb") as f:
            data = tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError):
        return empty
    table = data.get("project", {})
    if not isinstance(table, dict):
        return empty
    paths: set[str] = set()
    readme = table.get("readme")
    if isinstance(readme, dict):
        readme = readme.get("file")
    if isinstance(readme, str) and not _escapes_root(readme):
        paths.add(readme)
    license_ = table.get("license")
    if isinstance(license_, dict) and isinstance(license_.get("file"), str):
        if not _escapes_root(license_["file"]):
            paths.add(license_["file"])
    globs: set[str] = set()
    license_files = table.get("license-files")
    if isinstance(license_files, list):
        for pattern in license_files:
            if isinstance(pattern, str) and "**" not in pattern and not _escapes_root(pattern):
                globs.add(pattern)
    return {"paths": sorted(paths), "globs": sorted(globs)}


def _hash_tree_contents(h: "hashlib._Hash", label: str, base: Path) -> None:
    """Content digest (relpath header + raw bytes) of every file under base.

    Byte-exact on purpose: the non-editable store venv embeds these sources,
    and a stat-only digest (size + mtime_ns) can be defeated by a
    timestamp-preserving restore, yielding a stale HIT — a wrong environment.
    Hidden files are skipped — the walk must never see uvloom's own sidecars
    (.venv-uvloom.json is rewritten after every build; hashing it would
    invalidate every subsequent key) and the filtered source drops dotfiles
    anyway (.python-version is keyed separately via interpreter_request).
    """
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = sorted(
            d for d in dirnames if d not in _EXCLUDED_DIRS and not d.startswith(".")
        )
        for name in sorted(filenames):
            if name.endswith(".pyc") or name.startswith("."):
                continue
            path = Path(dirpath) / name
            _hash_file(h, f"{label}:{os.path.relpath(path, base)}", path)


def _hash_overlay_inputs(h: "hashlib._Hash", root: Path) -> None:
    """Overlay input closure: content-hash every importable file under root.

    uv.nix may ``import`` sibling .nix files and ``builtins.readFile``/
    ``fromTOML`` any other file under the root, including hidden files, so every such file's
    raw bytes feed the key — a stat digest would be defeated by a
    timestamp-preserving restore (cp -p), yielding a stale hit. The cost is
    only paid when uv.nix exists. Only generated runtime state is skipped:
    VCS/venv/uvloom/cache directories, bytecode, and uvloom's project
    sidecars. uv.nix itself is hashed separately by compute_key.
    """
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in _OVERLAY_RUNTIME_DIRS)
        for name in sorted(filenames):
            if name.endswith(".pyc") or name in {
                MARKER_NAME,
                LOCK_NAME,
                f"{MARKER_NAME}.tmp",
            }:
                continue
            path = Path(dirpath) / name
            label = "nix" if name.endswith(".nix") else "overlay-input"
            _hash_file(h, f"{label}:{os.path.relpath(path, root)}", path)


def _hash_uvloom_lib(h: "hashlib._Hash") -> None:
    """Frame the resolved uvloom Nix library into the key.

    The path string always feeds the key. When the lib lives outside
    /nix/store (repo checkout, UVLOOM_LIB), its contents are mutable, so the
    bytes of every ``*.nix`` directly under it (plus forge-fetch/) are hashed
    too; a store path is immutable and the path string alone suffices.
    """
    from . import nixrun

    lib = nixrun.uvloom_lib_path()
    h.update(f"\0uvloom-lib:{lib}\0".encode())
    if str(lib).startswith("/nix/store/"):
        return
    files: list[Path] = []
    for base in (lib, lib / "forge-fetch"):
        if base.is_dir():
            files.extend(p for p in base.iterdir() if p.is_file() and p.name.endswith(".nix"))
    for path in sorted(files, key=lambda p: os.path.relpath(p, lib)):
        _hash_file(h, f"uvloom-lib:{os.path.relpath(path, lib)}", path)


def compute_key(
    project,
    *,
    editable: bool,
    deps_spec: str,
    hammer: bool,
    source_preference: str,
    interpreter_request=_UNSET,
    sources=_UNSET,
    declared_meta=_UNSET,
    filter_source: bool = True,
    extra_source_paths=(),
) -> str:
    """sha256 over the raw bytes of every input the environment depends on.

    ``project`` only needs ``.root``, ``.pyproject_path``, ``.lock_path``,
    ``.overlay_path``, and ``.uv_toml_path`` — the hot path passes a lightweight stub plus explicit
    ``interpreter_request``, ``sources`` and ``declared_meta`` (from the
    marker's cached config) so no toml is ever parsed on a cache hit.

    ``interpreter_request`` is the EFFECTIVE request (UV_PYTHON, else the
    .python-version file — what effective_python_request returns); the
    default only covers callers without an explicit value.

    Beyond the root manifests, the key covers every local source from
    uv.lock (``local_sources`` pairs): manifest bytes of every tree and
    virtual source always (their build/[tool.uv] config feeds the venv; the
    root's own manifest is already hashed above, so ``virtual = "."`` never
    appears), raw bytes of ``path`` archives always (uv.lock records no
    content hash for them), and the raw bytes of whole trees for
    non-editable builds (the store venv embeds the sources; stat digests
    are defeated by timestamp-preserving restores). Entries escaping the
    project root frame the key as literal strings but are never read — the
    Nix library rejects them, and the key must not depend on outside files.
    Declared [project] readme/license metadata (``declared_meta``, a
    ``{"paths", "globs"}`` spec) is hashed explicitly: filterSource exempts
    it from its hidden-path filter, so its bytes reach the store copy even
    under a hidden dir that the tree walks here prune. License-files globs
    are re-expanded at key time — a cached expansion would miss files added
    under an unchanged pattern. When uv.nix exists, every visible file
    under the root is content-hashed — the overlay may import or readFile
    any of them. The resolved uvloom Nix library feeds the key too — a lib
    change must never produce a stale hit.
    """
    from . import __version__  # package __init__, stdlib-only

    if interpreter_request is _UNSET:
        interpreter_request = effective_python_request(
            project.root, getattr(project, "discovery_start", None)
        )
    if sources is _UNSET:
        sources = local_sources(project)
    if declared_meta is _UNSET:
        declared_meta = declared_metadata_spec(project)

    h = hashlib.sha256()
    h.update(b"uvloom-env-key-v5")
    h.update(f"\0cli:{__version__}\0".encode())
    h.update(f"\0interpreter:{interpreter_request or ''}\0".encode())
    h.update(f"\0editable:{int(bool(editable))}\0".encode())
    h.update(f"\0hammer:{int(bool(hammer))}\0".encode())
    h.update(f"\0source-preference:{source_preference}\0".encode())
    h.update(f"\0deps:{deps_spec}\0".encode())
    h.update(f"\0filter-source:{int(bool(filter_source))}\0".encode())
    extras = sorted(set(extra_source_paths or []))
    h.update(f"\0extra-source-paths:{json.dumps(extras, sort_keys=True)}\0".encode())
    _hash_file(h, "pyproject", project.pyproject_path)
    _hash_file(h, "uv.toml", project.uv_toml_path)
    _hash_file(h, "uv.lock", project.lock_path)
    _hash_file(h, "uv.nix", project.overlay_path)
    for kind, rel in sorted(tuple(s) for s in sources or []):
        escapes = _escapes_root(rel)
        h.update(f"\0source:{kind}:{rel}:{int(escapes)}\0".encode())
        if escapes:
            continue
        base = project.root if rel == "." else project.root / rel
        if kind == "path":
            # Local wheel/sdist archive: a file, or an unpacked directory.
            if base.is_dir():
                _hash_tree_contents(h, f"path-src:{rel}", base)
            else:
                _hash_file(h, f"path-src:{rel}", base)
            continue
        if rel != ".":
            # tree members and virtual members alike: the manifest's build
            # / [tool.uv] config feeds the venv (uv2nix folds member config
            # into the workspace). The root's manifest is hashed above.
            _hash_file(h, f"member-pyproject:{rel}", base / "pyproject.toml")
        if kind != "tree":
            continue
        if editable:
            # The editable venv doesn't embed the trees, but build-backend
            # config beyond pyproject.toml still shapes the built editable
            # wheel; _hash_file frames absent files too, so deleting one
            # also invalidates the key.
            for name in ("setup.py", "setup.cfg", "hatch.toml", "MANIFEST.in"):
                _hash_file(h, f"member-backend:{rel}:{name}", base / name)
        else:
            _hash_tree_contents(h, f"src:{rel}", base)
    meta = declared_meta if isinstance(declared_meta, dict) else {}
    for rel in sorted(set(meta.get("paths") or [])):
        # The helper never yields escaping entries, but the hot path replays
        # a user-writable marker: frame such strings without reading them.
        if _escapes_root(rel):
            h.update(f"\0declared-meta:{rel}:escapes\0".encode())
        else:
            _hash_file(h, f"declared-meta:{rel}", project.root / rel)
    for pattern in sorted(set(meta.get("globs") or [])):
        # Raw patterns re-expanded HERE, never cached expanded: the match
        # set depends on filesystem state, so a file added under a cached
        # pattern must still flip the key. Frame the pattern with its match
        # list (empty included), then hash each match's bytes.
        if "**" in pattern or _escapes_root(pattern):
            h.update(f"\0declared-glob:{pattern}:skipped\0".encode())
            continue
        import glob as globmod  # stdlib, hot path only when globs declared

        matches = sorted(
            m.replace(os.sep, "/")
            for m in globmod.glob(pattern, root_dir=project.root)
            if not _escapes_root(m)
        )
        h.update(f"\0declared-glob:{pattern}:{','.join(matches)}\0".encode())
        for rel in matches:
            _hash_file(h, f"declared-meta:{rel}", project.root / rel)
    if not filter_source:
        _hash_tree_contents(h, "unfiltered-root", project.root)
    else:
        for rel in extras:
            if _escapes_root(rel):
                h.update(f"\0extra-source:{rel}:escapes\0".encode())
                continue
            path = project.root / rel
            if path.is_dir():
                _hash_tree_contents(h, f"extra-source:{rel}", path)
            else:
                _hash_file(h, f"extra-source:{rel}", path)
    if project.overlay_path.exists():
        _hash_overlay_inputs(h, project.root)
    from . import nixrun

    _hash_file(h, "pins.json", nixrun.data_path("pins.json"))
    _hash_uvloom_lib(h)
    return h.hexdigest()


def read_marker(project) -> dict | None:
    try:
        with open(marker_path(project), "rb") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def write_marker(project, data: dict) -> None:
    path = marker_path(project)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n")
    os.replace(tmp, path)


def _venv_path(project) -> Path:
    return project.root / ".venv"


def _valid_store_venv(path: str) -> bool:
    """True only for an absolute, executable Nix-store virtual environment."""
    if not isinstance(path, str) or not path.startswith("/nix/store/"):
        return False
    try:
        candidate = Path(path)
        return candidate.is_dir() and (candidate / "bin").is_dir() and os.access(
            candidate / "bin" / "python", os.X_OK
        )
    except OSError:
        return False


def venv_is_current(project, key: str) -> bool:
    """Marker key matches AND .venv is a symlink to the marker's live store path."""
    marker = read_marker(project)
    if not marker or marker.get("key") != key:
        return False
    store_path = marker.get("store_path")
    if not _valid_store_venv(store_path):
        return False
    venv = _venv_path(project)
    if not venv.is_symlink():
        return False
    try:
        target = os.readlink(venv)
    except OSError:
        return False
    return target == store_path


def venv_is_foreign(project) -> bool:
    """.venv exists and is not a symlink into /nix/store (e.g. plain uv's dir)."""
    venv = _venv_path(project)
    if not os.path.lexists(venv):
        return False
    if not venv.is_symlink():
        return True
    try:
        target = os.readlink(venv)
    except OSError:
        return True
    return not target.startswith("/nix/store/")


def invalidate(project) -> None:
    """Drop the cache key (keeps the cached interpreter path when possible)."""
    with build_lock(project):
        marker = read_marker(project)
        if marker is None:
            with contextlib.suppress(OSError):
                os.unlink(marker_path(project))
            return
        marker.pop("key", None)
        marker.pop("store_path", None)
        try:
            write_marker(project, marker)
        except OSError:
            with contextlib.suppress(OSError):
                os.unlink(marker_path(project))


@contextlib.contextmanager
def build_lock(project):
    """Advisory flock held while (re)building. Readers of a valid marker never take it."""
    path = project.root / LOCK_NAME
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_CLOEXEC, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
