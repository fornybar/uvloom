{
  description = "uvloom editable development template";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    uvloom.url = "github:fornybar/uvloom";
    uvloom.inputs.nixpkgs.follows = "nixpkgs";
  };

  outputs =
    { nixpkgs, uvloom, ... }:
    let
      systems = [
        "x86_64-linux"
        "aarch64-linux"
        "x86_64-darwin"
        "aarch64-darwin"
      ];
      forAllSystems = nixpkgs.lib.genAttrs systems;
      project = uvloom.lib.loadProject { root = ./.; };
    in
    {
      devShells = forAllSystems (
        system:
        let
          pkgs = nixpkgs.legacyPackages.${system};
          scope = project.forPython {
            inherit pkgs;
            interpreter = pkgs.python312;
          };
        in
        {
          default = pkgs.mkShell {
            packages = [
              (scope.mkVenv {
                name = "smiley-plot-dev-env";
                editable = {
                  root = "$PWD";
                  members = [ "smiley-plot" ];
                };
              })
              pkgs.uv
            ];

            env = {
              UV_NO_SYNC = "1";
              UV_PYTHON = pkgs.lib.getExe scope.interpreter;
              UV_PYTHON_DOWNLOADS = "never";
            };

            shellHook = ''
              unset PYTHONPATH
            '';
          };
        }
      );
    };
}
