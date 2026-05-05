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

      project = uvloom.lib.loadProject { root = ./.; };

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

      venv = scope.mkVenv {
        name = "smiley-plot-dev-env";
        editable = {
          root = "$PWD";
          members = [ "smiley-plot" ];
        };
      };
    in
    {
      packages.${system}.default = scope.mkApplication { package = "smiley-plot"; };

      devShells.${system}.default = pkgs.mkShell {
        packages = [
          venv
          pkgs.uv
        ];
        env = {
          UV_PYTHON = pkgs.lib.getExe scope.interpreter;
          UV_PYTHON_DOWNLOADS = "never";
        };
      };
    };
}
