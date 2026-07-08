"""flakify.py: template rendering, refusal semantics, hammer/overlay toggles."""

import re
import textwrap

import pytest

from uvloom_cli.config import load_project
from uvloom_cli.errors import CliError
from uvloom_cli.flakify import (
    _git_add_targets,
    _interpreter_attr,
    _pins,
    _project_name,
    _render,
    cmd_flakify,
)

from conftest import make_project, write_stub

PLACEHOLDER_RE = re.compile(r"@[A-Za-z]\w*@")


def render(
    tmp_path, *, uv_table="", python_version="", overlay=False, hammer=True, name="demo"
):
    root = tmp_path / "proj"
    if python_version:
        root.mkdir(parents=True, exist_ok=True)
        (root / ".python-version").write_text(python_version + "\n")
    project = make_project(root, name=name, uv_table=uv_table)
    if overlay:
        project.overlay_path.write_text("final: prev: { }\n")
    return project, _render(project, _pins(), hammer=hammer)


def test_render_substitutes_all_placeholders(tmp_path):
    _, text = render(tmp_path, python_version="3.12", overlay=True)
    assert not PLACEHOLDER_RE.search(text), PLACEHOLDER_RE.search(text)


def test_render_bare_project_substitutes_all_placeholders(tmp_path):
    _, text = render(tmp_path)
    assert not PLACEHOLDER_RE.search(text), PLACEHOLDER_RE.search(text)


# --- _project_name -----------------------------------------------------------


def test_project_name_directory_fallback_is_sanitized(tmp_path):
    root = tmp_path / "we ird dir"
    root.mkdir()
    (root / "pyproject.toml").write_text('[project]\nversion = "0.1.0"\n')
    name = _project_name(load_project(root))
    assert name == "we-ird-dir"
    assert re.fullmatch(r"[A-Za-z0-9+._-]+", name)


def test_project_name_neutralizes_quotes_and_interpolation(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    (root / "pyproject.toml").write_text(
        '[project]\nname = "bad\\"name${x}"\nversion = "0.1.0"\n'
    )
    assert _project_name(load_project(root)) == "bad-name--x-"


def test_render_carries_project_facts(tmp_path):
    _, text = render(tmp_path, uv_table="no-binary = true", name="myproj")
    pins = _pins()
    assert f"github:NixOS/nixpkgs/{pins['nixpkgs']['rev']}" in text
    assert 'sourcePreference = "sdist";' in text
    assert '"myproj-env"' in text


@pytest.mark.parametrize(
    ("variable", "value"),
    [
        ("UV_NO_BINARY", "not-a-uv-boolean"),
        ("UV_NO_BINARY", ""),
        ("UV_NO_BINARY_PACKAGE", "numpy"),
        ("UV_NO_BINARY_PACKAGE", "not-a-package-selector:::"),
        ("UV_NO_BINARY_PACKAGE", ""),
    ],
)
def test_render_ignores_inherited_source_environment(tmp_path, monkeypatch, capsys, variable, value):
    """flakify must not parse invocation-only settings into a persistent flake."""
    project, text = render(tmp_path, uv_table="no-binary = true")
    # Establish project-derived result before setting each inherited override.
    assert 'sourcePreference = "sdist";' in text
    monkeypatch.setenv(variable, value)
    text = _render(project, _pins())
    assert 'sourcePreference = "sdist";' in text
    err = capsys.readouterr().err
    assert f"{variable}" in err
    assert "ignored" in err


def test_hammer_included_by_default(tmp_path):
    _, text = render(tmp_path)
    assert "uv2nix-hammer-overrides" in text
    assert "(uv2nix-hammer-overrides.overrides pkgs)" in text


def test_hammer_omitted_when_disabled(tmp_path):
    _, text = render(tmp_path, hammer=False)
    assert "hammer" not in text.lower()


def test_overlay_included_iff_uvloom_nix_present(tmp_path):
    _, without = render(tmp_path / "a")
    assert "uv.nix" not in without
    _, with_overlay = render(tmp_path / "b", overlay=True)
    assert "(import ./uv.nix)" in with_overlay


def test_interpreter_line_rendered(tmp_path, capsys):
    _, text = render(tmp_path, python_version="3.12")
    assert "interpreter = pkgs.python312;" in text

    # exact patch request degrades with the canonical interpreter.py warning
    patch_root = tmp_path / "patch"
    patch_root.mkdir()
    (patch_root / ".python-version").write_text("3.12.4\n")
    project = make_project(patch_root)
    assert _interpreter_attr(project) == "pkgs.python312"
    err = capsys.readouterr().err
    assert err.startswith("uvloom: warning:")
    assert "3.12.4" in err
    assert "python312" in err

    # no request -> no interpreter line at all
    _, bare = render(tmp_path / "bare")
    assert "interpreter =" not in bare


def test_interpreter_invalid_request_raises(tmp_path):
    root = tmp_path / "p"
    root.mkdir()
    (root / ".python-version").write_text("pypy3\n")
    project = make_project(root)
    with pytest.raises(CliError, match="cannot map python request"):
        _interpreter_attr(project)


def test_interpreter_line_uses_discovery_start_and_blank_masks_parent(tmp_path):
    root = tmp_path / "p"
    child = root / "packages" / "a"
    (root).mkdir()
    (root / ".python-version").write_text("3.12\n")
    child.mkdir(parents=True)
    (child / ".python-version").write_text("3.11\n")
    project = make_project(root)
    project.discovery_start = child
    assert _interpreter_attr(project) == "pkgs.python311"
    targets, _ = _git_add_targets(project)
    assert "packages/a/.python-version" in targets
    assert ".python-version" not in targets

    (child / ".python-version").write_text("\n")
    assert _interpreter_attr(project) is None
    targets, _ = _git_add_targets(project)
    assert "packages/a/.python-version" in targets
    assert ".python-version" not in targets


# --- cmd_flakify -------------------------------------------------------------


def test_cmd_flakify_writes_flake(tmp_path, monkeypatch, capsys):
    project = make_project(tmp_path / "proj")
    project.lock_path.write_text("version = 1\n")
    monkeypatch.chdir(project.root)
    assert cmd_flakify([]) == 0
    flake = project.root / "flake.nix"
    assert flake.is_file()
    flake_text = flake.read_text()
    assert not PLACEHOLDER_RE.search(flake_text)
    assert "filterSource = true;" in flake_text
    assert '# extraSourcePaths = [ "tests" "data" ];' in flake_text
    assert "Set filterSource = false" in flake_text
    out = capsys.readouterr().out
    assert f"wrote {flake}" in out
    assert f"git -C {project.root} add -- flake.nix" in out


def test_cmd_flakify_ignores_malformed_source_environment(tmp_path, monkeypatch, capsys):
    project = make_project(tmp_path / "proj", uv_table="no-binary = true")
    project.lock_path.write_text("version = 1\n")
    monkeypatch.setenv("UV_NO_BINARY", "invalid inherited value")
    monkeypatch.setenv("UV_NO_BINARY_PACKAGE", "numpy")
    monkeypatch.chdir(project.root)

    assert cmd_flakify([]) == 0
    flake = (project.root / "flake.nix").read_text()
    assert 'sourcePreference = "sdist";' in flake
    err = capsys.readouterr().err
    assert "UV_NO_BINARY" in err and "ignored" in err
    assert "UV_NO_BINARY_PACKAGE" in err


def test_cmd_flakify_refuses_existing_flake(tmp_path, monkeypatch):
    project = make_project(tmp_path / "proj")
    project.lock_path.write_text("version = 1\n")
    (project.root / "flake.nix").write_text("{ }\n")
    monkeypatch.chdir(project.root)
    with pytest.raises(CliError, match="flake.nix already exists"):
        cmd_flakify([])


def test_cmd_flakify_existing_flake_does_not_bootstrap_lock(tmp_path, monkeypatch):
    project = make_project(tmp_path / "proj")
    (project.root / "flake.nix").write_text("{ }\n")
    uv = write_stub(tmp_path / "uv", 'touch "$PWD/lock-was-mutated"\n')
    monkeypatch.setenv("UVLOOM_UV", str(uv))
    monkeypatch.chdir(project.root)
    with pytest.raises(CliError, match="flake.nix already exists"):
        cmd_flakify([])
    assert not (project.root / "lock-was-mutated").exists()


def test_cmd_flakify_no_hammer_flag(tmp_path, monkeypatch):
    project = make_project(tmp_path / "proj")
    project.lock_path.write_text("version = 1\n")
    monkeypatch.chdir(project.root)
    assert cmd_flakify(["--no-hammer"]) == 0
    assert "hammer" not in (project.root / "flake.nix").read_text().lower()


def test_cmd_flakify_lockless_project_creates_lock_first(tmp_path, monkeypatch, capsys):
    # No uv.lock: a rendered flake could never evaluate. flakify bootstraps
    # the lock like sync/run/venv/check ('uv lock' via UVLOOM_UV).
    project = make_project(tmp_path / "proj")
    uv = write_stub(tmp_path / "uv", 'printf "version = 1\\n" > "$PWD/uv.lock"\n')
    monkeypatch.setenv("UVLOOM_UV", str(uv))
    monkeypatch.chdir(project.root)
    assert cmd_flakify([]) == 0
    assert project.lock_path.is_file()
    assert (project.root / "flake.nix").is_file()
    assert "no uv.lock — creating it via 'uv lock'" in capsys.readouterr().err


def test_cmd_flakify_lock_bootstrap_ignores_uv_project_selectors(tmp_path, monkeypatch):
    project = make_project(tmp_path / "proj")
    other = make_project(tmp_path / "other")
    uv = write_stub(
        tmp_path / "uv",
        'test -z "${UV_PROJECT-}"\n'
        'test -z "${UV_WORKING_DIR-}"\n'
        'printf "version = 1\\n" > "$PWD/uv.lock"\n',
    )
    monkeypatch.setenv("UVLOOM_UV", str(uv))
    monkeypatch.setenv("UV_PROJECT", str(other.root))
    monkeypatch.setenv("UV_WORKING_DIR", str(other.root.parent))
    monkeypatch.chdir(project.root)

    assert cmd_flakify([]) == 0
    assert project.lock_path.is_file()
    assert (project.root / "flake.nix").is_file()
    assert not other.lock_path.exists()


def test_cmd_flakify_lock_failure_is_clierror_and_writes_no_flake(tmp_path, monkeypatch):
    project = make_project(tmp_path / "proj")
    uv = write_stub(tmp_path / "uv", "exit 1\n")
    monkeypatch.setenv("UVLOOM_UV", str(uv))
    monkeypatch.chdir(project.root)
    with pytest.raises(CliError, match="'uv lock' failed"):
        cmd_flakify([])
    assert not (project.root / "flake.nix").exists()


def test_cmd_flakify_rejects_unknown_arguments(tmp_path, monkeypatch):
    project = make_project(tmp_path / "proj")
    monkeypatch.chdir(project.root)
    with pytest.raises(CliError, match="unknown flag '--force'"):
        cmd_flakify(["--force"])


def test_cmd_flakify_git_add_lists_workspace_member_dirs(tmp_path, monkeypatch, capsys):
    project = make_project(tmp_path / "proj")
    (project.root / ".python-version").write_text("3.12\n")
    (project.root / "uv.lock").write_text(
        textwrap.dedent(
            """\
            version = 1

            [[package]]
            name = "member"
            version = "0.1.0"
            source = { directory = "packages/member" }
            """
        )
    )
    monkeypatch.chdir(project.root)
    assert cmd_flakify([]) == 0
    out = capsys.readouterr().out
    add_line = next(line for line in out.splitlines() if " add -- " in line)
    assert "packages/member" in add_line
    assert ".python-version" in add_line


def test_cmd_flakify_git_add_quotes_workspace_member_dirs(tmp_path, monkeypatch, capsys):
    project = make_project(tmp_path / "proj")
    (project.root / "uv.lock").write_text(
        textwrap.dedent(
            """\
            version = 1

            [[package]]
            name = "member"
            version = "0.1.0"
            source = { directory = "packages/my lib" }
            """
        )
    )
    monkeypatch.chdir(project.root)
    assert cmd_flakify([]) == 0
    out = capsys.readouterr().out
    add_line = next(line for line in out.splitlines() if " add -- " in line)
    assert "'packages/my lib'" in add_line


def test_cmd_flakify_notes_uv_nix_imports_must_be_tracked(tmp_path, monkeypatch, capsys):
    project = make_project(tmp_path / "proj")
    project.lock_path.write_text("version = 1\n")
    project.overlay_path.write_text("final: prev: { }\n")
    monkeypatch.chdir(project.root)
    assert cmd_flakify([]) == 0
    out = capsys.readouterr().out
    assert "add -- flake.nix pyproject.toml uv.lock uv.nix" in out
    assert "files uv.nix imports or reads" in out


def test_cmd_flakify_git_add_flat_layout_hints_module_dirs(tmp_path, monkeypatch, capsys):
    project = make_project(tmp_path / "proj")
    (project.root / "uv.lock").write_text(
        textwrap.dedent(
            """\
            version = 1

            [[package]]
            name = "demo"
            version = "0.1.0"
            source = { editable = "." }
            """
        )
    )
    # No src/ directory: flat module layout — module dirs are unknowable, so
    # the explicit list covers the manifests and a hint line asks the user to
    # add the module directories by hand. Never `git add -A`.
    monkeypatch.chdir(project.root)
    assert cmd_flakify([]) == 0
    out = capsys.readouterr().out
    assert "git add -A" not in out
    assert "add -- flake.nix pyproject.toml uv.lock" in out
    assert "also git add the package's module directories" in out


def test_cmd_flakify_git_add_src_layout_has_no_flat_hint(tmp_path, monkeypatch, capsys):
    project = make_project(tmp_path / "proj")
    (project.root / "uv.lock").write_text(
        textwrap.dedent(
            """\
            version = 1

            [[package]]
            name = "demo"
            version = "0.1.0"
            source = { editable = "." }
            """
        )
    )
    (project.root / "src").mkdir()
    monkeypatch.chdir(project.root)
    assert cmd_flakify([]) == 0
    out = capsys.readouterr().out
    add_line = next(line for line in out.splitlines() if " add -- " in line)
    assert "src" in add_line
    assert "also git add" not in out


def test_cmd_flakify_git_add_lists_root_metadata_files(tmp_path, monkeypatch, capsys):
    project = make_project(tmp_path / "proj")
    project.lock_path.write_text("version = 1\n")
    (project.root / "LICENSE").write_text("MIT\n")
    (project.root / "NOTICE.txt").write_text("notice\n")
    monkeypatch.chdir(project.root)
    assert cmd_flakify([]) == 0
    out = capsys.readouterr().out
    add_line = next(line for line in out.splitlines() if " add -- " in line)
    assert "LICENSE" in add_line
    assert "NOTICE.txt" in add_line


def test_cmd_flakify_git_add_lists_declared_license_file(tmp_path, monkeypatch, capsys):
    project = make_project(tmp_path / "proj")
    project.lock_path.write_text("version = 1\n")
    (project.root / "pyproject.toml").write_text(
        textwrap.dedent(
            """\
            [project]
            name = "demo"
            version = "0.1.0"
            license = { file = "legal/LICENSE.txt" }
            """
        )
    )
    (project.root / "legal").mkdir()
    (project.root / "legal" / "LICENSE.txt").write_text("MIT\n")
    monkeypatch.chdir(project.root)
    assert cmd_flakify([]) == 0
    out = capsys.readouterr().out
    add_line = next(line for line in out.splitlines() if " add -- " in line)
    assert "legal/LICENSE.txt" in add_line


def test_cmd_flakify_git_add_expands_license_files_globs(tmp_path, monkeypatch, capsys):
    project = make_project(tmp_path / "proj")
    project.lock_path.write_text("version = 1\n")
    (project.root / "pyproject.toml").write_text(
        textwrap.dedent(
            """\
            [project]
            name = "demo"
            version = "0.1.0"
            license-files = ["legal/LICENSE*"]
            """
        )
    )
    (project.root / "legal").mkdir()
    (project.root / "legal" / "LICENSE.apache").write_text("Apache-2.0\n")
    monkeypatch.chdir(project.root)
    assert cmd_flakify([]) == 0
    out = capsys.readouterr().out
    add_line = next(line for line in out.splitlines() if " add -- " in line)
    assert "legal/LICENSE.apache" in add_line


def test_cmd_flakify_git_add_skips_metadata_named_directories(tmp_path, monkeypatch, capsys):
    project = make_project(tmp_path / "proj")
    project.lock_path.write_text("version = 1\n")
    # A directory whose name matches the metadata prefixes is not a metadata
    # file — filter-source keeps regular files only, and so must the add list.
    (project.root / "LICENSES").mkdir()
    monkeypatch.chdir(project.root)
    assert cmd_flakify([]) == 0
    out = capsys.readouterr().out
    add_line = next(line for line in out.splitlines() if " add -- " in line)
    assert "LICENSES" not in add_line


@pytest.mark.parametrize(
    ("metadata", "message"),
    [
        ('readme = "../outside.md"', "[project].readme"),
        ('license = { file = "../LICENSE" }', "[project].license.file"),
        ('license-files = ["../LICENSE*"]', "license-files pattern"),
    ],
)
def test_cmd_flakify_rejects_escaping_metadata_without_writing(tmp_path, monkeypatch, metadata, message):
    project = make_project(tmp_path / "proj")
    project.lock_path.write_text("version = 1\n")
    (project.root / "pyproject.toml").write_text(
        f"[project]\nname = \"demo\"\nversion = \"0.1.0\"\n{metadata}\n"
    )
    monkeypatch.chdir(project.root)
    with pytest.raises(CliError, match=re.escape(message)):
        cmd_flakify([])
    assert not (project.root / "flake.nix").exists()


def test_cmd_flakify_rejects_malformed_lock_package_array_without_writing(tmp_path, monkeypatch):
    project = make_project(tmp_path / "proj")
    project.lock_path.write_text('version = 1\npackage = ["bad"]\n')
    monkeypatch.chdir(project.root)
    with pytest.raises(CliError, match="package entry 1 is not a table"):
        cmd_flakify([])
    assert not (project.root / "flake.nix").exists()


def test_cmd_flakify_rejects_escaping_lock_source_without_writing(tmp_path, monkeypatch):
    project = make_project(tmp_path / "proj")
    project.lock_path.write_text(
        "version = 1\n\n[[package]]\nname = \"bad\"\nsource = { directory = \"../outside\" }\n"
    )
    monkeypatch.chdir(project.root)
    with pytest.raises(CliError, match="local source from uv.lock"):
        cmd_flakify([])
    assert not (project.root / "flake.nix").exists()
