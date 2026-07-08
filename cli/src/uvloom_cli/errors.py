class CliError(Exception):
    """User-facing error. main() prints 'uvloom: {msg}' to stderr and exits 1. Message is one sentence, no trace."""


def execvpe(cmd: list[str], env: dict[str, str]) -> None:
    """os.execvpe with exec failures surfaced as one-line CLI errors."""
    import os

    try:
        os.execvpe(cmd[0], cmd, env)
    except OSError as exc:
        raise CliError(f"cannot exec '{cmd[0]}': {exc.strerror or exc}") from None
