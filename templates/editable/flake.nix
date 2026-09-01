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
        "aarch64-darwin"
      ];
      forAllSystems = nixpkgs.lib.genAttrs systems;
      project = uvloom.lib.project.load { root = ./.; };
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
              (scope.venv {
                name = "smiley-plot-dev-env";
                editable = {
                  members = [ "smiley-plot" ];
                };
              })
              pkgs.uv
            ];

            shellHook = scope.hook;
          };
        }
      );
    };
}
