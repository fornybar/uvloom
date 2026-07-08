"""envkey.py: key determinism/sensitivity, marker roundtrip, venv state, lock."""

import fcntl
import os
import re
import textwrap

import pytest

from uvloom_cli import envkey
from uvloom_cli.errors import CliError

from conftest import make_project, write_pyproject


def _key(project, **overrides):
    kwargs = {
        "editable": True,
        "deps_spec": "workspace-default",
        "hammer": True,
        "source_preference": "wheel",
    }
    kwargs.update(overrides)
    return envkey.compute_key(project, **kwargs)


# --- compute_key -------------------------------------------------------------


def test_key_deterministic(project):
    (project.root / "uv.lock").write_text("version = 1\n")
    assert _key(project) == _key(project)
    assert len(_key(project)) == 64
    int(_key(project), 16)  # hex digest


def test_key_sensitive_to_pyproject_bytes(project):
    before = _key(project)
    project.pyproject_path.write_text(project.pyproject_path.read_text() + "# tweak\n")
    assert _key(project) != before


def test_key_sensitive_to_uv_toml_bytes(project):
    before = _key(project)
    (project.root / "uv.toml").write_text("no-binary = true\n")
    assert _key(project) != before


def test_key_sensitive_to_lock_bytes(project):
    project.lock_path.write_text("version = 1\n")
    before = _key(project)
    project.lock_path.write_text("version = 1\n# changed\n")
    assert _key(project) != before


def test_key_sensitive_to_overlay_presence(project):
    before = _key(project)
    project.overlay_path.write_text("final: prev: { }\n")
    assert _key(project) != before


def test_key_sensitive_to_flags_and_deps_spec(project):
    base = _key(project)
    assert _key(project, editable=False) != base
    assert _key(project, hammer=False) != base
    assert _key(project, deps_spec="all-groups") != base
    # Flag variants are pairwise distinct too.
    assert _key(project, editable=False) != _key(project, hammer=False)


def test_key_sensitive_to_interpreter_request(tmp_path):
    project = make_project(tmp_path / "p")
    base = _key(project)
    (project.root / ".python-version").write_text("3.12\n")
    assert _key(project) != base


def test_key_requires_source_preference_kwarg(project):
    # No default: a caller that forgets to thread the preference must fail
    # loudly instead of hashing a key that silently ignores UV_NO_BINARY.
    with pytest.raises(TypeError, match="source_preference"):
        envkey.compute_key(
            project, editable=True, deps_spec="workspace-default", hammer=True
        )


def test_key_sensitive_to_source_preference(project):
    assert _key(project, source_preference="sdist") != _key(project)


def test_key_sensitive_to_uv_python_env(project, monkeypatch):
    monkeypatch.delenv("UV_PYTHON", raising=False)
    (project.root / ".python-version").write_text("3.12\n")
    base = _key(project)
    monkeypatch.setenv("UV_PYTHON", "3.13")
    assert _key(project) != base
    # UV_PYTHON equal to the file request leaves the effective request — and
    # therefore the key — unchanged.
    monkeypatch.setenv("UV_PYTHON", "3.12")
    assert _key(project) == base


# --- compute_key: workspace source dirs --------------------------------------


def _make_workspace(tmp_path):
    """Root project + one member (pkgs/mem), both local sources in uv.lock."""
    project = make_project(tmp_path / "ws")
    (project.root / "uv.lock").write_text(
        textwrap.dedent(
            """\
            version = 1

            [[package]]
            name = "demo"
            version = "0.1.0"
            source = { editable = "." }

            [[package]]
            name = "mem"
            version = "0.1.0"
            source = { editable = "pkgs/mem" }
            """
        )
    )
    mem = project.root / "pkgs" / "mem"
    write_pyproject(mem, name="mem")
    src = mem / "src" / "mem"
    src.mkdir(parents=True)
    (src / "__init__.py").write_text("x = 1\n")
    return project


def test_key_sensitive_to_member_pyproject_bytes(tmp_path):
    project = _make_workspace(tmp_path)
    before = {e: _key(project, editable=e) for e in (True, False)}
    member = project.root / "pkgs" / "mem" / "pyproject.toml"
    member.write_text(member.read_text() + "# tweak\n")
    assert _key(project, editable=True) != before[True]
    assert _key(project, editable=False) != before[False]


def test_source_bytes_only_affect_non_editable_key(tmp_path):
    project = _make_workspace(tmp_path)
    before = {e: _key(project, editable=e) for e in (True, False)}
    source = project.root / "pkgs" / "mem" / "src" / "mem" / "__init__.py"
    st = source.stat()
    # mtime-only bump: content digest, so no key changes.
    os.utime(source, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))
    assert _key(project, editable=True) == before[True]
    assert _key(project, editable=False) == before[False]
    # Same-size byte change with size+mtime restored (timestamp-preserving
    # restore): the non-editable key must still change.
    source.write_text("x = 2\n")
    os.utime(source, ns=(st.st_atime_ns, st.st_mtime_ns))
    assert source.stat().st_size == st.st_size
    assert _key(project, editable=True) == before[True]
    assert _key(project, editable=False) != before[False]


def test_key_sensitive_to_sibling_nix_files_when_overlay_present(tmp_path):
    project = _make_workspace(tmp_path)
    project.overlay_path.write_text("final: prev: { }\n")
    overrides = project.root / "overrides"
    overrides.mkdir()
    (overrides / "x.nix").write_text("{ }\n")
    before = _key(project)
    (overrides / "x.nix").write_text("{ a = 1; }\n")
    assert _key(project) != before


def test_key_sensitive_to_non_nix_sibling_when_overlay_present(tmp_path):
    project = _make_workspace(tmp_path)
    overrides = project.root / "overrides.json"
    overrides.write_text('{"a": 1}\n')
    without_overlay = _key(project)
    project.overlay_path.write_text("final: prev: { }\n")
    before = _key(project)
    # Same-size byte change with size+mtime restored (timestamp-preserving
    # restore): the overlay may readFile/fromTOML this file, so its raw
    # bytes feed the key.
    st = overrides.stat()
    overrides.write_text('{"a": 2}\n')
    os.utime(overrides, ns=(st.st_atime_ns, st.st_mtime_ns))
    assert overrides.stat().st_size == st.st_size
    assert _key(project) != before
    # Without uv.nix, non-nix siblings are not part of the key.
    project.overlay_path.unlink()
    assert _key(project) == without_overlay



def test_overlay_hashes_hidden_sibling_files(tmp_path):
    # uv.nix can import a dotfile. It is part of its input closure and must
    # invalidate a cached environment when changed.
    project = _make_workspace(tmp_path)
    project.overlay_path.write_text("final: prev: { }\n")
    overrides = project.root / ".overrides.nix"
    overrides.write_text("{ }\n")
    before = _key(project)
    overrides.write_text("{ a = 1; }\n")
    assert _key(project) != before


def test_overlay_ignores_generated_runtime_dirs(tmp_path):
    project = _make_workspace(tmp_path)
    project.overlay_path.write_text("final: prev: { }\n")
    before = _key(project)
    for dirname in (".git", ".venv", ".uvloom"):
        hidden_dir = project.root / dirname
        hidden_dir.mkdir()
        (hidden_dir / "input.nix").write_text("{ changed = true; }\n")
    assert _key(project) == before

def test_marker_sidecar_never_affects_key(tmp_path):
    project = _make_workspace(tmp_path)
    project.overlay_path.write_text("final: prev: { }\n")
    before = {e: _key(project, editable=e) for e in (True, False)}
    (project.root / envkey.MARKER_NAME).write_text('{"key": "abc"}\n')
    (project.root / envkey.LOCK_NAME).write_text("")
    assert _key(project, editable=True) == before[True]
    assert _key(project, editable=False) == before[False]


def test_overlay_hashes_hidden_directory_inputs(tmp_path):
    project = _make_workspace(tmp_path)
    project.overlay_path.write_text("final: prev: { }\n")
    hidden = project.root / ".config"
    hidden.mkdir()
    input_ = hidden / "overrides.nix"
    input_.write_text("{ value = 1; }\n")
    before = _key(project)
    input_.write_text("{ value = 2; }\n")
    assert _key(project) != before


# --- compute_key: path / virtual / escaping sources ----------------------------


def test_key_sensitive_to_path_archive_bytes(project):
    # uv.lock records no content hash for `source = { path = ... }` archives:
    # their raw bytes must feed the key in BOTH editable modes, or swapping
    # the vendored wheel yields a stale HIT with uv.lock unchanged.
    wheel = project.root / "vendored" / "localwheel-0.1.0-py3-none-any.whl"
    wheel.parent.mkdir()
    wheel.write_bytes(b"wheel-bytes-v1")
    project.lock_path.write_text(
        textwrap.dedent(
            """\
            version = 1

            [[package]]
            name = "localwheel"
            version = "0.1.0"
            source = { path = "vendored/localwheel-0.1.0-py3-none-any.whl" }

            [[package]]
            name = "demo"
            version = "0.1.0"
            source = { editable = "." }
            """
        )
    )
    before = {e: _key(project, editable=e) for e in (True, False)}
    wheel.write_bytes(b"wheel-bytes-v2")  # uv.lock untouched
    assert _key(project, editable=True) != before[True]
    assert _key(project, editable=False) != before[False]


def test_key_sensitive_to_unpacked_path_source_tree(project):
    # A path source may also be an unpacked directory: hashed as a tree.
    pkg = project.root / "vendored" / "localpkg"
    pkg.mkdir(parents=True)
    (pkg / "PKG-INFO").write_text("Name: localpkg\n")
    project.lock_path.write_text(
        textwrap.dedent(
            """\
            version = 1

            [[package]]
            name = "localpkg"
            version = "0.1.0"
            source = { path = "vendored/localpkg" }
            """
        )
    )
    before = _key(project)
    (pkg / "module.py").write_text("VALUE = 2\n")
    assert _key(project) != before


def test_key_sensitive_to_virtual_member_manifest_only(project):
    # Non-root virtual members are manifest-only: uv2nix folds their
    # [tool.uv] config into the workspace, so pyproject.toml bytes feed the
    # key — but nothing else in the member tree does.
    helper = project.root / "tools" / "helper"
    write_pyproject(helper, name="helper")
    (helper / "notes.txt").write_text("v1\n")
    project.lock_path.write_text(
        textwrap.dedent(
            """\
            version = 1

            [[package]]
            name = "helper"
            version = "0.1.0"
            source = { virtual = "tools/helper" }

            [[package]]
            name = "demo"
            version = "0.1.0"
            source = { editable = "." }
            """
        )
    )
    before = _key(project)
    (helper / "notes.txt").write_text("v2\n")
    assert _key(project) == before
    (helper / "pyproject.toml").write_text(
        (helper / "pyproject.toml").read_text() + "# tweak\n"
    )
    assert _key(project) != before


def test_key_never_reads_sources_escaping_the_root(project, tmp_path):
    # The Nix library rejects sources outside the root; the key frames such
    # entries as literal strings but must never read the outside bytes.
    outside = tmp_path / "outside"
    write_pyproject(outside, name="outside")
    project.lock_path.write_text(
        textwrap.dedent(
            """\
            version = 1

            [[package]]
            name = "outside"
            version = "0.1.0"
            source = { editable = "../outside" }
            """
        )
    )
    before = {e: _key(project, editable=e) for e in (True, False)}
    (outside / "pyproject.toml").write_text(
        (outside / "pyproject.toml").read_text() + "# tweak\n"
    )
    (outside / "module.py").write_text("VALUE = 3\n")
    assert _key(project, editable=True) == before[True]
    assert _key(project, editable=False) == before[False]


def test_key_frames_escaping_entries_as_literal_strings(project):
    # Same project bytes throughout: only the entry strings differ.
    assert _key(project, sources=[["tree", "../outside"]]) != _key(project, sources=[])
    assert _key(project, sources=[["path", "/abs/a.whl"]]) != _key(
        project, sources=[["path", "/abs/b.whl"]]
    )


# --- compute_key: declared readme/license metadata -----------------------------


def _declare(project, extra: str) -> None:
    """Append declared metadata to the fixture's [project] table."""
    project.pyproject_path.write_text(project.pyproject_path.read_text() + extra)


def test_key_sensitive_to_declared_hidden_readme_bytes(project):
    # filterSource exempts the DECLARED readme from its hidden-path filter,
    # so a `.github/README.md` reaches the store copy — but the tree walks
    # prune dot-entries. The declared path must be hashed explicitly, or
    # editing it yields a stale HIT.
    _declare(project, 'readme = ".github/README.md"\n')
    readme = project.root / ".github" / "README.md"
    readme.parent.mkdir()
    readme.write_text("# one\n")
    before = _key(project)
    readme.write_text("# two\n")
    assert _key(project) != before


def test_key_sensitive_to_license_files_glob_match_bytes(project):
    _declare(project, 'license-files = ["LICENSES/*.txt"]\n')
    lic = project.root / "LICENSES" / "MIT.txt"
    lic.parent.mkdir()
    lic.write_text("MIT\n")
    before = _key(project)
    lic.write_text("MIT (revised)\n")
    assert _key(project) != before


def test_key_stable_when_undeclared_hidden_file_changes(project):
    _declare(project, 'readme = ".github/README.md"\n')
    (project.root / ".github").mkdir()
    (project.root / ".github" / "README.md").write_text("# readme\n")
    other = project.root / ".github" / "FUNDING.yml"
    other.write_text("a: 1\n")
    before = _key(project)
    other.write_text("a: 2\n")
    assert _key(project) == before


def test_key_sensitive_to_declared_readme_deletion(project):
    # _hash_file frames absent files, so deleting the declared readme must
    # invalidate the key (the wheel no longer embeds it).
    _declare(project, 'readme = ".github/README.md"\n')
    readme = project.root / ".github" / "README.md"
    readme.parent.mkdir()
    readme.write_text("# readme\n")
    before = _key(project)
    readme.unlink()
    assert _key(project) != before


def test_declared_metadata_spec_shapes_and_filters(project):
    # dict readme + license.file as literal paths; license-files patterns
    # stay RAW (expansion happens at key time, never cached); ** patterns
    # and root-escaping entries are dropped (Nix lib rejects them).
    _declare(
        project,
        textwrap.dedent(
            """\
            readme = { file = "docs/README.md", content-type = "text/markdown" }
            license = { file = "COPYING" }
            license-files = ["LICENSES/*.txt", "deep/**/*.txt", "../escape*"]
            """
        ),
    )
    assert envkey.declared_metadata_spec(project) == {
        "paths": ["COPYING", "docs/README.md"],
        "globs": ["LICENSES/*.txt"],
    }


def test_declared_metadata_spec_ignores_non_list_license_files(project):
    _declare(project, 'license-files = "LICENSE*"\n')
    assert envkey.declared_metadata_spec(project) == {"paths": [], "globs": []}


def test_new_glob_match_flips_key_with_cached_spec(project):
    # Hot-path contract: the marker caches the RAW spec, not the expanded
    # match list. A file added under an unchanged license-files pattern
    # (pyproject and uv.lock untouched) must still flip the key on the
    # hot-path recompute — globs are re-expanded inside compute_key.
    _declare(project, 'license-files = ["LICENSES/*.txt"]\n')
    lic = project.root / "LICENSES"
    lic.mkdir()
    (lic / "MIT.txt").write_text("MIT\n")
    spec = envkey.declared_metadata_spec(project)
    before = _key(project, declared_meta=spec)
    (lic / "BSD.txt").write_text("BSD\n")
    assert _key(project, declared_meta=spec) != before


# --- python_version_request ---------------------------------------------------


def test_python_version_request_skips_leading_blank_line(tmp_path):
    root = tmp_path / "p"
    root.mkdir()
    (root / ".python-version").write_text("\n  3.12.4  \n3.11\n")
    assert envkey.python_version_request(root) == "3.12.4"


def test_python_version_request_missing_or_blank(tmp_path):
    root = tmp_path / "p"
    root.mkdir()
    assert envkey.python_version_request(root) is None
    (root / ".python-version").write_text("\n\n")
    assert envkey.python_version_request(root) is None


def test_python_version_request_searches_from_start_bounded_by_root(tmp_path):
    root = tmp_path / "p"
    pkg = root / "pkg"
    pkg.mkdir(parents=True)
    (root / ".python-version").write_text("3.12\n")
    assert envkey.python_version_request(root, pkg) == "3.12"
    (pkg / ".python-version").write_text("3.11\n")
    assert envkey.python_version_request(root, pkg) == "3.11"
    assert envkey.python_version_request(root, root) == "3.12"


def test_python_version_request_blank_nearest_stops_parent_fallback(tmp_path):
    root = tmp_path / "p"
    pkg = root / "pkg"
    pkg.mkdir(parents=True)
    (root / ".python-version").write_text("3.12\n")
    (pkg / ".python-version").write_text("\n")
    assert envkey.python_version_request(root, pkg) is None
    assert envkey.python_version_file(root, pkg) == pkg / ".python-version"


def test_effective_python_request_clamps_outside_start(tmp_path, monkeypatch):
    root = tmp_path / "p"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (root / ".python-version").write_text("3.12\n")
    (outside / ".python-version").write_text("3.11\n")
    monkeypatch.delenv("UV_PYTHON", raising=False)
    assert envkey.effective_python_request(root, outside) == "3.12"


# --- requires_python -----------------------------------------------------------


def test_requires_python_reads_project_table(project):
    project.pyproject_path.write_text(
        '[project]\nname = "demo"\nrequires-python = ">=3.12,<3.14"\n'
    )
    assert envkey.requires_python(project) == ">=3.12,<3.14"


def test_requires_python_none_for_missing_malformed_or_wrong_type(project):
    project.pyproject_path.write_text('[project]\nname = "demo"\n')
    assert envkey.requires_python(project) is None
    project.pyproject_path.write_text("[project]\nrequires-python = 3.1\n")
    assert envkey.requires_python(project) is None
    project.pyproject_path.write_text("not toml [[[")
    assert envkey.requires_python(project) is None
    project.pyproject_path.unlink()
    assert envkey.requires_python(project) is None


# --- effective_python_request / env_source_preference -------------------------


def test_effective_python_request_env_overrides_file(tmp_path, monkeypatch):
    root = tmp_path / "p"
    root.mkdir()
    (root / ".python-version").write_text("3.12\n")
    monkeypatch.delenv("UV_PYTHON", raising=False)
    assert envkey.effective_python_request(root) == "3.12"
    monkeypatch.setenv("UV_PYTHON", "3.13")
    assert envkey.effective_python_request(root) == "3.13"
    # Empty UV_PYTHON is no request: the file wins again.
    monkeypatch.setenv("UV_PYTHON", "")
    assert envkey.effective_python_request(root) == "3.12"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("1", "sdist"),
        ("yes", "sdist"),
        ("true", "sdist"),
        ("TRUE", "sdist"),  # case-insensitive
        ("0", "wheel"),
        ("no", "wheel"),
        ("false", "wheel"),
    ],
)
def test_env_source_preference_mapping(monkeypatch, value, expected):
    monkeypatch.setenv("UV_NO_BINARY", value)
    assert envkey.env_source_preference() == expected


def test_env_source_preference_unset_is_none(monkeypatch):
    monkeypatch.delenv("UV_NO_BINARY", raising=False)
    assert envkey.env_source_preference() is None


@pytest.mark.parametrize("value", ["", ":all:", " 1 ", "somepkg"])
def test_env_source_preference_rejects_values_uv_rejects(monkeypatch, value):
    monkeypatch.setenv("UV_NO_BINARY", value)
    with pytest.raises(CliError, match="UV_NO_BINARY must be a uv boolean"):
        envkey.env_source_preference()


# --- local_sources -------------------------------------------------------------


def test_local_sources_kinds_sorted(project):
    project.lock_path.write_text(
        textwrap.dedent(
            """\
            version = 1

            [[package]]
            name = "b"
            version = "0.1.0"
            source = { editable = "pkgs/b" }

            [[package]]
            name = "a"
            version = "0.1.0"
            source = { directory = "pkgs/a" }

            [[package]]
            name = "wheel"
            version = "0.1.0"
            source = { path = "vendored/x.whl" }

            [[package]]
            name = "helper"
            version = "0.1.0"
            source = { virtual = "tools/helper" }

            [[package]]
            name = "demo"
            version = "0.1.0"
            source = { virtual = "." }

            [[package]]
            name = "wheel-dep"
            version = "1.0"
            source = { registry = "https://pypi.org/simple" }
            """
        )
    )
    assert envkey.local_sources(project) == [
        ["path", "vendored/x.whl"],
        ["tree", "pkgs/a"],
        ["tree", "pkgs/b"],
        ["virtual", "tools/helper"],
    ]


def test_local_sources_empty_for_root_virtual_and_missing_lock(project):
    assert envkey.local_sources(project) == []  # no uv.lock
    project.lock_path.write_text(
        textwrap.dedent(
            """\
            version = 1

            [[package]]
            name = "demo"
            version = "0.1.0"
            source = { virtual = "." }
            """
        )
    )
    # The root manifest is hashed separately; `virtual = "."` adds nothing.
    assert envkey.local_sources(project) == []


@pytest.mark.parametrize(
    ("lock_text", "message"),
    [
        ("version = 1\npackage = \"bad\"\n", "'package' must be an array of tables"),
        ("version = 1\npackage = [\"bad\"]\n", "package entry 1 is not a table"),
        ("version = 1\npackage = [{ name = \"ok\" }, 1]\n", "package entry 2 is not a table"),
    ],
)
def test_local_sources_rejects_malformed_package_array(project, lock_text, message):
    project.lock_path.write_text(lock_text)
    with pytest.raises(CliError, match=re.escape(message)):
        envkey.local_sources(project)


def test_compute_key_rejects_malformed_lock_package_array(project):
    project.lock_path.write_text('version = 1\npackage = ["bad"]\n')
    with pytest.raises(CliError, match="package entry 1 is not a table"):
        _key(project)


def test_local_sources_returns_escaping_entries_verbatim(project):
    project.lock_path.write_text(
        textwrap.dedent(
            """\
            version = 1

            [[package]]
            name = "outside"
            version = "0.1.0"
            source = { editable = "../outside" }

            [[package]]
            name = "abswheel"
            version = "0.1.0"
            source = { path = "/abs/wheel.whl" }
            """
        )
    )
    # Enumeration is faithful; the escape policy lives in compute_key.
    assert envkey.local_sources(project) == [
        ["path", "/abs/wheel.whl"],
        ["tree", "../outside"],
    ]


# --- marker roundtrip --------------------------------------------------------


def test_marker_roundtrip(project):
    data = {"key": "abc", "interpreter": "/nix/store/x/bin/python", "cli_version": "0.1.0"}
    envkey.write_marker(project, data)
    path = project.root / envkey.MARKER_NAME
    assert path.is_file()
    assert envkey.read_marker(project) == data
    # write is atomic: no tmp file left behind
    assert not list(project.root.glob("*.tmp"))


def test_read_marker_absent_or_corrupt(project):
    assert envkey.read_marker(project) is None
    (project.root / envkey.MARKER_NAME).write_text("{not json")
    assert envkey.read_marker(project) is None
    (project.root / envkey.MARKER_NAME).write_text('["a", "list"]')
    assert envkey.read_marker(project) is None


# --- venv_is_current ---------------------------------------------------------


def test_venv_current_requires_marker_key_and_live_symlink(project, tmp_path, monkeypatch):
    key = _key(project)
    target = tmp_path / "store-env"
    target.mkdir()
    monkeypatch.setattr(envkey, "_valid_store_venv", lambda path: path == str(target))

    # no marker at all
    assert not envkey.venv_is_current(project, key)

    envkey.write_marker(project, {"key": key, "store_path": str(target)})
    # marker ok but no .venv
    assert not envkey.venv_is_current(project, key)

    (project.root / ".venv").symlink_to(target)
    assert envkey.venv_is_current(project, key)
    # wrong key
    assert not envkey.venv_is_current(project, "deadbeef")

    # symlink target diverging from the marker's store path is stale
    envkey.write_marker(project, {"key": key, "store_path": "/nix/store/other-env"})
    assert not envkey.venv_is_current(project, key)


@pytest.mark.parametrize("store_path", ["relative-env", "/tmp/env", "/nix/store/no-python"])
def test_venv_current_rejects_non_store_or_invalid_venv_shape(project, store_path):
    key = _key(project)
    envkey.write_marker(project, {"key": key, "store_path": store_path})
    (project.root / ".venv").symlink_to(store_path)
    assert not envkey.venv_is_current(project, key)


def test_venv_current_false_for_plain_dir(project):
    key = _key(project)
    envkey.write_marker(project, {"key": key})
    (project.root / ".venv").mkdir()
    assert not envkey.venv_is_current(project, key)


def test_venv_current_false_for_dangling_symlink(project, tmp_path):
    key = _key(project)
    envkey.write_marker(project, {"key": key})
    (project.root / ".venv").symlink_to(tmp_path / "gone")
    assert not envkey.venv_is_current(project, key)


# --- venv_is_foreign ---------------------------------------------------------


def test_venv_foreign(project, tmp_path):
    # missing -> not foreign
    assert not envkey.venv_is_foreign(project)
    # plain directory (uv's own venv) -> foreign
    (project.root / ".venv").mkdir()
    assert envkey.venv_is_foreign(project)
    os.rmdir(project.root / ".venv")
    # symlink outside the store -> foreign
    (project.root / ".venv").symlink_to(tmp_path)
    assert envkey.venv_is_foreign(project)
    os.unlink(project.root / ".venv")
    # symlink into /nix/store -> ours (target need not exist for this check)
    (project.root / ".venv").symlink_to("/nix/store/0000000000000000000000000000000-env")
    assert not envkey.venv_is_foreign(project)


# --- invalidate --------------------------------------------------------------


def test_invalidate_keeps_interpreter(project):
    envkey.write_marker(
        project,
        {"key": "k", "store_path": "/nix/store/x", "interpreter": "/nix/store/py", "config": {}},
    )
    envkey.invalidate(project)
    marker = envkey.read_marker(project)
    assert marker is not None
    assert "key" not in marker
    assert "store_path" not in marker
    assert marker["interpreter"] == "/nix/store/py"


def test_invalidate_without_marker_is_noop(project):
    envkey.invalidate(project)  # must not raise
    assert envkey.read_marker(project) is None


# --- build_lock --------------------------------------------------------------


def test_build_lock_creates_and_releases(project):
    lock_path = project.root / envkey.LOCK_NAME
    with envkey.build_lock(project):
        assert lock_path.exists()
    # Released: a fresh descriptor can take an exclusive non-blocking lock.
    fd = os.open(lock_path, os.O_RDWR)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)  # raises if still held
        fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def test_build_lock_releases_on_exception(project):
    lock_path = project.root / envkey.LOCK_NAME
    try:
        with envkey.build_lock(project):
            raise RuntimeError("boom")
    except RuntimeError:
        pass
    fd = os.open(lock_path, os.O_RDWR)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)
