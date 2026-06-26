{
  description = "uvloom simple PEP 723 script example";

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

      script = uvloom.lib.inline.load { path = ./script.py; };

      scope = script.forPython {
        inherit pkgs;
        interpreter = pkgs.python312;
      };
    in
    {
      packages.${system}.default = scope.app { name = "simple-script"; };

      devShells.${system}.default = pkgs.mkShell {
        packages = [
          (scope.app.editable {
            name = "simple-script";
            path = "script.py";
          })
          pkgs.uv
        ];

        shellHook = scope.hook;
      };
    };
}
