{
  description = "Example target: simplified uv2nix API";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-25.11";

    # Wrapper owns uv2nix + pyproject.nix + build-system-pkgs wiring.
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

      # Load project once.
      # In real project this would usually be `./.`.
      project = uvloom.lib.loadProject {
        root = ../.;
      };

      # System-specific Python scope.
      # Final API goals:
      # - user still controls flake architecture
      # - wrapper hides uv2nix composition boilerplate
      # - `dependencies` stays close to uv2nix shape
      # - scope-level deps pick package set
      # - env-level deps pick install set
      # - curated low-level object remains available as `scope.pythonSet`
      # - interpreter may be explicit or inferred from workspace requires-python
      scope = project.forPython {
        inherit pkgs;
        interpreter = pkgs.python312;
        sourcePreference = "wheel";

        overlays = [
          (final: prev: {
            meshpy = prev.meshpy.overrideAttrs (old: {
              buildInputs = (old.buildInputs or [ ]) ++ [ pkgs.stdenv.cc.cc.lib ];
            });
          })
        ];
      };

      # No `scope.editablePythonSet` / `scope.mkEditableVenv` here.
      # Final v1 exposes editable-only attrs only when `editable = { ... };` is present.
      venv = scope.mkVenv {
        name = "smiley-plot-env";
      };

      application = scope.mkApplication {
        inherit venv;
        package = "smiley-plot";
      };
    in
    {
      # Flake structure still plain Nix. No mkFlake / forAllSystems abstraction.
      devShells.${system}.default = pkgs.mkShell {
        packages = [
          venv
          pkgs.just
          pkgs.eza
        ];
      };

      packages.${system} = {
        default = application;
        inherit venv;
      };
    };
}
