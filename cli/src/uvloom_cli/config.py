"""Project discovery and supported uv configuration.

Source preference follows uv's precedence: ``UV_NO_BINARY``, project
``uv.toml``, then ``[tool.uv]`` in ``pyproject.toml``.  uvloom has one
project-wide wheel/sdist choice, so package-specific no-binary settings are
rejected instead of being silently applied incorrectly.
"""

import glob
import os
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

from .envkey import effective_python_request, env_source_preference
from .errors import CliError


@dataclass
class UvloomConfig:
    no_binary: bool = False  # True -> build all dependencies from sdists
    default_groups: tuple[str, ...] | str = ("dev",)  # tuple names or "all"
    default_groups_explicit: bool = False


_NAME_RE = re.compile(r"[A-Za-z0-9._-]+")


def _reject_no_binary_package(value, *, source: str) -> None:
    """Reject setting uvloom cannot represent with one sourcePreference."""
    if value is None:
        return
    if not isinstance(value, list) or not all(isinstance(name, str) for name in value):
        raise CliError(f"{source} no-binary-package must be an array of package names")
    if value:
        raise CliError(
            f"{source} no-binary-package is not supported: uvloom only supports "
            "a project-wide wheel or sdist preference"
        )


def source_preference(config: UvloomConfig) -> str:
    """uv2nix source preference derived from uv no-binary settings."""
    reject_unsupported_env_source_settings()
    env_pref = env_source_preference()
    if env_pref is not None:
        return env_pref
    return "sdist" if config.no_binary else "wheel"


def reject_unsupported_env_source_settings() -> None:
    """Validate source-selection environment usable without parsing TOML.

    cmd_run calls this on hot cache hits, where source_preference(Project)
    would defeat cache-path no-TOML discipline.
    """
    if os.environ.get("UV_NO_BINARY_PACKAGE"):
        raise CliError(
            "UV_NO_BINARY_PACKAGE is not supported: uvloom only supports "
            "a project-wide wheel or sdist preference"
        )


@dataclass
class Project:
    root: Path                 # project root (workspace-aware; see load_project)
    discovery_start: Path      # directory used for bounded .python-version discovery
    pyproject_path: Path       # root / "pyproject.toml"
    lock_path: Path            # root / "uv.lock" (may not exist)
    overlay_path: Path         # root / "uv.nix" (may not exist)
    uv_toml_path: Path         # root / "uv.toml" (may not exist)
    config: UvloomConfig


def load_project(start: Path | None = None) -> Project:
    """Walk up from `start` (default cwd) to the project root.

    A nested project is standalone unless it is an actual member of an
    ancestor [tool.uv.workspace]. An ancestor uv.lock alone proves nothing:
    unrelated nested projects are common. A nested project's own lock only
    wins when no ancestor workspace claims it. If no workspace claims it, use
    nearest pyproject directory.
    """
    cur = _start_dir(start if start is not None else Path.cwd()).resolve()
    candidates: list[Path] = []
    for candidate in (cur, *cur.parents):
        pyproject_path = candidate / "pyproject.toml"
        if not pyproject_path.is_file():
            continue
        candidates.append(candidate)
    if not candidates:
        raise CliError(
            f"no pyproject.toml found in '{cur}' or any parent directory"
        )
    nearest = candidates[0]
    for workspace in candidates[1:]:
        if _workspace_contains(workspace / "pyproject.toml", nearest):
            return _project(workspace, cur)
    return _project(nearest, cur)


def _start_dir(start: Path) -> Path:
    return start if start.is_dir() else start.parent


def _project(root: Path, discovery_start: Path | None = None) -> Project:
    _reject_unmanaged_project(root / "pyproject.toml")
    return Project(
        root=root,
        discovery_start=discovery_start or root,
        pyproject_path=root / "pyproject.toml",
        lock_path=root / "uv.lock",
        overlay_path=root / "uv.nix",
        uv_toml_path=root / "uv.toml",
        config=_load_config(root / "pyproject.toml", root / "uv.toml"),
    )


def _managed_from_data(data: dict, *, source: str) -> bool:
    """Return [tool.uv] managed, defaulting to uv's managed=true."""
    tool = data.get("tool")
    uv = tool.get("uv") if isinstance(tool, dict) else None
    if not isinstance(uv, dict) or "managed" not in uv:
        return True
    managed = uv["managed"]
    if not isinstance(managed, bool):
        raise CliError(f"{source} managed must be a boolean, got {managed!r}")
    return managed


def _tool_uv_managed(pyproject_path: Path) -> bool:
    data = _read_toml(pyproject_path, required=True)
    return _managed_from_data(data, source="[tool.uv]")


def _reject_unmanaged_project(pyproject_path: Path) -> None:
    if not _tool_uv_managed(pyproject_path):
        raise CliError(
            "[tool.uv] managed = false is not supported by uvloom: "
            "uv would not manage this project"
        )


def _workspace_contains(pyproject_path: Path, member: Path) -> bool:
    """Whether ``member`` is included by this uv workspace's members/exclude.

    uv workspace paths are root-relative glob patterns. Invalid workspace TOML
    is left to uv to diagnose; discovery must not let a merely locked ancestor
    capture an unrelated child.
    """
    try:
        with open(pyproject_path, "rb") as f:
            data = tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError):
        return False
    tool = data.get("tool")
    uv = tool.get("uv") if isinstance(tool, dict) else None
    workspace = uv.get("workspace") if isinstance(uv, dict) else None
    if not isinstance(workspace, dict):
        return False
    if not _managed_from_data(data, source="[tool.uv]"):
        return False
    members = workspace.get("members")
    if not isinstance(members, list) or not all(isinstance(p, str) for p in members):
        return False
    root = pyproject_path.parent.resolve()
    member = member.resolve()

    def valid_patterns(patterns) -> list[str]:
        """Keep workspace globs confined to workspace root.

        Discovery must never let an absolute or parent-traversing glob make
        an ancestor claim a project outside its tree. uv will diagnose those
        invalid workspace declarations when it is invoked; uvloom ignores
        them for root selection.
        """
        if not isinstance(patterns, list):
            return []
        valid: list[str] = []
        for pattern in patterns:
            if not isinstance(pattern, str):
                continue
            normalized = pattern.replace("\\", "/")
            if os.path.isabs(pattern) or any(part == ".." for part in normalized.split("/")):
                continue
            valid.append(pattern)
        return valid

    def matches(patterns: list[str]) -> bool:
        for pattern in patterns:
            # recursive=True gives uv-style ** support while exact resolved
            # comparison keeps a pattern from accidentally claiming children.
            for found in glob.glob(str(root / pattern), recursive=True):
                if Path(found).resolve() == member:
                    return True
        return False

    if not matches(valid_patterns(members)):
        return False
    member_pyproject = member / "pyproject.toml"
    if member_pyproject.is_file() and not _tool_uv_managed(member_pyproject):
        return False
    excluded = workspace.get("exclude", [])
    excluded_matches = matches(valid_patterns(excluded))
    return not excluded_matches


def _read_toml(path: Path, *, required: bool) -> dict:
    try:
        with open(path, "rb") as f:
            data = tomllib.load(f)
    except tomllib.TOMLDecodeError as exc:
        raise CliError(f"invalid TOML in '{path}': {exc}") from exc
    except OSError as exc:
        if not required and exc.errno == 2:
            return {}
        raise CliError(f"cannot read '{path}': {exc}") from exc
    return data if isinstance(data, dict) else {}


def _no_binary_from_section(section, *, source: str) -> bool | None:
    if not isinstance(section, dict):
        return None
    _reject_no_binary_package(section.get("no-binary-package"), source=source)
    no_binary = section.get("no-binary")
    if no_binary is None:
        return None
    if not isinstance(no_binary, bool):
        raise CliError(f"{source} no-binary must be a boolean, got {no_binary!r}")
    return no_binary


def _default_groups_from_section(section, *, source: str) -> tuple[str, ...] | str | None:
    if not isinstance(section, dict) or "default-groups" not in section:
        return None
    value = section["default-groups"]
    if value == "all":
        return "all"
    if isinstance(value, str):
        raise CliError(
            f"{source} default-groups must be an array of group names or 'all', got {value!r}"
        )
    if isinstance(value, list):
        groups: list[str] = []
        for name in value:
            if not isinstance(name, str) or _NAME_RE.fullmatch(name) is None:
                raise CliError(f"{source} default-groups contains invalid group name {name!r}")
            groups.append(name)
        return tuple(groups)
    raise CliError(
        f"{source} default-groups must be an array of group names or 'all', got {value!r}"
    )


def _load_config(pyproject_path: Path, uv_toml_path: Path) -> UvloomConfig:
    data = _read_toml(pyproject_path, required=True)

    tool = data.get("tool")
    tool = tool if isinstance(tool, dict) else {}
    uv_section = tool.get("uv", {})
    pyproject_no_binary = _no_binary_from_section(uv_section, source="[tool.uv]")
    default_groups = _default_groups_from_section(uv_section, source="[tool.uv]")

    uv_toml = _read_toml(uv_toml_path, required=False)
    if "tool" in uv_toml:
        raise CliError("uv.toml uses top-level uv settings; [tool.uv] belongs in pyproject.toml")
    if "default-groups" in uv_toml:
        raise CliError(
            "uv.toml default-groups is not supported by uv 0.11.8; "
            "put [tool.uv] default-groups in workspace-root pyproject.toml"
        )
    uv_toml_no_binary = _no_binary_from_section(uv_toml, source="uv.toml")
    return UvloomConfig(
        no_binary=(uv_toml_no_binary if uv_toml_no_binary is not None else pyproject_no_binary)
        or False,
        default_groups=("dev",) if default_groups is None else default_groups,
        default_groups_explicit=default_groups is not None,
    )


def _valid_python_request(value: str) -> bool:
    # Keep in sync with interpreter._VERSION_RE (interpreter.py): a bare
    # MAJOR.MINOR[.PATCH] version, digits only — anything looser here would
    # be rejected later by interpreter.interpreter_attr on the cold path.
    value = value.strip()
    if "/" in value:
        return False
    return re.fullmatch(r"\d+\.\d+(?:\.\d+)?", value) is not None


def python_version_request(project: Project) -> str | None:
    """Return the effective, version-only public interpreter request.

    UV_PYTHON normally takes precedence over .python-version.  A nested
    uvloom process may carry its already-resolved executable in UV_PYTHON;
    effective_python_request ignores it only when the private
    UVLOOM_RESOLVED_PYTHON marker exactly matches.
    """
    request = effective_python_request(project.root, project.discovery_start)
    if request and not _valid_python_request(request):
        uv_python = os.environ.get("UV_PYTHON")
        resolved_python = os.environ.get("UVLOOM_RESOLVED_PYTHON")
        source = (
            "UV_PYTHON"
            if uv_python and uv_python != resolved_python
            else ".python-version"
        )
        raise CliError(
            f"{source} must be a MAJOR.MINOR[.PATCH] version like '3.12', "
            f"got {request!r}"
        )
    return request
