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
            editable = {
              root = "$PWD";
              members = [ "smiley-plot" ];
            };
          };
        in
        {
          default = pkgs.mkShell {
            packages = [
              (scope.mkEditableVenv { name = "smiley-plot-dev-env"; })
              pkgs.uv
            ];

            env = {
              UV_PYTHON = pkgs.lib.getExe scope.interpreter;
              UV_PYTHON_DOWNLOADS = "never";
            };
          };
        }
      );
    };
}
