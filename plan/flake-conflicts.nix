{
  description = "Example target: conflicting dependency selections with simplified uv2nix API";

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

      # Same workspace, two mutually exclusive dependency selections.
      # Example shape: CPU vs CUDA extras, or similar conflict groups.
      # Scope-level deps pick package set; env-level deps pick install set.
      cpuScope = project.forPython {
        inherit pkgs;
        interpreter = pkgs.python312;
        sourcePreference = "wheel";

        dependencies = {
          my-app = [ "cpu" ];
        };
      };

      cudaScope = project.forPython {
        inherit pkgs;
        interpreter = pkgs.python312;
        sourcePreference = "wheel";
        dependencies = {
          my-app = [ "cuda" ];
        };
      };

      cpuVenv = cpuScope.mkVenv {
        name = "my-app-cpu-env";

        # Env-level install dependency selection uses same uv2nix-native schema.
        dependencies = {
          my-app = [ "cpu" ];
        };
      };

      cudaVenv = cudaScope.mkVenv {
        name = "my-app-cuda-env";
        dependencies = {
          my-app = [ "cuda" ];
        };
      };
    in
    {
      packages.${system} = {
        cpu = cpuScope.mkApplication {
          venv = cpuVenv;
          package = "my-app";
        };

        cuda = cudaScope.mkApplication {
          venv = cudaVenv;
          package = "my-app";
        };
      };
    };
}
