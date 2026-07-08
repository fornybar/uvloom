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

  inherit (import ./errors.nix { }) fail;

  filterSourceLib = import ./filter-source.nix {
    inherit lib fail;
  };

  /**
    Load a uv project/workspace from `root`.

    # Arguments

    root
    : Path to the workspace root (must contain `pyproject.toml` and `uv.lock`).

    forgeFetch
    : Forge-fetch configuration forwarded to `forPython` (default `"auto"`).

    filterSource
    : When `true`, the source passed to uv2nix (and exposed as `project.root`)
      is a `lib.fileset.toSource`-filtered copy of `root` containing only
      `pyproject.toml`, `uv.lock`, `.python-version`/`uv.nix`/`README*`/
      `LICENSE*`/`LICENCE*`/`COPYING*`/`NOTICE*`/`AUTHORS*` (when present),
      the readme declared in `[project].readme` (string or `{ file = ... }`
      form), license files declared as `[project].license.file` or simple
      `[project].license-files` globs (`*` only as a trailing suffix;
      single-character `[...]` classes of plain characters are expanded),
      the source trees of every local package recorded in `uv.lock`
      (workspace members, local `directory` dependencies, and local
      `path`-sourced wheel/sdist archives), and the `pyproject.toml` of
      every non-root `virtual` workspace member (uv2nix folds member
      manifests' `[tool.uv]` config into the workspace configuration). For
      the root package, directories configured via
      `tool.hatch.build.targets.wheel.packages` or `tool.setuptools.packages`
      are always included alongside `src/` when both exist; without `src/`
      (or with a `src/` containing no Python files), top-level Python
      modules and the name-derived module directory are the
      fallback. A root `virtual` package (`[tool.uv] package = false`) gets
      the same root package sources, but leniently: a virtual root may
      carry no sources at all, and other directories still need
      `extraSourcePaths`. Root `setup.py`, `setup.cfg`, `hatch.toml`, and
      `MANIFEST.in` are included when regular files. Hatch
      force-include/include/artifacts and setuptools package-dir/packages.find
      data are not whitelisted; use `extraSourcePaths` or `filterSource =
      false` for those projects.
      Dotfiles and hidden directories (any hidden path segment) inside
      member trees are always dropped, except metadata explicitly declared
      in `[project]` (readme, license.file, license-files). Every inferred
      selected path must be free of symlinks; selected singleton metadata
      must be a regular file. Default `false` (byte-identical to passing
      `root` unfiltered).

    extraSourcePaths
    : Extra root-relative paths (strings) whitelisted into the filtered
      source when they exist, e.g. `[ "tests" ]` so a filtered project can
      still run its test suite. Explicit entries preserve hidden files and
      directories, but must be symlink-free. Ignored unless `filterSource =
      true`.
  */
  loadProject =
    {
      root,
      forgeFetch ? "auto",
      filterSource ? false,
      extraSourcePaths ? [ ],
    }:
    let
      projectForgeFetch = forgeFetch;

      # Whitelist-based source filtering (only explicitly whitelisted paths
      # reach the store copy); implementation lives in ./filter-source.nix.
      # uv2nix workspace path math keeps using the original workspace root;
      # package source derivations are overridden to this filtered copy below
      # when filterSource is enabled.
      sourceRoot =
        if !builtins.isBool filterSource then
          fail "project.load" "filterSource must be a boolean"
        else if filterSource then
          filterSourceLib.filterRoot { inherit root extraSourcePaths; }
        else
          root;

      uvLockTOML = builtins.fromTOML (builtins.readFile (sourceRoot + "/uv.lock"));
      pyprojectTOML = builtins.fromTOML (builtins.readFile (sourceRoot + "/pyproject.toml"));
      uvLock = uv2nix.lib.lock1.parseLock uvLockTOML;
      workspace = uv2nix.lib.workspace.loadWorkspace {
        workspaceRoot = root;
        uvLock = uvLockTOML;
        pyproject = pyprojectTOML;
      };
      localPackages = builtins.attrNames workspace.deps.default;
    in
    rec {
      inherit root sourceRoot;
      inherit workspace;

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
          sourceRoot = sourceRoot;
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
