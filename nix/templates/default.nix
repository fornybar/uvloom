{
  lib,
  root ? ../templates,
}:
let
  dirs = lib.pipe (builtins.readDir root) [
    (lib.filterAttrs (_: type: type == "directory"))
    lib.attrNames
  ];
in
{
  inherit dirs;

  flakeTemplates = lib.listToAttrs (
    map (
      dir:
      let
        path = root + "/${dir}";
        template = import (path + "/flake.nix");
      in
      lib.nameValuePair dir {
        inherit path;
        inherit (template) description;
      }
    ) dirs
  );
}
