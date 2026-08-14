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
      fetcher ? "auto",
    }:
    let
      projectForgeFetch = forgeFetch;
      projectFetcher = fetcher;
      pyproject = lib.importTOML (root + "/pyproject.toml");
      uvIndexes = ((pyproject.tool or { }).uv or { }).index or [ ];
      lock = uv2nix.lib.lock1.parseLock (lib.importTOML (root + "/uv.lock"));
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
            fetcher ? projectFetcher,
            overlays ? [ ],
            environ ? { },
            stdenv ? null,
            evaluatorFetch ? builtins.fetchurl,
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
                fetcher
                overlays
                environ
                evaluatorFetch
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
          fetcher ? projectFetcher,
          overlays ? [ ],
          environ ? { },
          stdenv ? pkgs.stdenv,
          evaluatorFetch ? builtins.fetchurl,
        }:
        makeScope {
          inherit
            workspace
            pkgs
            interpreter
            sourcePreference
            dependencies
            forgeFetch
            fetcher
            overlays
            environ
            stdenv
            lock
            uvIndexes
            evaluatorFetch
            ;
          workspaceRoot = root;
        };
    };
in
{
  project = {
    load = loadProject;
  };

  inline = {
    load = inlineLib.load;
    fromDir = inlineLib.loadDir;
  };
}
