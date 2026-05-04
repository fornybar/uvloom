{
  description = "Example target: pytest checks with simplified uv2nix API";

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
      };

      # Common case should be first-class: pytest check using named
      # dependency group from pyproject.toml. Helper derives a test scope
      # so groups are present at package-set creation time.
      pytest = scope.mkPytestCheck {
        # Omit package when workspace has exactly one local package.
        groups = [ "test" ];
      };

      # Low-level escape still available for custom cases through
      # `scope.pythonSet` + `scope.mkVenv`, but common path should be this helper.
    in
    {
      checks.${system} = {
        inherit pytest;
      };

      packages.${system}.default = scope.mkApplication {
        # Omit `venv` to use final v1 auto-venv behavior.
        package = "smiley-plot";
      };
    };
}
