"""nixrun.py: uvloom Nix library discovery."""

import io
import subprocess
from types import SimpleNamespace

import pytest

from uvloom_cli import nixrun
from uvloom_cli.errors import CliError


def _mock_popen(monkeypatch, *, stdout="", stderr="", rc=0, calls=None):
    class FakeProcess:
        def __init__(self, argv, **kwargs):
            if calls is not None:
                calls.append((argv, kwargs))
            self.stdout = io.StringIO(stdout)
            self.stderr = io.StringIO(stderr)
            self.rc = rc
            self.terminated = False

        def wait(self, timeout=None):
            return self.rc

        def terminate(self):
            self.terminated = True

        def kill(self):
            self.terminated = True

    monkeypatch.setattr(nixrun.subprocess, "Popen", FakeProcess)


def _fake_module_at(tmp_path, depth):
    """A fake nixrun.__file__ nested `depth` dirs below tmp_path."""
    pkg = tmp_path
    for name in ("src", "uvloom_cli")[:depth]:
        pkg = pkg / name
    pkg.mkdir(parents=True, exist_ok=True)
    module = pkg / "nixrun.py"
    module.write_text("")
    return module


def test_fallback_walk_requires_uvloom_specific_sibling(tmp_path, monkeypatch):
    # An unrelated ancestor repo with lib/default.nix must NOT be accepted:
    # only a lib/ that also carries uvloom's scope.nix is ours.
    monkeypatch.delenv("UVLOOM_LIB", raising=False)
    foreign = tmp_path / "lib"
    foreign.mkdir()
    (foreign / "default.nix").write_text("{ }: { }\n")
    monkeypatch.setattr(nixrun, "__file__", str(_fake_module_at(tmp_path, 2)))
    with pytest.raises(CliError, match="cannot locate the uvloom Nix library"):
        nixrun.uvloom_lib_path()


def test_fallback_walk_finds_lib_with_scope_nix(tmp_path, monkeypatch):
    monkeypatch.delenv("UVLOOM_LIB", raising=False)
    lib = tmp_path / "lib"
    lib.mkdir()
    (lib / "default.nix").write_text("{ }: { }\n")
    (lib / "scope.nix").write_text("{ }: { }\n")
    monkeypatch.setattr(nixrun, "__file__", str(_fake_module_at(tmp_path, 2)))
    assert nixrun.uvloom_lib_path() == lib


def test_uvloom_lib_env_needs_only_default_nix(tmp_path, monkeypatch):
    # The explicit override keeps its existing contract: default.nix suffices.
    lib = tmp_path / "anylib"
    lib.mkdir()
    (lib / "default.nix").write_text("{ }: { }\n")
    monkeypatch.setenv("UVLOOM_LIB", str(lib))
    assert nixrun.uvloom_lib_path() == lib


def test_nix_build_uses_options_cwd_and_last_nonblank_stdout_path(tmp_path, monkeypatch):
    calls = []

    _mock_popen(monkeypatch, stdout="\n/nix/store/first\n  \n /nix/store/final  \n", calls=calls)

    assert nixrun.nix_build(["default.nix", "-A", "package"], cwd=tmp_path) == "/nix/store/final"
    assert calls == [
        (
            [
                "nix-build",
                "--option",
                "extra-experimental-features",
                "flakes fetch-tree",
                "--no-out-link",
                "default.nix",
                "-A",
                "package",
            ],
            {"cwd": str(tmp_path), "stdout": subprocess.PIPE, "stderr": subprocess.PIPE},
        )
    ]


def test_nix_build_passes_explicit_out_link(monkeypatch):
    calls = []

    _mock_popen(monkeypatch, stdout="/nix/store/result\n", calls=calls)

    assert nixrun.nix_build(["expr.nix"], out_link="result") == "/nix/store/result"
    assert calls == [
        (
            [
                "nix-build",
                "--option",
                "extra-experimental-features",
                "flakes fetch-tree",
                "--out-link",
                "result",
                "expr.nix",
            ],
            {"cwd": None, "stdout": subprocess.PIPE, "stderr": subprocess.PIPE},
        )
    ]


def test_nix_build_nonzero_retains_stderr(monkeypatch):
    stderr = "error: evaluation failed\ntrace detail\n"
    _mock_popen(monkeypatch, stderr=stderr, rc=17)

    with pytest.raises(nixrun.NixBuildError, match="nix-build exited with status 17") as exc:
        nixrun.nix_build(["broken.nix"])

    assert exc.value.stderr == stderr


def test_nix_build_rejects_empty_output_and_retains_stderr(monkeypatch):
    stderr = "warning emitted despite successful exit\n"
    _mock_popen(monkeypatch, stdout="\n \t\n", stderr=stderr)

    with pytest.raises(nixrun.NixBuildError, match="produced no output path") as exc:
        nixrun.nix_build(["empty.nix"])

    assert exc.value.stderr == stderr


def test_verbose_nix_build_tees_and_retains_stderr(tmp_path, monkeypatch, capsys):
    stderr = "building dependency\nerror: builder failed\n"
    calls = []

    class FakeProcess:
        def __init__(self, argv, **kwargs):
            calls.append((argv, kwargs))
            self.stdout = io.StringIO("/nix/store/incomplete\n")
            self.stderr = io.StringIO(stderr)

        def wait(self):
            return 9

    monkeypatch.setattr(nixrun.subprocess, "Popen", FakeProcess)

    with pytest.raises(nixrun.NixBuildError) as exc:
        nixrun.nix_build(["verbose.nix"], verbose=True, cwd=tmp_path)

    assert exc.value.stderr == stderr
    assert stderr in capsys.readouterr().err
    assert calls == [
        (
            [
                "nix-build",
                "--option",
                "extra-experimental-features",
                "flakes fetch-tree",
                "--no-out-link",
                "verbose.nix",
            ],
            {
                "cwd": str(tmp_path),
                "stdout": subprocess.PIPE,
                    "stderr": subprocess.PIPE,
            },
        )
    ]


def test_nix_build_drains_large_stdout_and_stderr(monkeypatch):
    # Both pipes exceed the usual kernel pipe capacity. The implementation
    # must drain them concurrently, not stderr-then-stdout.
    stdout = "x" * 200_000 + "\n/nix/store/result\n"
    stderr = "warning\n" * 50_000
    _mock_popen(monkeypatch, stdout=stdout, stderr=stderr)

    assert nixrun.nix_build(["large-output.nix"]) == "/nix/store/result"


def test_nix_build_replaces_invalid_utf8_without_losing_output(monkeypatch):
    class FakeProcess:
        def __init__(self, *_args, **_kwargs):
            self.stdout = io.BytesIO(b"/nix/store/result\n")
            self.stderr = io.BytesIO(b"warning: bad byte \xff\n")

        def wait(self, timeout=None):
            return 0

    monkeypatch.setattr(nixrun.subprocess, "Popen", FakeProcess)
    assert nixrun.nix_build(["binary-output.nix"]) == "/nix/store/result"


def test_nix_build_interrupt_terminates_and_reaps_child(monkeypatch):
    created = []

    class FakeProcess:
        def __init__(self, *_args, **_kwargs):
            self.stdout = io.StringIO("")
            self.stderr = io.StringIO("")
            self.wait_calls = 0
            self.terminated = False
            created.append(self)

        def wait(self, timeout=None):
            self.wait_calls += 1
            if self.wait_calls == 1:
                raise KeyboardInterrupt
            return -15

        def terminate(self):
            self.terminated = True

        def kill(self):
            pytest.fail("graceful termination should be reaped without kill")

    monkeypatch.setattr(nixrun.subprocess, "Popen", FakeProcess)

    with pytest.raises(KeyboardInterrupt):
        nixrun.nix_build(["interrupt.nix"])

    assert created[0].terminated
    assert created[0].wait_calls == 2


def test_nix_log_success_uses_expected_process_contract(tmp_path, monkeypatch):
    calls = []

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(stdout="full build log\n", stderr="", returncode=0)

    monkeypatch.setattr(nixrun.subprocess, "run", fake_run)

    assert nixrun.nix_log("/nix/store/example.drv", cwd=tmp_path, timeout=4.5) == "full build log\n"
    assert calls == [
        (
            [
                "nix",
                "--extra-experimental-features",
                "nix-command flakes fetch-tree",
                "log",
                "/nix/store/example.drv",
            ],
            {"cwd": str(tmp_path), "capture_output": True, "text": True, "timeout": 4.5},
        )
    ]


def test_nix_log_nonzero_is_best_effort(monkeypatch):
    monkeypatch.setattr(
        nixrun.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(stdout="partial log", stderr="failure", returncode=1),
    )

    assert nixrun.nix_log("/nix/store/failed.drv") is None


def test_nix_log_timeout_is_best_effort(monkeypatch):
    def timeout(argv, **_kwargs):
        raise subprocess.TimeoutExpired(argv, 0.01)

    monkeypatch.setattr(nixrun.subprocess, "run", timeout)

    assert nixrun.nix_log("/nix/store/slow.drv", timeout=0.01) is None


def test_uv_binary_prefers_environment_override(monkeypatch):
    monkeypatch.setenv("UVLOOM_UV", "/opt/custom/uv")

    def unexpected_path_lookup(_name):
        pytest.fail("PATH must not be consulted when UVLOOM_UV is set")

    monkeypatch.setattr(nixrun.shutil, "which", unexpected_path_lookup)

    assert nixrun.uv_binary() == "/opt/custom/uv"


def test_uv_binary_falls_back_to_path(monkeypatch):
    monkeypatch.delenv("UVLOOM_UV", raising=False)
    monkeypatch.setattr(nixrun.shutil, "which", lambda name: "/usr/bin/uv" if name == "uv" else None)

    assert nixrun.uv_binary() == "/usr/bin/uv"


def test_uv_binary_missing_raises_actionable_error(monkeypatch):
    monkeypatch.delenv("UVLOOM_UV", raising=False)
    monkeypatch.setattr(nixrun.shutil, "which", lambda _name: None)

    with pytest.raises(CliError, match="no 'uv' binary found"):
        nixrun.uv_binary()
