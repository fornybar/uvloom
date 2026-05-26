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
    }:
    let
      scriptPath = path;
      script = path;
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
          }:
          let
            pythonSetCore = pythonSetLib.build {
              where = "inline.load.forPython";
              inherit
                pkgs
                interpreter
                sourcePreference
                overlays
                environ
                stdenv
                ;
              requiresPythonSource = {
                requires-python = metadataScript.metadata.requires-python;
              };
              mkOverlay =
                { sourcePreference, environ }:
                loadedScript.mkOverlay {
                  inherit sourcePreference environ workspaceRoot;
                };
            };

            inherit (pythonSetCore) pythonSet;

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
                root ? "$PWD",
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
    }:
    lib.mapAttrs'
      (
        fileName: _:
        lib.nameValuePair (lib.removeSuffix ".py" fileName) (load {
          path = root + "/${fileName}";
          inherit config;
        })
      )
      (
        lib.filterAttrs (name: type: type == "regular" && lib.hasSuffix ".py" name) (builtins.readDir root)
      );
in
{
  inherit load loadDir;
}
