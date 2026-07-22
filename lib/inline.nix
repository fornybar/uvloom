{
  lib,
  uv2nix,
  pyproject-nix,
  pyproject-build-systems,
}:

let
  pythonSetLib = import ./python-set.nix {
    inherit lib pyproject-nix pyproject-build-systems;
  };

  load =
    {
      path,
      lockPath ? path + ".lock",
      config ? { },
      fetcher ? "auto",
      evaluatorFetch ? builtins.fetchurl,
    }:
    let
      scriptPath = path;
      script = path;
      configuredFetcher = fetcher;
      configuredEvaluatorFetch = evaluatorFetch;
      hasInlineMetadata = lib.hasInfix "# /// script" (builtins.readFile scriptPath);
      missingInlineMetadataError = "inline.load: ${toString scriptPath} has no PEP 723 inline metadata. For uv project entrypoints, use project.load and app { command = ...; }.";
    in
    if !hasInlineMetadata then
      throw missingInlineMetadataError
    else
      let
        metadataScript = pyproject-nix.lib.scripts.loadScript {
          inherit script;
        };

        loadedScript = uv2nix.lib.scripts.loadScript {
          inherit script lockPath config;
        };
        lock = uv2nix.lib.lock1.parseLock (lib.importTOML lockPath);
      in
      {
        inherit (loadedScript) name config;

        inherit (metadataScript) metadata;

        raw = loadedScript;

        forPython =
          {
            pkgs,
            interpreter ? null,
            sourcePreference ? if loadedScript.config.no-binary then "sdist" else "wheel",
            overlays ? [ ],
            environ ? { },
            workspaceRoot ? builtins.dirOf script,
            stdenv ? pkgs.stdenv,
            fetcher ? configuredFetcher,
            evaluatorFetch ? configuredEvaluatorFetch,
          }:
          let
            validFetchers = [
              "auto"
              "evaluator"
              "nixpkgs"
            ];
            checkedFetcher =
              if builtins.elem fetcher validFetchers then
                fetcher
              else
                throw "uvloom.inline.load.forPython: fetcher must be one of: ${lib.concatStringsSep ", " validFetchers}";
            authenticatedIndexFetchOverlay =
              if checkedFetcher == "nixpkgs" then
                null
              else
                let
                  authenticatedIndexFetchLib = import ./authenticated-index-fetch.nix {
                    inherit lib;
                    fail = where: message: throw "uvloom.${where}: ${message}";
                  };
                in
                authenticatedIndexFetchLib.mkOverlay {
                  inherit lock evaluatorFetch;
                  uvIndexes = ((metadataScript.metadata.tool or { }).uv or { }).index or [ ];
                  authenticatedOnly = checkedFetcher == "auto";
                };
            packagePkgs =
              if authenticatedIndexFetchOverlay == null then pkgs else pkgs.extend authenticatedIndexFetchOverlay;
            pythonSetCore = pythonSetLib.build {
              where = "inline.load.forPython";
              inherit
                interpreter
                sourcePreference
                overlays
                environ
                stdenv
                ;
              pkgs = packagePkgs;
              requiresPythonSource = {
                requires-python = metadataScript.metadata.requires-python;
              };
              mkOverlay =
                { sourcePreference, environ }:
                loadedScript.mkOverlay {
                  inherit sourcePreference environ workspaceRoot;
                };
            };

            inherit (pythonSetCore) resolvedInterpreter pythonSet;

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
              { }:
              loadedScript.mkVirtualEnv {
                inherit pythonSet environ;
              };

            renderScript =
              {
                venv ? mkVenv { },
              }:
              loadedScript.renderScript { inherit venv; };

            mkApplication =
              {
                name ? loadedScript.name,
                venv ? mkVenv { },
              }:
              pkgs.writeScriptBin name (renderScript {
                inherit venv;
              });

            mkEditableApplication =
              {
                name ? loadedScript.name,
                root ? "$REPO_ROOT",
                path ? baseNameOf scriptPath,
                venv ? mkVenv { },
              }:
              pkgs.writeShellApplication {
                inherit name;
                runtimeInputs = [ venv ];
                text = ''
                  script_path=${lib.escapeShellArg path}
                  exec python "${root}/$script_path" "$@"
                '';
              };
          in
          {
            inherit
              pythonSet
              ;

            venv = mkVenv;
            render = renderScript;
            interpreter = resolvedInterpreter;
            hook = hooks.default;
            inherit hooks;
            app = {
              __functor = self: mkApplication;
              editable = mkEditableApplication;
            };
          };
      };

  loadDir =
    {
      root,
      config ? { },
      fetcher ? "auto",
      evaluatorFetch ? builtins.fetchurl,
    }:
    lib.mapAttrs'
      (
        fileName: _:
        lib.nameValuePair (lib.removeSuffix ".py" fileName) (load {
          path = root + "/${fileName}";
          inherit config fetcher evaluatorFetch;
        })
      )
      (
        lib.filterAttrs (name: type: type == "regular" && lib.hasSuffix ".py" name) (builtins.readDir root)
      );
in
{
  inherit load loadDir;
}
