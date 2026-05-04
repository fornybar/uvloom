# Reference

Stable user-facing uvloom API. Built docs also include a full API page.

## `uvloom.lib.loadProject`

Load a `uv` workspace from `pyproject.toml` and `uv.lock`.

```nix
project = uvloom.lib.loadProject { root = ./.; };
```

Returns:

| Attribute | Meaning |
| --- | --- |
| `project.forPython` | Create scope for one nixpkgs package set and Python interpreter. |
| `project.workspace` | Upstream `uv2nix` workspace escape hatch. |
| `project.nixpkgs.overlay` | Export selected packages through a nixpkgs overlay. |
| `project.nixpkgs.pythonPackagesExtension` | Export selected packages as a Python package-set extension. |

## `project.forPython`

Create build scope:

```nix
scope = project.forPython {
  inherit pkgs;
  interpreter = pkgs.python312;
};
```

Common arguments:

| Argument | Purpose |
| --- | --- |
| `pkgs` | nixpkgs package set. Required. |
| `interpreter` | Python interpreter, such as `pkgs.python312`. |
| `sourcePreference` | Prefer `wheel` or `sdist` where upstream supports it. |
| `dependencies` | Dependency selection. Defaults to `project.workspace.deps.default`. |
| `overlays` | Extra pyproject.nix package-set overlays. |
| `editable` | Editable working-tree config, usually `{ root = "$PWD"; members = [ "my-project" ]; }`. |
| `environ` | Environment passed to upstream workspace overlay. |
| `stdenv` | stdenv used by pyproject.nix builds. |

Returns scope helpers below.

## `scope.interpreter`

Resolved Python interpreter derivation. Use `lib.getExe` for the executable path in dev shells that also expose `uv`:

```nix
UV_PYTHON = pkgs.lib.getExe scope.interpreter;
```

## `scope.mkApplication`

Build console-script application wrapper.

```nix
scope.mkApplication {
  package = "my-project";
}
```

If workspace has exactly one local package, `package` can be omitted.

## `scope.mkVenv`

Build virtual environment.

```nix
scope.mkVenv {
  name = "my-project-env";
}
```

Common arguments:

| Argument | Purpose |
| --- | --- |
| `name` | Derivation/environment name. |
| `dependencies` | Dependency selection. Defaults to `project.workspace.deps.default`. |

## `scope.mkPytestCheck`

Build pytest derivation for `checks`.

```nix
scope.mkPytestCheck {
  package = "my-project";
  groups = [ "test" ];
  paths = [ "tests" ];
  pytestFlags = [ "-q" ];
}
```

Common arguments:

| Argument | Purpose |
| --- | --- |
| `package` | Local package to test. Can be omitted for single-package workspaces. |
| `groups` | Dependency groups to include. Defaults to `[ "test" ]`. |
| `paths` | Test paths. Defaults to `[ "tests" ]`. |
| `pytestFlags` | Extra pytest flags. |
| `env` | Environment variables for test derivation. |
| `nativeBuildInputs` | Extra native build inputs. |

## `scope.mkEditableVenv`

Build virtual environment that imports selected workspace members from working tree.

Requires `editable` on `project.forPython`.

```nix
scope.mkEditableVenv {
  name = "my-project-dev-env";
}
```

## `scope.pythonSet`

Final pyproject.nix package set used by non-editable helpers.

Use for package overrides, custom derivations, and advanced interop.

## `scope.editablePythonSet`

Final editable package set. Present only when `editable` is configured.

## `scope.nixpkgs.pythonPackagesExtension`

Create nixpkgs-style Python package extension.

```nix
python = pkgs.python312.override {
  self = python;
  packageOverrides = scope.nixpkgs.pythonPackagesExtension {
    packages = [ "my-project" ];
  };
};
```

List dependencies explicitly when they are missing from nixpkgs or need lockfile versions.

```nix
python = pkgs.python312.override {
  self = python;
  packageOverrides = scope.nixpkgs.pythonPackagesExtension {
    packages = [
      "my-project"
      "locked-dependency"
    ];
  };
};
```

## `scope.nixpkgs.package`

Return one nixpkgs-compatible package directly.

```nix
packages.nixpkgs-style = scope.nixpkgs.package {
  package = "my-project";
};
```

## `uvloom.lib.loadScript`

Load a PEP 723 inline-metadata script.

```nix
script = uvloom.lib.loadScript { script = ./scripts/tool.py; };
scope = script.forPython { inherit pkgs; interpreter = pkgs.python312; };
```

Use `scope.mkApplication { }` to build runnable script package.

## Check commands

```sh
nix build
nix flake check
```
