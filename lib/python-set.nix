{
  lib,
  pyproject-nix,
  pyproject-build-systems,
}:

let
  errors = import ./errors.nix { };

  pythonInterpreters = import ./interpreter.nix {
    inherit lib pyproject-nix;
    fail = errors.fail;
    show = errors.show;
  };

  overlayNames = builtins.attrNames pyproject-build-systems.overlays;
in
{
  build =
    {
      where,
      pkgs,
      interpreter ? null,
      requiresPythonSource,
      sourcePreference,
      overlays ? [ ],
      environ ? { },
      stdenv ? pkgs.stdenv,
      forgeFetchOverlay ? null,
      fetchOverlays ? [ ],
      mkOverlay,
    }:
    let
      checkedOverlays =
        if builtins.isList overlays then overlays else errors.fail where "overlays must be a list";

      resolvedInterpreter =
        if interpreter == null then pythonInterpreters.choose pkgs requiresPythonSource else interpreter;

      buildOverlay =
        pyproject-build-systems.overlays.${sourcePreference}
          or (errors.fail where "unknown sourcePreference ${sourcePreference}; available: ${lib.concatStringsSep ", " overlayNames}");

      baseSet = pkgs.callPackage pyproject-nix.build.packages {
        python = resolvedInterpreter;
        inherit stdenv;
      };

      generatedOverlay = mkOverlay {
        inherit sourcePreference environ;
      };

      pythonSet = baseSet.overrideScope (
        lib.composeManyExtensions (
          [
            buildOverlay
            generatedOverlay
          ]
          ++ lib.optional (forgeFetchOverlay != null) forgeFetchOverlay
          ++ fetchOverlays
          ++ checkedOverlays
        )
      );
    in
    {
      inherit
        checkedOverlays
        resolvedInterpreter
        pythonSet
        ;
    };
}
