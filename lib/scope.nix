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

  forgeFetchLib = import ./forge-fetch {
    inherit lib pyproject-nix;
    fail = errors.fail;
  };

  authenticatedIndexFetchLib = import ./authenticated-index-fetch.nix {
    inherit lib;
    fail = errors.fail;
  };

  packageLib = import ./packages.nix {
    inherit lib;
    fail = errors.fail;
  };

  makeScope =
    {
      workspace,
      workspaceRoot ? null,
      pkgs,
      interpreter ? null,
      sourcePreference ? "wheel",
      dependencies ? workspace.deps.default,
      forgeFetch ? null,
      fetcher ? "auto",
      overlays ? [ ],
      environ ? { },
      stdenv ? pkgs.stdenv,
      lock ? null,
      uvIndexes ? [ ],
      evaluatorFetch ? builtins.fetchurl,
    }:
    let
      scopeDependencies = dependencies;
      candidates = packageLib.localNames workspace;
      packagePkgs = authenticatedIndexFetchLib.pkgsForFetcher {
        where = "forPython";
        inherit
          fetcher
          pkgs
          lock
          uvIndexes
          evaluatorFetch
          ;
      };

      pythonSetCore = pythonSetLib.build {
        where = "forPython";
        inherit
          interpreter
          sourcePreference
          overlays
          environ
          stdenv
          ;
        pkgs = packagePkgs;
        requiresPythonSource = workspace;
        forgeFetchOverlay = forgeFetchLib.mkOverlay {
          root = workspaceRoot;
          config = forgeFetch;
        };
        mkOverlay =
          { sourcePreference, environ }:
          workspace.mkPyprojectOverlay {
            inherit sourcePreference environ;
            dependencies = scopeDependencies;
          };
      };

      inherit (pythonSetCore) checkedOverlays resolvedInterpreter pythonSet;

      normalizeEditable =
        where: editable:
        if editable == false then
          null
        else if editable == true then
          {
            root = "$REPO_ROOT";
          }
        else if builtins.isAttrs editable then
          (
            {
              root = if editable ? root then editable.root else "$REPO_ROOT";
            }
            // lib.optionalAttrs (editable ? members) {
              members = editable.members;
            }
          )
        else
          errors.fail where "editable must be false, true, or an attribute set";

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

      hooks = rec {
        repoRoot = ''
          if [ -z "''${REPO_ROOT:-}" ]; then
            REPO_ROOT="$(${lib.getExe pkgs.git} rev-parse --show-toplevel 2>/dev/null || pwd)"
            export REPO_ROOT
          fi
        '';

        uv = ''
          export UV_NO_SYNC="''${UV_NO_SYNC:-1}"
          export UV_PYTHON="${lib.getExe resolvedInterpreter}"
          export UV_PYTHON_DOWNLOADS="''${UV_PYTHON_DOWNLOADS:-never}"
        '';

        python = ''
          unset PYTHONPATH
        '';

        default = ''
          ${repoRoot}
          ${uv}
          ${python}
        '';
      };

      mkVenv =
        {
          name,
          dependencies ? scopeDependencies,
          editable ? false,
        }:
        let
          venvPythonSet = if editable == false then pythonSet else mkEditablePythonSet "venv" editable;
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
          name ? null,
          command ? null,
          script ? null,
          pythonPath ? [ ],
          workingDirectory ? workspaceRoot,
        }:
        if command != null then
          let
            commandName = if name != null then name else pname;
          in
          if package != null then
            errors.fail "app" "pass either `package` or `command`, not both"
          else if script != null then
            errors.fail "app" "pass `script` only with package mode"
          else if builtins.isString command then
            errors.fail "app" "`command` must be a list, not a shell string"
          else if !builtins.isList command then
            errors.fail "app" "`command` must be a non-empty list of strings or paths"
          else if command == [ ] then
            errors.fail "app" "`command` must be a non-empty list of strings or paths"
          else if !(builtins.all (entry: builtins.isString entry || builtins.isPath entry) command) then
            errors.fail "app" "`command` must be a non-empty list of strings or paths"
          else if commandName == null then
            errors.fail "app" "`name` is required when using command mode"
          else if commandName == "" then
            errors.fail "app" "`name` must be non-empty when using command mode"
          else if !builtins.isList pythonPath then
            errors.fail "app" "`pythonPath` must be a list of strings or paths"
          else if !(builtins.all (entry: builtins.isString entry || builtins.isPath entry) pythonPath) then
            errors.fail "app" "`pythonPath` must be a list of strings or paths"
          else
            let
              commandVenv = if venv == null then mkVenv { name = "${commandName}-env"; } else venv;
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
              name = commandName;
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
            appPackage = pythonSet.${packageName};
            appVenv = if venv == null then mkVenv { name = "${packageName}-env"; } else venv;
          in
          if script == null then
            (pkgs.callPackage pyproject-nix.build.util { }).mkApplication (
              {
                venv = appVenv;
                package = appPackage;
              }
              // lib.optionalAttrs (pname != null) { inherit pname; }
              // lib.optionalAttrs (version != null) { inherit version; }
            )
          else if !builtins.isString script || script == "" then
            errors.fail "app" "`script` must be a non-empty string"
          else if lib.hasInfix "/" script then
            errors.fail "app" "`script` must not contain `/` when using script mode"
          else if name != null then
            errors.fail "app" "`name` cannot be used with `script`; the output binary name is `script`"
          else if pname != null && (!builtins.isString pname || pname == "") then
            errors.fail "app" "`pname` must be a non-empty string when using script mode"
          else if pname != null && lib.hasInfix "/" pname then
            errors.fail "app" "`pname` must not contain `/` when using script mode"
          else
            let
              appName = script;
              appPname = if pname != null then pname else script;
              appVersion = if version != null then version else appPackage.version;
              sourceScript = "${appVenv}/bin/${script}";
            in
            pkgs.runCommand "${appPname}-${appVersion}"
              {
                pname = appPname;
                version = appVersion;
                meta = appPackage.meta or { };
                passthru = appPackage.passthru or { };
              }
              ''
                mkdir -p "$out/bin"
                source_script=${lib.escapeShellArg sourceScript}
                if [ ! -x "$source_script" ]; then
                  echo ${lib.escapeShellArg "uvloom.app: script `${script}` not found in venv for package `${packageName}`"} >&2
                  exit 1
                fi

                target_name=${lib.escapeShellArg appName}
                ln -s "$source_script" "$out/bin/$target_name"
              '';

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
              fetcher
              lock
              uvIndexes
              evaluatorFetch
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
      hook = hooks.default;
      inherit hooks;

      nixpkgs = {
        package = mkNixpkgsPackage;
      };
    };
in
makeScope
