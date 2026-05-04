{
  description = "Example target: editable development shell with simplified uv2nix API";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-25.11";

    uvloom = {
      url = "github:fornybar/uvloom";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs =
    {
      self,
      nixpkgs,
      uvloom,
      ...
    }:
    let
      system = "x86_64-linux";
      pkgs = import nixpkgs { inherit system; };

      project = uvloom.lib.loadProject {
        root = ../.;
      };

      scope = project.forPython {
        inherit pkgs;
        interpreter = pkgs.python312;
        sourcePreference = "wheel";

        # Editable config must support non-store roots.
        # Also needs subset selection for multi-member workspaces.
        editable = {
          root = "$REPO_ROOT";
          members = [ "smiley-plot" ];
        };

        overlays = [
          (final: prev: {
            # Example package-level source filtering or manual overrides.
            # Important: filtering belongs on package src, not workspace root.
            smiley-plot = prev.smiley-plot.overrideAttrs (old: {
              src = old.src;
            });
          })
        ];
      };

      devVenv = scope.mkEditableVenv {
        name = "smiley-plot-dev-env";
      };
    in
    {
      devShells.${system}.default = pkgs.mkShell {
        packages = [
          devVenv
          pkgs.uv
        ];

        env = {
          UV_NO_SYNC = "1";
          UV_PYTHON = scope.editablePythonSet.python.interpreter;
          UV_PYTHON_DOWNLOADS = "never";
        };

        shellHook = ''
          unset PYTHONPATH
          export REPO_ROOT=$(git rev-parse --show-toplevel)
        '';
      };

      # Advanced editable build systems still need low-level access.
      # Example future extension:
      # packages = [
      #   devVenv
      #   pkgs.uv
      #   pyproject-nix.packages.${system}.build-editable
      # Add pyproject-nix as an explicit flake input when needed.
      # ];
      # shellHook = ''
      #   unset PYTHONPATH
      #   export REPO_ROOT=$(git rev-parse --show-toplevel)
      #   build-editable
      # '';
    };
}
