{
  description = "uvloom complex package example";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

    uvloom = {
      url = "github:fornybar/uvloom";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs =
    {
      nixpkgs,
      uvloom,
      ...
    }:
    let
      system = "x86_64-linux";
      pkgs = nixpkgs.legacyPackages.${system};

      project = uvloom.lib.project.load { root = ./.; };

      # For dependencies not in the PyPI or uv.lock metadata
      overlay = final: prev: {
        meshpy = prev.meshpy.overrideAttrs (old: {
          buildInputs = (old.buildInputs or [ ]) ++ [ pkgs.stdenv.cc.cc.lib ];
        });
      };

      scope = project.forPython {
        inherit pkgs;
        interpreter = pkgs.python312;
        overlays = [ overlay ];
      };

      venv = scope.venv {
        name = "smiley-plot-dev-env";
        editable = {
          members = [ "smiley-plot" ];
        };
      };
    in
    {
      packages.${system}.default = scope.app { package = "smiley-plot"; };

      devShells.${system}.default = pkgs.mkShell {
        packages = [
          venv
          pkgs.uv
        ];
        shellHook = scope.hook;
      };
    };
}
