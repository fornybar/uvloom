"""uvloom entry point: argv dispatch.

Hot-path discipline: the only top-level import is sys; every
command module — and even errors.py — is imported lazily inside its branch.
No argparse anywhere on the dispatch path.
"""

import sys

_PASSTHROUGH = frozenset(
    {"lock", "add", "remove", "tree", "export", "init", "build", "version"}
)
_ENVIRONMENT = frozenset({"sync", "run", "venv", "check"})

# Known uv commands we deliberately do not support.
_UNSUPPORTED = {
    "pip": "'uv pip' mutates environments imperatively, which conflicts with store-built venvs — call uv directly at your own risk.",
    "tool": "'uv tool' mutates environments imperatively, which conflicts with store-built venvs — call uv directly at your own risk.",
    "uvx": "'uvx' mutates environments imperatively, which conflicts with store-built venvs — call uv directly at your own risk.",
    "publish": "'uv publish' has no Nix interaction — call uv directly.",
    "self": "'uv self' has no Nix interaction — call uv directly.",
    "python": "Nix provides the interpreter — use a .python-version file instead of 'uv python'.",
}

_USAGE = """\
uvloom — the uv workflow with Nix guarantees

usage: uvloom <command> [args...]

pass-through commands (exec the pinned uv binary, environment untouched):
  lock          update uv.lock
  add           add a dependency (then run 'uvloom sync')
  remove        remove a dependency (then run 'uvloom sync')
  tree          show the dependency tree
  export        export the lockfile
  init          create a new project
  build         build source/wheel distributions
  version       show or set the project version (uv's version command)

environment commands (built with Nix; uv never touches .venv):
  sync          build the project venv as a store symlink at .venv
  run           ensure the venv is current, then exec a command inside it
  venv          build the venv and print its store path
  check         build and run the project's pytest suite

other commands:
  flakify       write a flake.nix so the project graduates to plain Nix

options:
  -h, --help    show this help

notes:
  there is no 'uvloom --version'; 'uvloom version' passes through to uv
  (the project version). unsupported uv commands (pip, tool, uvx, publish,
  self, python) explain themselves when invoked.
"""

_COMMAND_HELP = {
    "sync": """usage: uvloom sync [options]

Build project .venv with Nix.

options:
  --group <name>       include dependency group (repeatable)
  --extra <name>       include optional extra (repeatable)
  --all-groups         include every dependency group, not extras
  --no-editable        build non-editable local packages
  --include <path>     copy extra source path into filtered source (repeatable)
  --no-filter-source   copy whole project source instead of filtered source
  --no-hammer          disable bundled build overrides
  --force              rebuild even when environment is current
  -v, --verbose        stream Nix build output
  -q, --quiet          suppress sync status
  -h, --help           show this help
""",
    "run": """usage: uvloom run [options] [--] <command> [args...]

Build or reuse project .venv, then run command inside it.

Options match `uvloom sync`: --group, --extra, --all-groups,
--no-editable, --include, --no-filter-source, --no-hammer, --force,
-v/--verbose, -q/--quiet.
`-m`/`--module` starts Python module command.
Use `uvloom run --help` to show this help.
""",
    "venv": """usage: uvloom venv [options]

Build project .venv and print its store path.

Options match `uvloom sync`: --group, --extra, --all-groups,
--no-editable, --include, --no-filter-source, --no-hammer, --force,
-v/--verbose, -q/--quiet.
Use `uvloom venv --help` to show this help.
""",
    "check": """usage: uvloom check [options] [-- pytest-args...]

Run pytest as hermetic Nix build.

options:
  --group <name>       select dependency group (repeatable)
  --paths <path>       test path to copy and run (repeatable)
  --include <path>     copy extra source path without collecting it
  --no-filter-source   copy whole project source instead of filtered source
  --no-hammer          disable bundled build overrides
  -v, --verbose        stream Nix build output
  -h, --help           show this help
""",
    "flakify": """usage: uvloom flakify [--no-hammer]

Write a flake.nix for current uv project. Creates uv.lock first if missing.

options:
  --no-hammer          omit bundled build overrides
  -h, --help           show this help
""",
}


def main() -> None:
    argv = sys.argv[1:]
    if not argv:
        print(_USAGE, end="", file=sys.stderr)
        raise SystemExit(1)
    if argv[0] in ("-h", "--help"):
        print(_USAGE, end="")
        raise SystemExit(0)

    cmd, rest = argv[0], argv[1:]

    # Native command help must be side-effect free: no project discovery,
    # lock bootstrap, Nix evaluation, or imports of command implementations.
    if cmd in _COMMAND_HELP and rest in (["-h"], ["--help"]):
        print(_COMMAND_HELP[cmd], end="")
        raise SystemExit(0)

    from .errors import CliError

    try:
        if cmd in _PASSTHROUGH:
            from .passthrough import run_passthrough

            run_passthrough(cmd, rest)  # execs or sys.exit()s
        elif cmd in _ENVIRONMENT:
            if cmd == "sync":
                from .commands import cmd_sync

                raise SystemExit(cmd_sync(rest))
            if cmd == "run":
                from .commands import cmd_run

                raise SystemExit(cmd_run(rest))
            if cmd == "venv":
                from .commands import cmd_venv

                raise SystemExit(cmd_venv(rest))
            from .commands import cmd_check

            raise SystemExit(cmd_check(rest))
        elif cmd == "flakify":
            from .flakify import cmd_flakify

            raise SystemExit(cmd_flakify(rest))
        elif cmd in _UNSUPPORTED:
            raise CliError(_UNSUPPORTED[cmd])
        else:
            raise CliError(
                f"unknown command '{cmd}' — supported: "
                "lock, add, remove, tree, export, init, build, version, "
                "sync, run, venv, check, flakify (see 'uvloom --help')."
            )
    except KeyboardInterrupt:
        raise SystemExit(130) from None  # 128 + SIGINT, shell convention
    except CliError as exc:
        print(f"uvloom: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
    except OSError as exc:
        # Filesystem surprises (e.g. a plain-file .venv, EPERM on a sidecar)
        # are environment problems, not bugs: one line, no traceback — same
        # 'uvloom: ' prefix as CliError.
        raise SystemExit(f"uvloom: {exc}") from None


if __name__ == "__main__":
    main()
