{
  lib,
  uv2nix,
  pyproject-nix,
  pyproject-build-systems,
}:

let
  makeScope = import ./scope.nix {
    inherit lib pyproject-nix pyproject-build-systems;
  };

  scriptLib = import ./script.nix {
    inherit
      lib
      uv2nix
      pyproject-nix
      pyproject-build-systems
      ;
  };
in
{
  /**
    Stable uvloom library API version.

    Incremented when documented `uvloom.lib` API contracts change in a backward-incompatible way.

    # Type

    ```
    apiVersion :: Int
    ```
  */
  apiVersion = 1;

  /**
    Load a uv workspace and prepare it for Python package/check construction.

    This is the main uvloom entry point. It loads `pyproject.toml` and `uv.lock` from `root` with
    `uv2nix.lib.workspace.loadWorkspace`, then returns the raw workspace plus `forPython`, a helper
    that creates a scoped API for one nixpkgs package set and interpreter.

    # Type

    ```
    loadProject :: { root :: Path } -> Project
    ```

    # Arguments

    - `root`: Project root containing `pyproject.toml` and `uv.lock`.

    # Result

    `loadProject` returns an attribute set with:

    - `workspace`: Raw `uv2nix` workspace value. This is an advanced escape hatch for narrow upstream interop such as `workspace.deps.*`, `mkPyprojectOverlay`, or `mkEditablePyprojectOverlay`; uvloom only guarantees that the attr is present and does not stabilize every upstream workspace detail.
    - `forPython`: Function that binds the workspace to one nixpkgs package set and Python interpreter.
    - `nixpkgs.pythonPackagesExtension`: Function that exports selected uv2nix packages as a nixpkgs Python package-set extension.
    - `nixpkgs.overlay`: Function that exports selected uv2nix packages through `pythonPackagesExtensions`.

    # `forPython` arguments

    `forPython` accepts:

    - `pkgs`: nixpkgs package set for the target system.
    - `interpreter`: Python interpreter derivation. Defaults to an interpreter compatible with the workspace `requires-python` metadata when uvloom can infer one.
    - `sourcePreference`: uv2nix source preference. Defaults to `"wheel"`.
    - `dependencies`: uv2nix dependency selection. Defaults to `workspace.deps.default`.
    - `overlays`: Additional pyproject.nix package-set overlays. Defaults to `[ ]`.
    - `editable`: Optional editable overlay config, usually `{ root = "$PWD"; members = [ "package-name" ]; }`.
    - `environ`: Environment passed to `workspace.mkPyprojectOverlay`. Defaults to `{ }`.
    - `stdenv`: stdenv used by pyproject.nix builds. Defaults to `pkgs.stdenv`.

    # `forPython` result

    `forPython` returns a scope with:

    - `interpreter`: The resolved Python interpreter derivation. Use `lib.getExe scope.interpreter` for the executable path, for example in `UV_PYTHON`.
    - `pythonSet`: The underlying pyproject.nix package set after build-system, workspace, and user overlays. This is an advanced seam for package-set-level interop.
    - `nixpkgs.pythonPackagesExtension { packages ? localPackages }`: Export selected generated packages as a nixpkgs Python package-set extension.
    - `nixpkgs.package { package ? null, exportPackages ? [ resolved package ] }`: Build one generated package through nixpkgs `buildPythonPackage` compatibility.
    - `mkVenv { name, dependencies ? workspace.deps.default }`: Build a virtual environment from a dependency selection.
    - `mkApplication { package ? null, venv ? null, pname ? null, version ? null }`: Build an application wrapper for a local package. `package` can be omitted for single-package workspaces.
    - `mkPytestCheck { package ? null, groups ? [ "test" ], dependencies ? null, name ? null, paths ? [ "tests" ], pytestFlags ? [ ], env ? { }, nativeBuildInputs ? [ ] }`: Build a pytest check derivation.
    - `editablePythonSet`: Present only when `editable` is set. Package set with editable overlay applied.
    - `mkEditableVenv { name, dependencies ? workspace.deps.default }`: Present only when `editable` is set. Build an editable virtual environment.

    # Example

    ```nix
    let
      project = uvloom.lib.loadProject { root = ./.; };
      scope = project.forPython { inherit pkgs; };
    in
    scope.mkVenv { name = "my-project-env"; }
    ```
  */
  loadProject =
    { root }:
    let
      workspace = uv2nix.lib.workspace.loadWorkspace {
        workspaceRoot = root;
      };
      localPackages = builtins.attrNames workspace.deps.default;
    in
    rec {
      inherit workspace;

      nixpkgs = {
        pythonPackagesExtension =
          {
            packages ? localPackages,
            sourcePreference ? "wheel",
            dependencies ? workspace.deps.default,
            overlays ? [ ],
            environ ? { },
            stdenv ? null,
          }:
          pythonFinal: pythonPrev:
          let
            pkgs = pythonPrev.pkgs;
            scope = forPython {
              inherit
                pkgs
                sourcePreference
                dependencies
                overlays
                environ
                ;
              interpreter = pythonPrev.python;
              stdenv = if stdenv == null then pkgs.stdenv else stdenv;
            };
          in
          (scope.nixpkgs.pythonPackagesExtension { inherit packages; }) pythonFinal pythonPrev;

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
          overlays ? [ ],
          editable ? null,
          environ ? { },
          stdenv ? pkgs.stdenv,
        }:
        makeScope {
          inherit
            workspace
            pkgs
            interpreter
            sourcePreference
            dependencies
            overlays
            editable
            environ
            stdenv
            ;
        };
    };

  /**
    Load a PEP 723 inline metadata Python script and prepare it for application construction.

    # Type

    ```
    loadScript :: { script :: Path, lockPath ? Path, config ? AttrSet | Function } -> Script
    ```

    # Arguments

    - `script`: Python script containing inline metadata.
    - `lockPath`: uv script lock file. Defaults to `${script}.lock`.
    - `config`: uv2nix script config overrides. Passed through to `uv2nix.lib.scripts.loadScript`.

    # Result

    Returns an attribute set with:

    - `name`: Script basename without `.py`.
    - `metadata`: Parsed inline script metadata.
    - `config`: Loaded script config.
    - `raw`: Raw upstream uv2nix script value.
    - `forPython`: Function that binds the script to one nixpkgs package set and interpreter.

    `forPython` accepts `pkgs`, optional `interpreter`, `sourcePreference`, `overlays`, `environ`,
    `workspaceRoot`, and `stdenv`, then returns:

    - `pythonSet`: Package set containing script dependencies.
    - `mkVenv { }`: Build the script virtual environment.
    - `renderScript { venv ? mkVenv { } }`: Render script with a venv shebang.
    - `mkApplication { name ? scriptName, venv ? mkVenv { } }`: Build a runnable script application.

    # Example

    ```nix
    let
      script = uvloom.lib.loadScript { script = ./scripts/weather.py; };
      scope = script.forPython { inherit pkgs; interpreter = pkgs.python312; };
    in
    scope.mkApplication { name = "weather"; }
    ```
  */
  loadScript = scriptLib.loadScript;

  /**
    Load all `.py` inline metadata scripts from a directory.

    # Type

    ```
    loadScripts :: { root :: Path, config ? AttrSet | Function } -> AttrSet Script
    ```

    Result keys are script filenames with the `.py` suffix removed.
  */
  loadScripts = scriptLib.loadScripts;
}
