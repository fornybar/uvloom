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
      editable ? null,
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

      checkedEditable =
        if editable == null || editable ? root && builtins.isString editable.root then
          editable
        else
          errors.fail "forPython" "editable.root must be a string";

      mkVenv =
        {
          name,
          dependencies ? workspace.deps.default,
        }:
        pythonSet.mkVirtualEnv name dependencies;

      editablePythonSet =
        if checkedEditable == null then
          null
        else
          pythonSet.overrideScope (
            workspace.mkEditablePyprojectOverlay (
              {
                root = checkedEditable.root;
              }
              // lib.optionalAttrs (checkedEditable ? members) {
                members = checkedEditable.members;
              }
            )
          );

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

      nixpkgs = {
        pythonPackagesExtension = mkPythonPackagesExtension;
        package = mkNixpkgsPackage;
      };
    }
    // lib.optionalAttrs (checkedEditable != null) {
      inherit editablePythonSet;

      mkEditableVenv =
        {
          name,
          dependencies ? workspace.deps.default,
        }:
        editablePythonSet.mkVirtualEnv name dependencies;
    };
in
makeScope
