{
  lib,
  pyproject-nix,
  fail,
  show,
}:

{
  choose =
    pkgs: workspace:
    let
      requires-python = workspace.requires-python or [ ];
      shownRequires = show (workspace.requires-python or null);
      candidates = pyproject-nix.lib.util.filterPythonInterpreters {
        inherit requires-python;
        inherit (pkgs) pythonInterpreters;
      };
    in
    if candidates == [ ] then
      fail "forPython" "could not infer interpreter for requires-python ${shownRequires}; pass interpreter explicitly"
    else
      lib.last candidates;
}
