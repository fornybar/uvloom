"""failures.py: build-failure translation (docstring fixtures are ground truth)."""

import textwrap
import types

import pytest

from uvloom_cli.errors import CliError
from uvloom_cli.failures import (
    raise_translated,
    translate_build_failure,
    translate_eval_failure,
    _parse_drv_name,
)


# Fixture 1 from the module docstring: missing pkg-config.
PKG_CONFIG_STDERR = textwrap.dedent(
    """\
    error: builder for '/nix/store/aaaabbbbccccddddeeeeffffgggghhhh-python3.12-pyzmq-26.0.3.drv' failed with exit code 1;
           last 3 log lines:
           > checking for pkg-config...
           > ./configure: line 42: pkg-config: command not found
           > error: Program 'pkg-config' not found
    """
)

# Fixture 2: auto-patchelf unsatisfied soname.
AUTOPATCHELF_STDERR = textwrap.dedent(
    """\
    error: builder for '/nix/store/aaaabbbbccccddddeeeeffffgggghhhh-python3.12-lxml-5.2.1.drv' failed with exit code 1;
           last 2 log lines:
           > auto-patchelf: 1 dependencies could not be satisfied
           > error: auto-patchelf could not satisfy dependency libxslt.so.1 wanted by /nix/store/...-lxml-5.2.1/lib/etree.so
    """
)


# --- translate_build_failure -------------------------------------------------


def test_pkg_config_class(project, no_nix):
    msg = translate_build_failure(PKG_CONFIG_STDERR, project)
    assert "build of pyzmq 26.0.3 failed" in msg
    # log tail carried over from stderr (nix log unavailable)
    assert "pkg-config: command not found" in msg
    assert "detected: 'pkg-config' is missing at build time" in msg
    # ready-to-paste stanza names the failing package and the right inputs kind
    assert '"pyzmq" = prev."pyzmq".overrideAttrs' in msg
    assert "nativeBuildInputs = (old.nativeBuildInputs or [ ]) ++ [ final.pkgs.pkg-config ];" in msg
    assert (
        "full log: nix log /nix/store/aaaabbbbccccddddeeeeffffgggghhhh-python3.12-pyzmq-26.0.3.drv"
        in msg
    )


def test_autopatchelf_soname_class(project, no_nix):
    msg = translate_build_failure(AUTOPATCHELF_STDERR, project)
    assert "build of lxml 5.2.1 failed" in msg
    assert "detected: missing shared library libxslt.so.1 (auto-patchelf)" in msg
    # sonames.json maps libxslt -> libxslt, as buildInputs
    assert '"lxml" = prev."lxml".overrideAttrs' in msg
    assert "buildInputs = (old.buildInputs or [ ]) ++ [ final.pkgs.libxslt ];" in msg


def test_classification_uses_selected_derivation_log_only(project, no_nix):
    stderr = textwrap.dedent(
        """\
        error: builder for '/nix/store/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa-python3.12-package-a-1.0.drv' failed with exit code 1;
               last 2 log lines:
               > building package-a
               > error: package-a failed for an unrelated reason
        error: builder for '/nix/store/bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb-python3.12-package-b-2.0.drv' failed with exit code 1;
               last 2 log lines:
               > checking for pkg-config...
               > error: Program 'pkg-config' not found
        error: build of '/nix/store/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa-python3.12-package-a-1.0.drv', '/nix/store/bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb-python3.12-package-b-2.0.drv' failed
        """
    )
    msg = translate_build_failure(stderr, project)
    assert "build of package-a 1.0 failed" in msg
    assert "package-a failed for an unrelated reason" in msg
    assert "pkg-config" not in msg
    assert "overrideAttrs" not in msg


def test_classification_falls_back_to_stderr_when_no_log_available(project, no_nix):
    stderr = textwrap.dedent(
        """\
        error: build of '/nix/store/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa-python3.12-package-a-1.0.drv' failed
        error: Program 'pkg-config' not found
        """
    )
    msg = translate_build_failure(stderr, project)
    assert "build of package-a 1.0 failed" in msg
    assert "detected: 'pkg-config' is missing at build time" in msg
    assert '"package-a" = prev."package-a".overrideAttrs' in msg


def test_modern_dependency_failure_extracts_version_and_embedded_log(
    project, no_nix
):
    drv = "/nix/store/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa-python3.12-needs-pkgconf-2.4.1.drv"
    stderr = textwrap.dedent(
        f"""\
        error: Cannot build '{drv}'.
               Reason: builder failed with exit code 1.
               Last 2 log lines:
               > configuring needs-pkgconf
               > error: Program 'pkg-config' not found
        """
    )

    msg = translate_build_failure(stderr, project)

    assert "build of needs-pkgconf 2.4.1 failed" in msg
    assert "configuring needs-pkgconf" in msg
    assert "detected: 'pkg-config' is missing at build time" in msg
    assert '"needs-pkgconf" = prev."needs-pkgconf".overrideAttrs' in msg
    assert f"full log: nix log {drv}" in msg


def test_direct_pkg_config_requirement_recovers_locked_version(project, no_nix):
    project.lock_path.write_text(
        'version = 1\n\n[[package]]\nname = "needs-pkgconf"\nversion = "0.1.0"\n'
    )
    stderr = (
        "trace: internal evaluator detail that must stay hidden\n"
        "error: pkg-config is required to build needs-pkgconf\n"
    )

    msg = translate_build_failure(stderr, project)

    assert "build of needs-pkgconf 0.1.0 failed" in msg
    assert "detected: 'pkg-config' is missing at build time" in msg
    assert '"needs-pkgconf" = prev."needs-pkgconf".overrideAttrs' in msg
    assert "final.pkgs.pkg-config" in msg
    assert "internal evaluator detail" not in msg
    assert "nix log" not in msg
    assert ".drv" not in msg


def test_direct_pkg_config_requirement_normalizes_locked_package_name(
    project, no_nix
):
    project.lock_path.write_text(
        'version = 1\n\n[[package]]\nname = "Needs.PkgConf"\nversion = "0.2.0"\n'
    )

    msg = translate_build_failure(
        "error: pkg-config is required to build needs_pkgconf\n", project
    )

    assert msg.splitlines()[0] == "build of needs_pkgconf 0.2.0 failed"


def test_direct_pkg_config_requirement_omits_version_missing_from_lock(
    project, no_nix
):
    project.lock_path.write_text(
        'version = 1\n\n[[package]]\nname = "somewhere-else"\nversion = "9.9.9"\n'
    )

    msg = translate_build_failure(
        "error: pkg-config is required to build needs-pkgconf\n", project
    )

    assert msg.splitlines()[0] == "build of needs-pkgconf failed"
    assert "9.9.9" not in msg


@pytest.mark.parametrize("bad_lock", ["malformed", "unreadable"])
def test_direct_pkg_config_requirement_tolerates_bad_lock(
    project, no_nix, bad_lock
):
    if bad_lock == "malformed":
        project.lock_path.write_text(
            '[[package]\nname = "needs-pkgconf"\nversion = "7.7.7"\n'
        )
    else:
        project.lock_path.mkdir()

    msg = translate_build_failure(
        "error: pkg-config is required to build needs-pkgconf\n", project
    )

    assert msg.splitlines()[0] == "build of needs-pkgconf failed"
    assert "7.7.7" not in msg
    assert "detected: 'pkg-config' is missing at build time" in msg


def test_unidentifiable_failure_concise_fallback(project, no_nix):
    stderr = (
        "error: syntax error, unexpected end of file\n"
        "       at /home/user/proj/uv.nix:12:1:\n"
        "       ... very long nix trace line ...\n"
    )
    msg = translate_build_failure(stderr, project)
    assert msg == (
        "nix evaluation failed (error: syntax error, unexpected end of file)\n"
        "rerun with -v for the full trace"
    )
    # The raw trace never reaches the user (module contract).
    assert "at /home/user/proj/uv.nix" not in msg


def test_unidentifiable_failure_truncates_long_error_line(project, no_nix):
    stderr = "error: " + "x" * 500 + "\n"
    msg = translate_build_failure(stderr, project)
    first = msg.splitlines()[0]
    assert first.startswith("nix evaluation failed (error: ")
    assert len(first) < 260
    assert "…" in first
    assert "rerun with -v for the full trace" in msg


def test_unidentifiable_failure_without_error_line(project, no_nix):
    msg = translate_build_failure("something exploded\nno drv here\n", project)
    assert msg == "nix evaluation failed\nrerun with -v for the full trace"


def test_no_builder_uvloom_fail_still_translates(project, no_nix):
    stderr = "error: uvloom.project.load: root must contain a pyproject.toml"
    msg = translate_build_failure(stderr, project)
    assert msg == "project.load: root must contain a pyproject.toml"


def test_parse_drv_name_strips_hash_and_python_prefix():
    assert _parse_drv_name(
        "/nix/store/aaaabbbbccccddddeeeeffffgggghhhh-python3.12-numpy-1.26.4.drv"
    ) == ("numpy", "1.26.4")
    assert _parse_drv_name("/nix/store/aaaabbbbccccddddeeeeffffgggghhhh-pkg-config-0.29.drv") == (
        "pkg-config",
        "0.29",
    )


# --- hammer near-miss --------------------------------------------------------


def _hammer_tree(tmp_path, entries):
    root = tmp_path / "hammer"
    for collection, pkg, version in entries:
        (root / collection / pkg / version).mkdir(parents=True)
    return root


def test_near_miss_lists_other_versions(project, no_nix, tmp_path):
    hammer = _hammer_tree(
        tmp_path,
        [
            ("overrides", "pyzmq", "26.0.2"),
            ("manual_overrides", "pyzmq", "25.0.0"),
        ],
    )
    msg = translate_build_failure(PKG_CONFIG_STDERR, project, hammer_path=str(hammer))
    assert "overrides for pyzmq at version(s) 25.0.0, 26.0.2, but not 26.0.3" in msg


def test_near_miss_exact_version_suggests_reenabling(project, no_nix, tmp_path):
    hammer = _hammer_tree(tmp_path, [("overrides", "pyzmq", "26.0.3")])
    msg = translate_build_failure(PKG_CONFIG_STDERR, project, hammer_path=str(hammer))
    assert "has an entry for pyzmq 26.0.3" in msg
    assert "re-enabling may fix this" in msg


def test_near_miss_absent_package_says_nothing(project, no_nix, tmp_path):
    hammer = _hammer_tree(tmp_path, [("overrides", "other-pkg", "1.0")])
    msg = translate_build_failure(PKG_CONFIG_STDERR, project, hammer_path=str(hammer))
    assert "hint:" not in msg


# --- translate_eval_failure --------------------------------------------------


def test_eval_missing_uv_lock_exact_message():
    stderr = "error: getting status of '/nix/store/xxx-source/uv.lock': No such file or directory"
    assert translate_eval_failure(stderr) == "no uv.lock — run 'uvloom lock' first"


def test_eval_uvloom_fail_format():
    stderr = "error: uvloom.project.load: root must contain a pyproject.toml"
    assert translate_eval_failure(stderr) == "project.load: root must contain a pyproject.toml"


def test_eval_unrecognized_returns_none():
    assert translate_eval_failure("error: infinite recursion encountered") is None
    assert translate_eval_failure("") is None


def test_eval_uv_lock_in_build_log_falls_through_to_build_translator():
    stderr = (
        "error: builder for '/nix/store/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa-python3.12-foo-1.0.drv'"
        " failed with exit code 1;\n"
        "       last 1 log lines:\n"
        "       > FileNotFoundError: uv.lock: No such file or directory\n"
    )
    assert translate_eval_failure(stderr) is None


def test_eval_missing_uv_lock_outside_store_path():
    stderr = "error: getting status of '/x/uv.lock': No such file or directory"
    assert translate_eval_failure(stderr) == "no uv.lock — run 'uvloom lock' first"


def test_eval_uv_lock_and_missing_path_on_different_lines_is_not_missing_lock():
    # False-positive guard: 'uv.lock' and the does-not-exist text must sit on
    # the SAME line — a trace naming uv.lock elsewhere plus a missing
    # unrelated path must not blame the project lock.
    stderr = (
        "trace: while evaluating uv.lock workspace members\n"
        "error: getting status of '/x/some/other/file.toml': No such file or directory\n"
    )
    assert translate_eval_failure(stderr) is None


def test_eval_group_mismatch_names_group_and_fixes():
    stderr = (
        "error:\n"
        "       … while evaluating derivation 'demo-pytest-env'\n"
        "       error: Extra/group name 'test' does not match either extra or dependency group\n"
    )
    assert translate_eval_failure(stderr) == (
        "dependency group 'test' is not defined in pyproject.toml; "
        "uvloom check selects group 'test' by default — add "
        "[dependency-groups] test = [...] or pass --group <existing-group>"
    )


def test_eval_group_mismatch_reports_the_requested_group():
    stderr = "error: Extra/group name 'integration' does not match either extra or dependency group"
    msg = translate_eval_failure(stderr)
    assert msg is not None
    assert "dependency group 'integration' is not defined" in msg


def test_eval_group_mismatch_in_build_log_falls_through():
    # Embedded build-log lines are "> "-prefixed; the anchored pattern must
    # not fire on a package build that happens to echo the same text.
    stderr = (
        "error: builder for '/nix/store/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa-python3.12-foo-1.0.drv'"
        " failed with exit code 1;\n"
        "       last 1 log lines:\n"
        "       > error: Extra/group name 'test' does not match either extra or dependency group\n"
    )
    assert translate_eval_failure(stderr) is None


# --- raise_translated ----------------------------------------------------------


def test_raise_translated_prefers_eval_translation(project, no_nix):
    err = types.SimpleNamespace(
        stderr="error: uvloom.project.load: root must contain a pyproject.toml"
    )
    with pytest.raises(CliError, match="project.load: root must contain a pyproject.toml"):
        raise_translated(err, project)


def test_raise_translated_falls_back_to_build_translation(project, no_nix):
    err = types.SimpleNamespace(stderr=PKG_CONFIG_STDERR)
    with pytest.raises(CliError, match="build of pyzmq 26.0.3 failed"):
        raise_translated(err, project)
