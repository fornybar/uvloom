{
  lib,
  uv2nix,
  pyproject-nix,
  pyproject-build-systems,
}:

let
  makeScope = import ./scope.nix {
    inherit
      lib
      uv2nix
      pyproject-nix
      pyproject-build-systems
      ;
  };

  inlineLib = import ./inline.nix {
    inherit
      lib
      uv2nix
      pyproject-nix
      pyproject-build-systems
      ;
  };

  loadProject =
    {
      root,
      forgeFetch ? "auto",
    }:
    let
      projectForgeFetch = forgeFetch;
      uvLock = uv2nix.lib.lock1.parseLock (builtins.fromTOML (builtins.readFile (root + "/uv.lock")));
      workspace = uv2nix.lib.workspace.loadWorkspace {
        workspaceRoot = root;
      };
      localPackages = builtins.attrNames workspace.deps.default;
    in
    rec {
      inherit root workspace;

      nixpkgs = {
        pythonPackagesExtension =
          {
            packages ? localPackages,
            sourcePreference ? "wheel",
            dependencies ? workspace.deps.default,
            forgeFetch ? projectForgeFetch,
            overlays ? [ ],
            environ ? { },
            stdenv ? null,
          }:
          python-final: python-prev:
          let
            pkgs = python-prev.pkgs;
            scope = forPython {
              inherit
                pkgs
                sourcePreference
                dependencies
                forgeFetch
                overlays
                environ
                ;
              interpreter = python-prev.python;
              stdenv = if stdenv == null then pkgs.stdenv else stdenv;
            };
          in
          ((pkgs.callPackage pyproject-nix.build.hacks { }).toNixpkgs {
            inherit packages;
            inherit (scope) pythonSet;
          })
            python-final
            python-prev;

        overlay = args: final: prev: {
          pythonPackagesExtensions = (prev.pythonPackagesExtensions or [ ]) ++ [
            (nixpkgs.pythonPackagesExtension args)
          ];
        };
      };

      forPython =
        {
          pkgs,
          interpreter ? null,
          sourcePreference ? "wheel",
          dependencies ? workspace.deps.default,
          forgeFetch ? projectForgeFetch,
          overlays ? [ ],
          environ ? { },
          stdenv ? pkgs.stdenv,
        }:
        makeScope {
          inherit
            workspace
            uvLock
            pkgs
            interpreter
            sourcePreference
            dependencies
            forgeFetch
            overlays
            environ
            stdenv
            ;
          workspaceRoot = root;
        };
    };
in
{
  apiVersion = 2;

  project = {
    load = loadProject;
  };

  inline = {
    load = inlineLib.load;
    fromDir = inlineLib.loadDir;
  };
}
