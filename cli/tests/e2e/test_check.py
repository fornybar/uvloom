"""``uvloom check`` E2E: run the fixture pytest suite as a Nix build.

templates/pytest ships a passing test suite, so ``uvloom check`` must exit 0
and report success on stderr. A copy with a deliberately failing test must
exit nonzero and surface the pytest failure — never a raw Nix eval trace
(metric 8).
"""

import re

import pytest


@pytest.mark.slow
def test_check_passes(make_project, run_uvloom):
    project = make_project("templates/pytest")
    res = run_uvloom(project, "check", check=True, timeout=3600)
    assert "checks passed" in res.stderr, (
        f"expected 'checks passed' on stderr\n"
        f"--- stdout ---\n{res.stdout}\n--- stderr ---\n{res.stderr}"
    )


@pytest.mark.slow
def test_check_reports_pytest_failure(make_project, run_uvloom):
    project = make_project("templates/pytest")
    (project / "tests" / "test_fail_e2e.py").write_text(
        "def test_fail(): assert False\n"
    )
    res = run_uvloom(project, "check", timeout=3600)
    assert res.returncode == 1, (
        f"uvloom check should exit 1 for a pytest failure, got {res.returncode}\n"
        f"--- stdout ---\n{res.stdout}\n--- stderr ---\n{res.stderr}"
    )
    assert res.stdout == "", (
        f"uvloom check failure output belongs on stderr\n"
        f"--- stdout ---\n{res.stdout}\n--- stderr ---\n{res.stderr}"
    )
    assert "assert False" in res.stderr, (
        f"expected pytest assertion output on stderr\n"
        f"--- stdout ---\n{res.stdout}\n--- stderr ---\n{res.stderr}"
    )
    assert "short test summary info" in res.stderr and "1 failed" in res.stderr, (
        f"expected the pytest failure summary on stderr\n"
        f"--- stdout ---\n{res.stdout}\n--- stderr ---\n{res.stderr}"
    )
    assert re.search(r"/nix/store/[^\s'\"]+\.drv", res.stderr) is None
    for marker in ("while calling", "while evaluating"):
        assert marker not in res.stderr
