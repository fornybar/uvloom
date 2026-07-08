# Standalone (flakeless) build of the uvloom CLI, and the single source of
# the wrapper recipe. `import ./cli { }` builds everything from the static
# pins; the flake (nix/packages) calls this with its own pkgs and app so the
# wrapper is not duplicated there.
let
  pins = import ./src/uvloom_cli/data/pins.nix;
in
{
  pkgs ? import pins.nixpkgs { },
  uvloomLib ? import ../lib {
    inherit (pkgs) lib;
    inherit (pins) uv2nix pyproject-nix pyproject-build-systems;
  },
  app ?
    let
      project = uvloomLib.project.load {
        root = ./.;
        filterSource = true;
      };
      scope = project.forPython { inherit pkgs; };
    in
    scope.app {
      package = "uvloom-cli";
      script = "uvloom";
    },
  uv ? pins.uvPackage pkgs,
}:
pkgs.runCommand "uvloom-cli-${app.version}"
  {
    pname = app.pname;
    version = app.version;
    meta = app.meta // {
      homepage = "https://github.com/fornybar/uvloom";
      license = pkgs.lib.licenses.mit;
      platforms = pkgs.lib.platforms.unix;
      mainProgram = "uvloom";
    };
    passthru = app.passthru or { };
    nativeBuildInputs = [ pkgs.makeWrapper ];
  }
  ''
    mkdir -p "$out/bin"
    makeWrapper ${app}/bin/uvloom "$out/bin/uvloom" \
      --set UVLOOM_LIB ${../lib} \
      --set UVLOOM_UV ${uv}/bin/uv \
      --suffix PATH : ${pkgs.lib.makeBinPath [ uv ]}
  ''
