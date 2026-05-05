{
  lib,
  pyproject-nix,
  pyproject-build-systems,
}:

let
  errors = import ./errors.nix { };

  pythonSetLib = import ./python-set.nix {
    inherit lib pyproject-nix pyproject-build-systems;
  };

  packageLib = import ./packages.nix {
    inherit lib;
    fail = errors.fail;
  };

  makeScope =
    {
      workspace,
      pkgs,
      interpreter ? null,
      sourcePreference ? "wheel",
      dependencies ? workspace.deps.default,
      overlays ? [ ],
      environ ? { },
      stdenv ? pkgs.stdenv,
    }:
    let
      candidates = packageLib.localNames workspace;

      pythonSetCore = pythonSetLib.build {
        where = "forPython";
        inherit
          pkgs
          interpreter
          sourcePreference
          overlays
          environ
          stdenv
          ;
        requiresPythonSource = workspace;
        mkOverlay =
          { sourcePreference, environ }:
          workspace.mkPyprojectOverlay {
            inherit sourcePreference dependencies environ;
          };
      };

      inherit (pythonSetCore) checkedOverlays resolvedInterpreter pythonSet;

      normalizeEditable =
        where: editable:
        if editable == false then
          null
        else if builtins.isAttrs editable then
          (
            {
              root = if editable ? root then editable.root else errors.fail where "editable.root is required";
            }
            // lib.optionalAttrs (editable ? members) {
              members = editable.members;
            }
          )
        else
          errors.fail where "editable must be false or an attribute set";

      mkEditablePythonSet =
        where: editable:
        let
          editableConfig = normalizeEditable where editable;
          checkedRoot =
            if builtins.isString editableConfig.root then
              editableConfig.root
            else
              errors.fail where "editable.root must be a string";
        in
        pythonSet.overrideScope (
          workspace.mkEditablePyprojectOverlay (
            {
              root = checkedRoot;
            }
            // lib.optionalAttrs (editableConfig ? members) {
              members = editableConfig.members;
            }
          )
        );

      mkVenv =
        {
          name,
          dependencies ? workspace.deps.default,
          editable ? false,
        }:
        let
          venvPythonSet = if editable == false then pythonSet else mkEditablePythonSet "mkVenv" editable;
        in
        venvPythonSet.mkVirtualEnv name dependencies;

      hacks = pkgs.callPackage pyproject-nix.build.hacks { };

      mkPythonPackagesExtension =
        {
          packages ? candidates,
        }:
        hacks.toNixpkgs {
          inherit pythonSet packages;
        };

      mkNixpkgsPackage =
        {
          package ? null,
          exportPackages ? null,
        }:
        let
          packageName = packageLib.resolveLocalPackage "nixpkgs.package" candidates pythonSet package;
          pythonPackagesExtension = mkPythonPackagesExtension {
            packages = if exportPackages == null then [ packageName ] else exportPackages;
          };
          python = resolvedInterpreter.override (old: {
            self = python;
            packageOverrides = lib.composeExtensions (old.packageOverrides or (_: _: { })
            ) pythonPackagesExtension;
          });
        in
        python.pkgs.${packageName};

      mkApplication =
        {
          package ? null,
          venv ? null,
          pname ? null,
          version ? null,
        }:
        let
          packageName = packageLib.resolveLocalPackage "mkApplication" candidates pythonSet package;
        in
        (pkgs.callPackage pyproject-nix.build.util { }).mkApplication (
          {
            venv = if venv == null then mkVenv { name = "${packageName}-env"; } else venv;
            package = pythonSet.${packageName};
          }
          // lib.optionalAttrs (pname != null) { inherit pname; }
          // lib.optionalAttrs (version != null) { inherit version; }
        );

      mkPytestCheck =
        {
          package ? null,
          groups ? [ "test" ],
          dependencies ? null,
          name ? null,
          paths ? [ "tests" ],
          pytestFlags ? [ ],
          env ? { },
          nativeBuildInputs ? [ ],
        }:
        let
          packageName = packageLib.requireLocalPackage "mkPytestCheck" candidates (
            packageLib.inferLocalPackage "mkPytestCheck" candidates package
          );
          testDependencies = if dependencies == null then { ${packageName} = groups; } else dependencies;
          testScope = makeScope {
            inherit
              workspace
              pkgs
              sourcePreference
              environ
              stdenv
              ;
            interpreter = resolvedInterpreter;
            dependencies = testDependencies;
            overlays = checkedOverlays;
          };
          resolvedPackageName =
            packageLib.requirePythonSetPackage "mkPytestCheck" candidates testScope.pythonSet
              packageName;
          pytestVenv = testScope.mkVenv {
            name = "${resolvedPackageName}-pytest-env";
            dependencies = testDependencies;
          };
        in
        stdenv.mkDerivation {
          name = if name == null then "${resolvedPackageName}-pytest" else name;
          inherit env;
          src = testScope.pythonSet.${resolvedPackageName}.src;
          nativeBuildInputs = [ pytestVenv ] ++ nativeBuildInputs;
          dontConfigure = true;
          buildPhase = ''
            runHook preBuild
            pytest ${lib.escapeShellArgs paths} ${lib.escapeShellArgs pytestFlags}
            runHook postBuild
          '';
          installPhase = ''
            touch $out
          '';
        };
    in
    {
      inherit
        pythonSet
        mkVenv
        mkApplication
        mkPytestCheck
        ;

      interpreter = resolvedInterpreter;

      nixpkgs = {
        package = mkNixpkgsPackage;
      };
    };
in
makeScope
