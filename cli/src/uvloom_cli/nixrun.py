"""Nix invocation helpers.

Every invocation enables the needed experimental features explicitly so the
user's nix.conf never needs changes: nix-build gets ``--option
extra-experimental-features 'flakes fetch-tree'`` (NIX_OPTIONS), the ``nix``
CLI calls get ``--extra-experimental-features 'nix-command flakes
fetch-tree'``. Project-relative invocations run with cwd set to the project
root (callers pass ``cwd``).
"""

import contextlib
import os
import re
import shlex
import shutil
import subprocess
import sys
import threading
from importlib import resources
from pathlib import Path

from .errors import CliError

# Passed on every nix-build / nix-instantiate / nix invocation.
NIX_OPTIONS = ["--option", "extra-experimental-features", "flakes fetch-tree"]


class NixBuildError(CliError):
    """A nix invocation exited nonzero. ``.stderr`` holds the full captured stderr.

    Subclasses CliError as a safety net: call sites translate it into an
    actionable message; any escapee prints as a single clean line (never a
    raw Nix trace — spec metric 8). Full stderr stays on ``.stderr`` for the
    translators and the verbose path.
    """

    def __init__(self, message: str, stderr: str):
        super().__init__(f"{message} — re-run with -v for the full Nix output")
        self.stderr = stderr


def nix_build(
    args: list[str],
    *,
    out_link: str | None = None,
    verbose: bool = False,
    cwd: str | Path | None = None,
) -> str:
    """Run nix-build; return the built store path (last stdout line).

    stderr is always captured (for the failure translator); under ``verbose``
    it is additionally streamed live to our own stderr.
    Raises NixBuildError on nonzero exit.
    """
    cmd = ["nix-build", *NIX_OPTIONS]
    if out_link is not None:
        cmd += ["--out-link", out_link]
    else:
        cmd += ["--no-out-link"]
    cmd += args

    if verbose:
        print(f"uvloom: $ {shlex.join(cmd)}", file=sys.stderr)
    proc = subprocess.Popen(
        cmd,
        cwd=str(cwd) if cwd is not None else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert proc.stderr is not None and proc.stdout is not None
    stdout_lines: list[str] = []
    stderr_lines: list[str] = []

    drain_errors: list[BaseException] = []

    def drain(stream, sink, *, tee: bool = False) -> None:
        try:
            # Binary pipes plus replacement decoding prevent an invalid byte
            # from killing a drain thread while its sibling/process blocks.
            while True:
                raw_line = stream.readline()
                if not raw_line:
                    break
                line = (
                    raw_line.decode("utf-8", errors="replace")
                    if isinstance(raw_line, bytes)
                    else raw_line
                )
                sink.append(line)
                if tee:
                    sys.stderr.write(line)
                    sys.stderr.flush()
        except BaseException as exc:
            drain_errors.append(exc)
            # A failed drain means captured output is incomplete. Stop child
            # now rather than waiting forever for a process blocked on pipe
            # output (for example a broken stderr tee).
            with contextlib.suppress(OSError):
                proc.terminate()
        finally:
            with contextlib.suppress(OSError):
                stream.close()

    # Both pipes can be arbitrarily large. Drain independently before wait;
    # reading stderr then stdout deadlocks when stdout fills its pipe.
    stdout_thread = threading.Thread(target=drain, args=(proc.stdout, stdout_lines), daemon=True)
    stderr_thread = threading.Thread(
        target=drain, args=(proc.stderr, stderr_lines), kwargs={"tee": verbose}, daemon=True
    )
    stdout_thread.start()
    stderr_thread.start()
    try:
        rc = proc.wait()
        stdout_thread.join()
        stderr_thread.join()
        if drain_errors:
            raise CliError(f"failed while reading nix-build output: {drain_errors[0]}") from drain_errors[0]
    except BaseException:
        # Do not strand a Nix child when Ctrl-C or a stream/write exception
        # aborts us. Reap it before preserving the original exception/status.
        with contextlib.suppress(OSError):
            proc.terminate()
        try:
            proc.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            with contextlib.suppress(OSError):
                proc.kill()
            with contextlib.suppress(OSError, subprocess.TimeoutExpired):
                proc.wait(timeout=5)
        raise
    finally:
        # Closing pipes unblocks a reader after child termination; joins make
        # worker failures observable and avoid daemon-thread leakage.
        with contextlib.suppress(OSError):
            proc.stdout.close()
        with contextlib.suppress(OSError):
            proc.stderr.close()
        stdout_thread.join()
        stderr_thread.join()
    stdout = "".join(stdout_lines)
    stderr = "".join(stderr_lines)

    if rc != 0:
        raise NixBuildError(f"nix-build exited with status {rc}", stderr)

    lines = [ln for ln in stdout.splitlines() if ln.strip()]
    if not lines:
        raise NixBuildError("nix-build produced no output path", stderr)
    return lines[-1].strip()


def nix_log(drv: str, *, cwd: str | Path | None = None, timeout: float = 30) -> str | None:
    """Best-effort ``nix log <drv>``; returns None when unavailable."""
    try:
        res = subprocess.run(
            ["nix", "--extra-experimental-features", "nix-command flakes fetch-tree", "log", drv],
            cwd=str(cwd) if cwd is not None else None,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if res.returncode != 0:
        return None
    return res.stdout


def data_path(name: str) -> Path:
    """Filesystem path of a file under src/uvloom_cli/data/."""
    return Path(str(resources.files(__package__) / "data" / name))


def hammer_store_path(*, timeout: float = 30) -> str | None:
    """Best-effort store path of the pinned uv2nix_hammer_overrides checkout.

    Called only from failure paths (cold, already failing) to enable
    near-miss hints. Evaluates the pin's fetchTree expression — when the
    build ran with hammer overlays the source is already in the store, so
    this is a fast local eval. Any problem returns None (silent, behavior
    unchanged) — except malformed pin fields, which raise CliError: they
    would otherwise be interpolated into a nix --expr.
    """
    import json

    try:
        pins = json.loads(
            (resources.files(__package__) / "data" / "pins.json").read_text()
        )
        pin = pins["uv2nix_hammer_overrides"]
        fields = {k: pin[k] for k in ("owner", "repo", "rev", "narHash")}
    except (OSError, ValueError, KeyError, TypeError):
        return None
    # The fields land verbatim inside a nix --expr: reject anything that
    # could escape its string literal (corrupted pins.json).
    for key, pattern in (
        ("owner", r"[A-Za-z0-9._-]+"),
        ("repo", r"[A-Za-z0-9._-]+"),
        ("rev", r"[0-9a-fA-F]{40}"),
        ("narHash", r"sha256-[A-Za-z0-9+/=]+"),
    ):
        value = fields[key]
        if not isinstance(value, str) or re.fullmatch(pattern, value) is None:
            raise CliError(
                f"vendored pins.json has a malformed uv2nix_hammer_overrides {key}"
            )
    try:
        expr = (
            '(builtins.fetchTree { type = "github"; '
            f'owner = "{fields["owner"]}"; repo = "{fields["repo"]}"; '
            f'rev = "{fields["rev"]}"; narHash = "{fields["narHash"]}"; }}).outPath'
        )
        res = subprocess.run(
            [
                "nix",
                "--extra-experimental-features",
                "nix-command flakes fetch-tree",
                "eval",
                "--raw",
                "--expr",
                expr,
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if res.returncode != 0:
        return None
    path = res.stdout.strip()
    if path.startswith("/nix/store/") and os.path.isdir(path):
        return path
    return None


def uvloom_lib_path() -> Path:
    """Path of the uvloom Nix library (directory containing default.nix).

    The packaged CLI wrapper sets UVLOOM_LIB to the embedded lib/; in a repo
    checkout we walk up from this file to find a sibling lib/default.nix.
    """
    env = os.environ.get("UVLOOM_LIB")
    if env:
        p = Path(env)
        if (p / "default.nix").is_file():
            return p
        raise CliError(f"UVLOOM_LIB={env} does not contain a default.nix")
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "lib"
        # scope.nix is uvloom-specific; default.nix alone would false-positive
        # on any unrelated ancestor repo with a lib/ directory.
        if (candidate / "default.nix").is_file() and (candidate / "scope.nix").is_file():
            return candidate
    raise CliError("cannot locate the uvloom Nix library (set UVLOOM_LIB)")


def uv_binary() -> str:
    """Path of the uv binary (UVLOOM_UV env, else PATH)."""
    env = os.environ.get("UVLOOM_UV")
    if env:
        return env
    found = shutil.which("uv")
    if found:
        return found
    raise CliError("no 'uv' binary found — install uv or set UVLOOM_UV")
