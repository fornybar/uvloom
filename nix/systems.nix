{
  lib,
}:
let
  systems = [
    "x86_64-linux"
    "aarch64-linux"
    "aarch64-darwin"
  ];
in
{
  inherit systems;
  forAllSystems = lib.genAttrs systems;
}
