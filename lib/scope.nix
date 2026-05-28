{
  lib,
  uv2nix,
  pyproject-nix,
  pyproject-build-systems,
}:

let
  errors = import ./errors.nix { };

  pythonSetLib = import ./python-set.nix {
    inherit lib pyproject-nix pyproject-build-systems;
  };

  forgeFetchLib = import ./forge-fetch {
    inherit lib pyproject-nix;
    fail = errors.fail;
  };

  packageLib = import ./packages.nix {
    inherit lib;
    fail = errors.fail;
  };

  venvDependencies = import ./venv-dependencies.nix {
    inherit lib uv2nix pyproject-nix;
    fail = errors.fail;
  };

  makeScope =
    {
      workspace,
      workspaceRoot ? null,
      uvLock ? null,
      pkgs,
      interpreter ? null,
      sourcePreference ? "wheel",
      dependencies ? workspace.deps.default,
      forgeFetch ? null,
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
        forgeFetchOverlay = forgeFetchLib.mkOverlay {
          root = workspaceRoot;
          config = forgeFetch;
        };
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
          venvPythonSet = if editable == false then pythonSet else mkEditablePythonSet "venv" editable;
          resolvedDependencies = venvDependencies.resolve {
            inherit dependencies uvLock environ;
            interpreter = resolvedInterpreter;
          };
        in
        venvPythonSet.mkVirtualEnv name resolvedDependencies;

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
          name ? pname,
          command ? null,
          pythonPath ? [ ],
          workingDirectory ? workspaceRoot,
        }:
        if command != null then
          if package != null then
            errors.fail "app" "pass either `package` or `command`, not both"
          else if builtins.isString command then
            errors.fail "app" "`command` must be a list, not a shell string"
          else if !builtins.isList command then
            errors.fail "app" "`command` must be a non-empty list of strings or paths"
          else if command == [ ] then
            errors.fail "app" "`command` must be a non-empty list of strings or paths"
          else if !(builtins.all (entry: builtins.isString entry || builtins.isPath entry) command) then
            errors.fail "app" "`command` must be a non-empty list of strings or paths"
          else if name == null then
            errors.fail "app" "`name` is required when using command mode"
          else if name == "" then
            errors.fail "app" "`name` must be non-empty when using command mode"
          else if !builtins.isList pythonPath then
            errors.fail "app" "`pythonPath` must be a list of strings or paths"
          else if !(builtins.all (entry: builtins.isString entry || builtins.isPath entry) pythonPath) then
            errors.fail "app" "`pythonPath` must be a list of strings or paths"
          else
            let
              commandVenv = if venv == null then mkVenv { name = "${name}-env"; } else venv;
              commandArgs = map (entry: if builtins.isPath entry then "${entry}" else toString entry) command;
              pythonPathEntries = map (
                entry: if builtins.isPath entry then "${entry}" else toString entry
              ) pythonPath;
              resolvedWorkingDirectory =
                if workingDirectory == null then
                  null
                else if builtins.isPath workingDirectory then
                  "${workingDirectory}"
                else
                  toString workingDirectory;
            in
            pkgs.writeShellApplication {
              inherit name;
              runtimeInputs = [ commandVenv ];
              text = lib.concatStringsSep "\n" (
                (lib.optional (
                  resolvedWorkingDirectory != null
                ) "cd ${lib.escapeShellArg resolvedWorkingDirectory}")
                ++ (lib.optional (pythonPath != [ ]) ''
                  export PYTHONPATH=${lib.escapeShellArg (lib.concatStringsSep ":" pythonPathEntries)}''${PYTHONPATH:+:}''${PYTHONPATH:-}
                '')
                ++ [
                  ''
                    exec ${lib.escapeShellArgs commandArgs} "$@"
                  ''
                ]
              );
            }
        else
          let
            packageName = packageLib.resolveLocalPackage "app" candidates pythonSet package;
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
          packageName = packageLib.requireLocalPackage "check.pytest" candidates (
            packageLib.inferLocalPackage "check.pytest" candidates package
          );
          testDependencies = if dependencies == null then { ${packageName} = groups; } else dependencies;
          testScope = makeScope {
            inherit
              workspace
              workspaceRoot
              pkgs
              sourcePreference
              forgeFetch
              environ
              stdenv
              ;
            interpreter = resolvedInterpreter;
            dependencies = testDependencies;
            overlays = checkedOverlays;
          };
          resolvedPackageName =
            packageLib.requirePythonSetPackage "check.pytest" candidates testScope.pythonSet
              packageName;
          pytestVenv = testScope.venv {
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
        ;

      venv = mkVenv;
      app = mkApplication;
      check = {
        pytest = mkPytestCheck;
      };

      interpreter = resolvedInterpreter;

      nixpkgs = {
        package = mkNixpkgsPackage;
      };
    };
in
makeScope
