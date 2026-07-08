"""Native command help must not inspect a project or invoke Nix."""

import sys

import pytest

from uvloom_cli.main import main


@pytest.mark.parametrize("command", ["sync", "run", "venv", "check", "flakify"])
@pytest.mark.parametrize("flag", ["-h", "--help"])
def test_native_command_help_is_side_effect_free(monkeypatch, capsys, command, flag):
    monkeypatch.setattr(sys, "argv", ["uvloom", command, flag])
    with pytest.raises(SystemExit) as exit_:
        main()
    assert exit_.value.code == 0
    out = capsys.readouterr().out
    assert out.startswith(f"usage: uvloom {command}")
    assert "help" in out
