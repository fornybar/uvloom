{
  lib,
  pep440,
  fail,
  show,
}:

let
  matchesPython =
    constraints: python:
    let
      version = pep440.parseVersion python.pythonVersion;
    in
    lib.all (constraint: pep440.comparators.${constraint.op} version constraint.version) constraints;
in
{
  choose =
    pkgs: workspace:
    let
      requires = workspace.requires-python or [ ];
      shownRequires = show (workspace.requires-python or null);
      pythonNames = [
        "python314"
        "python313"
        "python312"
        "python311"
        "python310"
        "python39"
        "python38"
      ];
      candidates = lib.pipe pythonNames [
        (builtins.filter (name: pkgs ? ${name}))
        (map (name: pkgs.${name}))
        (builtins.filter (python: matchesPython requires python))
      ];
    in
    if candidates == [ ] then
      fail "forPython" "could not infer interpreter for requires-python ${shownRequires}; pass interpreter explicitly"
    else
      builtins.head candidates;
}
