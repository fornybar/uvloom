{
  description = "uvloom marimo sandbox script example";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

    uvloom = {
      url = "github:fornybar/uvloom";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs =
    { nixpkgs, uvloom, ... }:
    let
      system = "x86_64-linux";
      pkgs = nixpkgs.legacyPackages.${system};

      script = uvloom.lib.inline.load { path = ./marimo_app.py; };

      scope = script.forPython {
        inherit pkgs;
        interpreter = pkgs.python312;
      };

      venv = scope.venv { };
    in
    {
      packages.${system} = {
        run-script = scope.app { name = "run-script"; };

        open-app = pkgs.writeShellApplication {
          name = "open-app";
          runtimeInputs = [ venv ];
          text = ''
            exec marimo run --no-sandbox ${./marimo_app.py} "$@"
          '';
        };
      };

      devShells.${system}.default = pkgs.mkShell {
        packages = [
          venv
          pkgs.uv
        ];

        shellHook = scope.hook;
      };
    };
}
