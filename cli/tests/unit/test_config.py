"""config.py: project discovery, [tool.uv] parsing, .python-version."""

import pytest

from uvloom_cli.config import UvloomConfig, load_project, python_version_request, source_preference
from uvloom_cli.errors import CliError

from conftest import make_project, write_pyproject


# --- discovery ---------------------------------------------------------------


def test_walk_up_finds_nearest_pyproject(tmp_path):
    write_pyproject(tmp_path / "proj")
    nested = tmp_path / "proj" / "src" / "pkg" / "deep"
    nested.mkdir(parents=True)
    project = load_project(nested)
    assert project.root == (tmp_path / "proj").resolve()
    assert project.pyproject_path == project.root / "pyproject.toml"
    assert project.uv_toml_path == project.root / "uv.toml"
    assert project.lock_path == project.root / "uv.lock"
    assert project.overlay_path == project.root / "uv.nix"
    assert project.discovery_start == nested.resolve()


def test_load_project_file_start_uses_parent_for_discovery(tmp_path):
    write_pyproject(tmp_path / "proj")
    script = tmp_path / "proj" / "tools" / "script.py"
    script.parent.mkdir(parents=True)
    script.write_text("print('x')\n")
    project = load_project(script)
    assert project.root == (tmp_path / "proj").resolve()
    assert project.discovery_start == script.parent.resolve()


def test_nearest_pyproject_wins_over_outer(tmp_path):
    write_pyproject(tmp_path / "outer")
    write_pyproject(tmp_path / "outer" / "inner")
    project = load_project(tmp_path / "outer" / "inner" / "sub")
    # No pyproject in sub itself; walk-up must stop at inner, not outer.
    assert project.root.name == "inner"


def test_no_pyproject_raises_clierror(tmp_path):
    lonely = tmp_path / "lonely"
    lonely.mkdir()
    with pytest.raises(CliError, match="no pyproject.toml found"):
        load_project(lonely)


# --- workspace discovery -------------------------------------------------------


def test_member_resolves_to_workspace_root_with_lock(tmp_path):
    ws = tmp_path / "ws"
    path = write_pyproject(ws, name="ws")
    path.write_text(path.read_text() + "\n[tool.uv.workspace]\nmembers = [\"packages/*\"]\n")
    (ws / "uv.lock").write_text("")
    member = ws / "packages" / "member"
    write_pyproject(member, name="member")
    project = load_project(member)
    assert project.root == ws
    assert project.discovery_start == member.resolve()
    assert project.lock_path == ws / "uv.lock"


def test_workspace_member_with_own_lock_resolves_to_workspace_root(tmp_path):
    ws = tmp_path / "ws"
    path = write_pyproject(ws, name="ws")
    path.write_text(path.read_text() + "\n[tool.uv.workspace]\nmembers = [\"packages/*\"]\n")
    (ws / "uv.lock").write_text("")
    member = ws / "packages" / "member"
    write_pyproject(member, name="member")
    (member / "uv.lock").write_text("")
    project = load_project(member)
    assert project.root == ws
    assert project.lock_path == ws / "uv.lock"


def test_unrelated_locked_nested_project_stays_standalone(tmp_path):
    outer = tmp_path / "outer"
    write_pyproject(outer, name="outer")
    (outer / "uv.lock").write_text("")
    child = outer / "tools" / "child"
    write_pyproject(child, name="child")
    (child / "uv.lock").write_text("")
    assert load_project(child).root == child


def test_workspace_excluded_child_is_standalone_even_with_outer_lock(tmp_path):
    ws = tmp_path / "ws"
    path = write_pyproject(ws, name="ws")
    path.write_text(
        path.read_text()
        + "\n[tool.uv.workspace]\nmembers = [\"packages/*\"]\nexclude = [\"packages/child\"]\n"
    )
    (ws / "uv.lock").write_text("")
    child = ws / "packages" / "child"
    write_pyproject(child, name="child")
    assert load_project(child).root == child


def test_no_lock_anywhere_falls_back_to_nearest_pyproject(tmp_path):
    outer = tmp_path / "outer"
    write_pyproject(outer, name="outer")
    inner = outer / "inner"
    write_pyproject(inner, name="inner")
    project = load_project(inner)
    assert project.root == inner


def test_workspace_declaration_without_lock_wins(tmp_path):
    ws = tmp_path / "ws"
    path = write_pyproject(ws, name="ws")
    path.write_text(path.read_text() + "\n[tool.uv.workspace]\nmembers = [\"packages/*\"]\n")
    member = ws / "packages" / "member"
    write_pyproject(member, name="member")
    project = load_project(member)
    assert project.root == ws


def test_unmanaged_workspace_member_not_captured_by_workspace(tmp_path):
    ws = tmp_path / "ws"
    path = write_pyproject(ws, name="ws")
    path.write_text(path.read_text() + "\n[tool.uv.workspace]\nmembers = [\"packages/*\"]\n")
    (ws / "uv.lock").write_text("")
    member = ws / "packages" / "member"
    write_pyproject(member, name="member", uv_table="managed = false")
    with pytest.raises(CliError, match="managed = false"):
        load_project(member)


def test_unmanaged_workspace_root_does_not_capture_child(tmp_path):
    ws = tmp_path / "ws"
    path = write_pyproject(ws, name="ws", uv_table="managed = false")
    path.write_text(path.read_text() + "\n[tool.uv.workspace]\nmembers = [\"packages/*\"]\n")
    (ws / "uv.lock").write_text("")
    child = ws / "packages" / "child"
    write_pyproject(child, name="child")
    assert load_project(child).root == child


def test_unmanaged_workspace_root_selected_directly_is_rejected(tmp_path):
    ws = tmp_path / "ws"
    path = write_pyproject(ws, name="ws", uv_table="managed = false")
    path.write_text(path.read_text() + "\n[tool.uv.workspace]\nmembers = [\"packages/*\"]\n")
    with pytest.raises(CliError, match="managed = false"):
        load_project(ws)


def test_unmanaged_member_with_own_lock_still_rejected(tmp_path):
    ws = tmp_path / "ws"
    path = write_pyproject(ws, name="ws")
    path.write_text(path.read_text() + "\n[tool.uv.workspace]\nmembers = [\"packages/*\"]\n")
    member = ws / "packages" / "member"
    write_pyproject(member, name="member", uv_table="managed = false")
    (member / "uv.lock").write_text("")
    with pytest.raises(CliError, match="managed = false"):
        load_project(member)


def test_managed_true_workspace_member_keeps_existing_behavior(tmp_path):
    ws = tmp_path / "ws"
    path = write_pyproject(ws, name="ws")
    path.write_text(path.read_text() + "\n[tool.uv.workspace]\nmembers = [\"packages/*\"]\n")
    member = ws / "packages" / "member"
    write_pyproject(member, name="member", uv_table="managed = true")
    assert load_project(member).root == ws


@pytest.mark.parametrize("pattern", ["/tmp/*", "../ws/packages/*"])
def test_absolute_or_escaping_workspace_member_pattern_does_not_capture_child(tmp_path, pattern):
    ws = tmp_path / "ws"
    path = write_pyproject(ws, name="ws")
    child = ws / "packages" / "member"
    write_pyproject(child, name="member")
    if pattern == "/tmp/*":
        # Point at this real child so only the absolute-pattern guard decides.
        pattern = str(child)
    path.write_text(path.read_text() + f'\n[tool.uv.workspace]\nmembers = ["{pattern}"]\n')
    assert load_project(child).root == child


@pytest.mark.parametrize("pattern", ["/tmp/*", "../ws/packages/member"])
def test_absolute_or_escaping_workspace_exclude_pattern_is_ignored(tmp_path, pattern):
    ws = tmp_path / "ws"
    path = write_pyproject(ws, name="ws")
    child = ws / "packages" / "member"
    write_pyproject(child, name="member")
    if pattern == "/tmp/*":
        pattern = str(child)
    path.write_text(
        path.read_text()
        + f'\n[tool.uv.workspace]\nmembers = ["packages/*"]\nexclude = ["{pattern}"]\n'
    )
    assert load_project(child).root == ws


# --- config parsing -----------------------------------------------------------


def test_defaults_without_tool_table(project):
    assert project.config == UvloomConfig()
    assert project.config.no_binary is False


def test_no_tool_tables_no_warning(tmp_path, capsys):
    make_project(tmp_path / "p")
    assert capsys.readouterr().err == ""


def test_invalid_toml_raises_clierror(tmp_path):
    root = tmp_path / "p"
    root.mkdir()
    (root / "pyproject.toml").write_text("this is [not toml")
    with pytest.raises(CliError, match="invalid TOML"):
        load_project(root)


def test_managed_false_standalone_is_rejected(tmp_path):
    root = tmp_path / "p"
    write_pyproject(root, uv_table="managed = false")
    with pytest.raises(CliError, match="managed = false"):
        load_project(root)


def test_managed_false_wrong_type_raises(tmp_path):
    root = tmp_path / "p"
    write_pyproject(root, uv_table='managed = "false"')
    with pytest.raises(CliError, match="managed must be a boolean"):
        load_project(root)


# --- [tool.uv] no-binary -----------------------------------------------------


def test_uv_no_binary_true_sets_no_binary(tmp_path):
    project = make_project(tmp_path / "p", uv_table="no-binary = true")
    assert project.config.no_binary is True


def test_uv_default_groups_absent_defaults_to_dev(tmp_path):
    config = make_project(tmp_path / "p").config
    assert config.default_groups == ("dev",)
    assert config.default_groups_explicit is False


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("[]", ()),
        ('["docs", "lint"]', ("docs", "lint")),
        ('"all"', "all"),
    ],
)
def test_uv_default_groups_supported_values(tmp_path, value, expected):
    project = make_project(tmp_path / "p", uv_table=f"default-groups = {value}")
    assert project.config.default_groups == expected
    assert project.config.default_groups_explicit is True


def test_uv_default_groups_explicit_dev_is_strict(tmp_path):
    config = make_project(tmp_path / "p", uv_table='default-groups = ["dev"]').config
    assert config.default_groups == ("dev",)
    assert config.default_groups_explicit is True


@pytest.mark.parametrize("value", ['"dev"', "true", '[1]', '["bad;name"]'])
def test_uv_default_groups_invalid_values_raise(tmp_path, value):
    with pytest.raises(CliError, match="default-groups"):
        make_project(tmp_path / "p", uv_table=f"default-groups = {value}")


def test_workspace_member_default_groups_ignored_in_favor_of_root(tmp_path):
    ws = tmp_path / "ws"
    write_pyproject(ws, uv_table='default-groups = ["docs"]\nworkspace = { members = ["member"] }')
    write_pyproject(ws / "member", name="member", uv_table='default-groups = ["dev"]')
    assert load_project(ws / "member").config.default_groups == ("docs",)


def test_uv_no_binary_false_or_absent_defaults(tmp_path):
    assert make_project(tmp_path / "a").config.no_binary is False
    assert make_project(tmp_path / "b", uv_table="no-binary = false").config.no_binary is False


def test_uv_no_binary_wrong_type_raises(tmp_path):
    with pytest.raises(CliError, match="no-binary"):
        make_project(tmp_path / "p", uv_table='no-binary = "sdist"')


def test_uv_no_binary_package_empty_list_is_representable(tmp_path):
    make_project(tmp_path / "p", uv_table="no-binary-package = []")


@pytest.mark.parametrize("value", ['["numpy"]', '"numpy"', "true"])
def test_uv_no_binary_package_is_rejected(tmp_path, value):
    with pytest.raises(CliError, match="no-binary-package.*not supported|must be an array"):
        make_project(tmp_path / "p", uv_table=f"no-binary-package = {value}")


def test_uv_toml_overrides_pyproject_no_binary(tmp_path):
    root = tmp_path / "p"
    write_pyproject(root, uv_table="no-binary = false")
    (root / "uv.toml").write_text("no-binary = true\n")
    assert load_project(root).config.no_binary is True


def test_uv_no_binary_env_overrides_uv_toml_and_pyproject(tmp_path, monkeypatch):
    root = tmp_path / "p"
    write_pyproject(root, uv_table="no-binary = true")
    (root / "uv.toml").write_text("no-binary = true\n")
    monkeypatch.setenv("UV_NO_BINARY", "false")
    assert source_preference(load_project(root).config) == "wheel"


def test_uv_toml_absent_setting_leaves_pyproject_setting(tmp_path):
    root = tmp_path / "p"
    write_pyproject(root, uv_table="no-binary = true")
    (root / "uv.toml").write_text("offline = true\n")
    assert load_project(root).config.no_binary is True


def test_uv_toml_uses_top_level_settings(tmp_path):
    root = tmp_path / "p"
    write_pyproject(root)
    (root / "uv.toml").write_text("[tool.uv]\nno-binary = true\n")
    with pytest.raises(CliError, match="top-level uv settings"):
        load_project(root)


def test_uv_toml_default_groups_is_rejected(tmp_path):
    root = tmp_path / "p"
    write_pyproject(root)
    (root / "uv.toml").write_text('default-groups = ["docs"]\n')
    with pytest.raises(CliError, match="uv.toml default-groups.*workspace-root pyproject.toml"):
        load_project(root)


def test_uv_toml_no_binary_package_is_rejected(tmp_path):
    root = tmp_path / "p"
    write_pyproject(root)
    (root / "uv.toml").write_text('no-binary-package = ["numpy"]\n')
    with pytest.raises(CliError, match="no-binary-package.*not supported"):
        load_project(root)


def test_uv_no_binary_env_flips_preference_to_sdist(monkeypatch):
    monkeypatch.setenv("UV_NO_BINARY", "1")
    assert source_preference(UvloomConfig()) == "sdist"


def test_uv_no_binary_env_wins_over_toml_false(monkeypatch):
    monkeypatch.setenv("UV_NO_BINARY", "1")
    assert source_preference(UvloomConfig(no_binary=False)) == "sdist"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("1", "sdist"), ("t", "sdist"), ("true", "sdist"), ("y", "sdist"),
        ("yes", "sdist"), ("on", "sdist"), ("TRUE", "sdist"),
        ("0", "wheel"), ("f", "wheel"), ("false", "wheel"), ("n", "wheel"),
        ("no", "wheel"), ("off", "wheel"), ("FALSE", "wheel"),
    ],
)
def test_uv_no_binary_env_uses_pinned_uv_boolean_spellings(monkeypatch, value, expected):
    monkeypatch.setenv("UV_NO_BINARY", value)
    assert source_preference(UvloomConfig()) == expected


@pytest.mark.parametrize("value", ["", "all", ":all:", "enable", " true "])
def test_uv_no_binary_env_rejects_values_pinned_uv_rejects(monkeypatch, value):
    monkeypatch.setenv("UV_NO_BINARY", value)
    with pytest.raises(CliError, match="UV_NO_BINARY must be a uv boolean"):
        source_preference(UvloomConfig())


def test_uv_no_binary_package_env_is_rejected(monkeypatch):
    monkeypatch.setenv("UV_NO_BINARY_PACKAGE", "numpy")
    with pytest.raises(CliError, match="UV_NO_BINARY_PACKAGE is not supported"):
        source_preference(UvloomConfig())


# --- python_version_request --------------------------------------------------


def test_python_version_file_first_line(project):
    (project.root / ".python-version").write_text("  3.12.4  \nsecond line ignored\n")
    assert python_version_request(project) == "3.12.4"


def test_uv_python_overrides_python_version_file(project, monkeypatch):
    (project.root / ".python-version").write_text("3.11\n")
    monkeypatch.setenv("UV_PYTHON", "3.12.1")
    assert python_version_request(project) == "3.12.1"


def test_uv_python_used_without_python_version_file(project, monkeypatch):
    monkeypatch.setenv("UV_PYTHON", "3.12")
    assert python_version_request(project) == "3.12"


def test_empty_uv_python_ignored(project, monkeypatch):
    (project.root / ".python-version").write_text("3.11\n")
    monkeypatch.setenv("UV_PYTHON", "")
    assert python_version_request(project) == "3.11"


def test_uv_python_absolute_path_is_rejected_even_when_executable(
    project, monkeypatch, tmp_path
):
    exe = tmp_path / "python3.12"
    exe.write_text("#!/bin/sh\n")
    exe.chmod(0o755)
    monkeypatch.setenv("UV_PYTHON", str(exe))
    with pytest.raises(CliError, match=r"UV_PYTHON must be a MAJOR\.MINOR"):
        python_version_request(project)


def test_nested_resolved_python_marker_preserves_declared_version(
    project, monkeypatch, tmp_path
):
    exe = tmp_path / "python3.12"
    exe.write_text("#!/bin/sh\n")
    exe.chmod(0o755)
    (project.root / ".python-version").write_text("3.12\n")
    monkeypatch.setenv("UV_PYTHON", str(exe))
    monkeypatch.setenv("UVLOOM_RESOLVED_PYTHON", str(exe))
    assert python_version_request(project) == "3.12"


def test_mismatched_private_marker_does_not_authorize_public_path(
    project, monkeypatch, tmp_path
):
    public = tmp_path / "public-python"
    public.write_text("#!/bin/sh\n")
    public.chmod(0o755)
    private = tmp_path / "private-python"
    private.write_text("#!/bin/sh\n")
    private.chmod(0o755)
    monkeypatch.setenv("UV_PYTHON", str(public))
    monkeypatch.setenv("UVLOOM_RESOLVED_PYTHON", str(private))
    with pytest.raises(CliError, match=r"UV_PYTHON must be a MAJOR\.MINOR"):
        python_version_request(project)


@pytest.mark.parametrize("kind", ["missing", "directory", "non-executable"])
def test_uv_python_path_is_rejected_as_non_version(project, monkeypatch, tmp_path, kind):
    path = tmp_path / kind
    if kind == "directory":
        path.mkdir()
    elif kind == "non-executable":
        path.write_text("#!/bin/sh\n")
    monkeypatch.setenv("UV_PYTHON", str(path))
    with pytest.raises(CliError, match=r"UV_PYTHON must be a MAJOR\.MINOR"):
        python_version_request(project)


@pytest.mark.parametrize("bad", ["pypy3", "python3.12", "3.x", "cpython@3.12"])
def test_invalid_uv_python_raises_clierror(project, monkeypatch, bad):
    monkeypatch.setenv("UV_PYTHON", bad)
    with pytest.raises(CliError, match=r"UV_PYTHON must be a MAJOR\.MINOR"):
        python_version_request(project)


def test_python_version_file_invalid_version_raises_naming_the_file(project, monkeypatch):
    monkeypatch.delenv("UV_PYTHON", raising=False)
    (project.root / ".python-version").write_text("pypy3\n")
    with pytest.raises(CliError, match=r"\.python-version must be a MAJOR\.MINOR"):
        python_version_request(project)


@pytest.mark.parametrize(
    "kind", ["missing", "directory", "non-executable", "executable"]
)
def test_python_version_file_path_is_rejected_as_non_version(
    project, monkeypatch, tmp_path, kind
):
    monkeypatch.delenv("UV_PYTHON", raising=False)
    path = tmp_path / kind
    if kind == "directory":
        path.mkdir()
    elif kind in {"non-executable", "executable"}:
        path.write_text("#!/bin/sh\n")
        if kind == "executable":
            path.chmod(0o755)
    (project.root / ".python-version").write_text(f"{path}\n")
    with pytest.raises(CliError, match=r"\.python-version must be a MAJOR\.MINOR"):
        python_version_request(project)


def test_no_request_returns_none(project):
    assert python_version_request(project) is None


def test_empty_python_version_file_returns_none(project):
    (project.root / ".python-version").write_text("\n")
    assert python_version_request(project) is None


def test_python_version_first_non_blank_line(project):
    (project.root / ".python-version").write_text("\n3.12\n")
    assert python_version_request(project) == "3.12"
