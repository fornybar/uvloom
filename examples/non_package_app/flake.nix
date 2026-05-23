{
  description = "uvloom non-package app example";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

    uvloom = {
      url = "path:../..";
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
      scope = project.forPython {
        inherit pkgs;
        interpreter = pkgs.python312;
      };
    in
    {
      packages.${system}.default = scope.app {
        name = "non-package-app";
        command = [
          "python"
          ./app.py
        ];
        pythonPath = [ ./. ];
      };
    };
}
