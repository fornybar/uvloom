{
  description = "uvloom: thin wrapper around uv2nix";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

    pyproject-nix = {
      url = "github:pyproject-nix/pyproject.nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };

    uv2nix = {
      url = "github:pyproject-nix/uv2nix";
      inputs.nixpkgs.follows = "nixpkgs";
      inputs.pyproject-nix.follows = "pyproject-nix";
    };

    pyproject-build-systems = {
      url = "github:pyproject-nix/build-system-pkgs";
      inputs.nixpkgs.follows = "nixpkgs";
      inputs.pyproject-nix.follows = "pyproject-nix";
      inputs.uv2nix.follows = "uv2nix";
    };
  };

  outputs =
    {
      self,
      nixpkgs,
      pyproject-nix,
      uv2nix,
      pyproject-build-systems,
      ...
    }:
    let
      lib = nixpkgs.lib;

      uvloom = {
        lib = import ./lib {
          inherit lib;
          inherit
            uv2nix
            pyproject-nix
            pyproject-build-systems
            ;
        };
      };

      systems = import ./nix/systems.nix { inherit lib; };
      templates = import ./nix/templates { inherit lib; };

      inherit (systems) forAllSystems;
    in
    {
      inherit (uvloom) lib;

      templates = templates.flakeTemplates;

      packages = forAllSystems (
        system:
        import ./nix/packages {
          inherit lib uvloom;
          pkgs = nixpkgs.legacyPackages.${system};
          templateDirs = templates.dirs;
        }
      );

      devShells = forAllSystems (
        system:
        import ./nix/devshells {
          inherit self system;
          pkgs = nixpkgs.legacyPackages.${system};
        }
      );

      checks = forAllSystems (
        system:
        import ./nix/checks {
          inherit
            lib
            self
            system
            uvloom
            nixpkgs
            pyproject-nix
            ;
          pkgs = nixpkgs.legacyPackages.${system};
          uvloomInput = uvloom;
          templateDirs = templates.dirs;
        }
      );

      formatter = forAllSystems (
        system:
        import ./nix/formatter.nix {
          pkgs = nixpkgs.legacyPackages.${system};
        }
      );
    };
}
