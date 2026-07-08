# Static pin loader for the uvloom CLI. Importable with a plain `import`
# (no arguments). All revisions live in ./pins.json — this file never
# changes on a pin bump; only pins.json is rewritten (see `just pins-update`).
#
# Fetching uses builtins.fetchTree with a narHash, so evaluation is pure and
# needs no experimental features beyond `fetch-tree` (nixrun.py passes
# `--option extra-experimental-features 'flakes fetch-tree'` explicitly).
#
# Flake inputs are resolved hermetically: flake-compat reads each pinned
# repo's own committed flake.lock and fetches those locked inputs via
# fetchTree, so no unpinned fetches happen at eval time. The hammer pin is
# the exception: we import its flake.nix directly and call outputs with our
# pinned nixpkgs lib plus inert stubs, so its upstream flake.lock is ignored.
#
# uv2nix_hammer_overrides (`hammer` below) exposes, per its flake.nix:
#   overrides              = pkgs: final: prev: ...   # version-matched, with fallback
#   overrides_debug        = pkgs: final: prev: ...   # same, traced
#   overrides_strict       = pkgs: final: prev: ...   # no fallback to older versions
#   overrides_strict_debug = pkgs: final: prev: ...
# The canonical way to obtain an overlay `final: prev:` is:
#   pins.hammer.overrides pkgs
let
  pins = builtins.fromJSON (builtins.readFile ./pins.json);

  fetch =
    name:
    builtins.fetchTree {
      type = "github";
      inherit (pins.${name})
        owner
        repo
        rev
        narHash
        ;
    };

  # (import flake-compat { src = ...; }) returns { outputs, defaultNix, shellNix }.
  # `.outputs` is the flake's outputs attrset merged with sourceInfo/inputs.
  flake-compat = import (fetch "flake-compat");

  loadFlake = name: (flake-compat { src = fetch name; }).outputs;

  nixpkgsSrc = fetch "nixpkgs";
  nixpkgs = import nixpkgsSrc { };

  loadHammer =
    let
      src = fetch "uv2nix_hammer_overrides";
      systems = builtins.toFile "uv2nix-hammer-empty-systems.nix" ''
        [ ]
      '';
      treefmt-nix = {
        lib.evalModule = _pkgs: _module: {
          config.build.wrapper = null;
        };
      };
      outputs = (import (src + "/flake.nix")).outputs {
        inherit nixpkgs systems treefmt-nix;
      };
    in
    builtins.intersectAttrs {
      overrides = null;
      overrides_debug = null;
      overrides_strict = null;
      overrides_strict_debug = null;
    } outputs;
in
{
  # Store path of the pinned nixpkgs source; `import pins.nixpkgs { }` works.
  nixpkgs = nixpkgsSrc.outPath;

  # Flake outputs attrsets:
  pyproject-nix = loadFlake "pyproject-nix"; # .lib, .build
  uv2nix = loadFlake "uv2nix"; # .lib
  pyproject-build-systems = loadFlake "pyproject-build-systems"; # .overlays.default
  hammer = loadHammer; # .overrides pkgs -> overlay

  # uv comes from the pinned nixpkgs above (uv 0.11.8 at the current pin,
  # well above the >=0.7 floor). Kept as a function so the driver has a
  # single knob if uv ever needs to be pinned independently of nixpkgs.
  uvPackage = pkgs: pkgs.uv;
}
