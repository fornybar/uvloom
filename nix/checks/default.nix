{
  lib,
  pkgs,
  self,
  system,
  uvloom,
  nixpkgs,
  uvloomInput,
  pyproject-nix,
  templateDirs,
}:
let
  evalTest = import ../../test/eval.nix {
    inherit pkgs uvloom pyproject-nix;
  };

  negativeTest = import ../../test/negative.nix {
    inherit pkgs uvloom pyproject-nix;
  };

  buildChecks = import ../../test/builds.nix {
    inherit pkgs uvloom;
  };

  templateFlakes =
    let
      callTemplate =
        template:
        let
          flakeFile = import (../../templates + "/${template}/flake.nix");
          flake = flakeFile.outputs args;
          args = builtins.mapAttrs (name: _: inputs'.${name}) (builtins.functionArgs flakeFile.outputs);
          inputs' = {
            self = flake;
            inherit nixpkgs;
            uvloom = uvloomInput;
          };
        in
        flake;

      mkCheck = template: prefix: check: drv: {
        name = "template-${template}-${prefix}-${check}";
        value = drv;
      };

      mkTemplateChecks =
        template:
        let
          flake = callTemplate template;
          checksFor =
            prefix: attr: lib.mapAttrsToList (mkCheck template prefix) (flake.${attr}.${system} or { });
        in
        checksFor "package" "packages" ++ checksFor "check" "checks" ++ checksFor "devShell" "devShells";
    in
    lib.pipe templateDirs [
      (lib.concatMap mkTemplateChecks)
      builtins.listToAttrs
    ];
in
buildChecks
// templateFlakes
// {
  docs = self.packages.${system}.docs;

  # Cover the CLI package in `nix flake check`: --no-build evals the
  # derivation, a full check builds it.
  uvloom-cli = self.packages.${system}.uvloom-cli;

  eval = pkgs.runCommand "uvloom-eval" { } ''
    ${if evalTest then "touch $out" else "false"}
  '';

  negative = pkgs.runCommand "uvloom-negative" { } ''
    ${if negativeTest then "touch $out" else "false"}
  '';
}
