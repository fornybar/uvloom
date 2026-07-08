"""E2E: override layering + failure translation (spec §7 metrics 4 and 8).

Fixtures (cli/tests/fixtures/):

- ``broken_sdist``  — workspace member ``needs-pkgconf`` whose setup.py aborts
  unless pkg-config is on PATH (the tests sync with ``--no-hammer`` so the fix
  must come from the user's uv.nix, applied last in the overlay stack).
- ``hammer_covered`` — depends on ``wrapt==1.16.0`` with sdist preference
  (``[tool.uv] no-binary = true``); wrapt's sdist declares no usable
  build-system, so it builds only when the
  pinned uv2nix_hammer_overrides collection injects setuptools.

Every failing scenario doubles as a metric-8 probe: stderr must carry the
translated failure, never a raw Nix evaluation trace.
"""

import pytest

pytestmark = pytest.mark.slow

# failures._classify() prefix for the ready-to-paste stanza (spec req 18c).
STANZA_MARKER = "paste into uv.nix at the project root"

# Raw Nix trace fragments that must never reach a non-verbose user (metric 8).
RAW_TRACE_MARKERS = ("while evaluating", "while calling")

# The known-good fix for the broken_sdist fixture — byte-identical to the
# stanza the CLI suggests (test_broken_sdist_guidance asserts the suggestion).
WORKING_OVERRIDE = """\
final: prev: {
  "needs-pkgconf" = prev."needs-pkgconf".overrideAttrs (old: {
    nativeBuildInputs = (old.nativeBuildInputs or [ ]) ++ [ final.pkgs.pkg-config ];
  });
}
"""


def assert_no_raw_trace(stderr: str) -> None:
    for marker in RAW_TRACE_MARKERS:
        assert marker not in stderr, (
            f"raw Nix trace marker {marker!r} leaked to the user:\n{stderr}"
        )


# ---------------------------------------------------------------------------
# Metric 4a: user uv.nix layer


def test_broken_sdist_guidance_without_override(make_project, run_uvloom):
    """Without uv.nix the sync fails with req-18 guidance, not a trace."""
    project = make_project("cli/tests/fixtures/broken_sdist")
    assert not (project / "uv.nix").exists()

    res = run_uvloom(project, "sync", "--no-hammer")

    assert res.returncode == 1, f"sync unexpectedly succeeded:\n{res.stdout}"
    stderr = res.stderr
    # (a) failing package + version identified
    assert "build of needs-pkgconf 0.1.0 failed" in stderr
    # (c) recognized failure class -> paste-able stanza naming the package
    assert STANZA_MARKER in stderr
    assert "final: prev: {" in stderr
    assert '"needs-pkgconf" = prev."needs-pkgconf".overrideAttrs' in stderr
    assert "final.pkgs.pkg-config" in stderr
    # Current Nix reports this direct build failure without a derivation path;
    # do not invent a nix log command that cannot be run.
    assert "full log: nix log" not in stderr
    # metric 8: translated form only
    assert_no_raw_trace(stderr)


def test_broken_sdist_fixed_by_uvloom_nix(make_project, run_uvloom):
    """With the suggested stanza written to uv.nix, sync succeeds."""
    project = make_project("cli/tests/fixtures/broken_sdist")
    (project / "uv.nix").write_text(WORKING_OVERRIDE)

    run_uvloom(project, "sync", "--no-hammer", check=True)

    venv = project / ".venv"
    assert venv.is_symlink()
    assert str(venv.resolve()).startswith("/nix/store/")

    # The dependency actually built and imports from the venv.
    res = run_uvloom(
        project,
        "run",
        "--",
        "python",
        "-c",
        "import needs_pkgconf; print(needs_pkgconf.MARKER)",
        check=True,
    )
    assert res.stdout.strip() == "needs-pkgconf-built"


# ---------------------------------------------------------------------------
# Metric 4b: hammer overrides apply by default, disabled by --no-hammer


def test_hammer_override_applies_by_default(make_project, run_uvloom):
    project = make_project("cli/tests/fixtures/hammer_covered")

    run_uvloom(project, "sync", check=True)

    res = run_uvloom(
        project, "run", "--", "python", "-c", "import wrapt; print(wrapt.__version__)",
        check=True,
    )
    assert res.stdout.strip() == "1.16.0"


def test_no_hammer_disables_override(make_project, run_uvloom):
    project = make_project("cli/tests/fixtures/hammer_covered")

    res = run_uvloom(project, "sync", "--no-hammer")

    assert res.returncode == 1, (
        f"--no-hammer sync unexpectedly succeeded:\n{res.stdout}"
    )
    assert "build of wrapt 1.16.0 failed" in res.stderr
    assert_no_raw_trace(res.stderr)
