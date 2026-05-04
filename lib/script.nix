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

  loadScript =
    {
      script,
      lockPath ? script + ".lock",
      config ? { },
    }:
    let
      loadedScript = uv2nix.lib.scripts.loadScript {
        inherit script lockPath config;
      };

      metadataScript = pyproject-nix.lib.scripts.loadScript {
        inherit script;
      };
    in
    rec {
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
            where = "loadScript.forPython";
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
            pkgs.writeScript name (renderScript {
              inherit venv;
            });
        in
        {
          inherit
            pythonSet
            mkVenv
            renderScript
            mkApplication
            ;
        };
    };

  loadScripts =
    {
      root,
      config ? { },
    }:
    lib.mapAttrs'
      (
        fileName: _:
        lib.nameValuePair (lib.removeSuffix ".py" fileName) (loadScript {
          script = root + "/${fileName}";
          inherit config;
        })
      )
      (
        lib.filterAttrs (name: type: type == "regular" && lib.hasSuffix ".py" name) (builtins.readDir root)
      );
in
{
  inherit loadScript loadScripts;
}
