# Explanation

uvloom keeps common `uv2nix` flakes small.

## Project and scope

Most flakes start here:

```nix
project = uvloom.lib.loadProject { root = ./.; };
scope = project.forPython { inherit pkgs; interpreter = pkgs.python312; };
```

`project` comes from `pyproject.toml` and `uv.lock`.

`scope` adds the Nix context: nixpkgs package set, Python interpreter, dependency selection, overlays, and optional editable mode.

This split matters because one Python project can be built for multiple systems or Python versions.

## Helpers

Scope helpers are shortcuts over the same package set:

| Helper | Output |
| --- | --- |
| `mkApplication` | Console-script package. |
| `mkVenv` | Virtual environment. |
| `mkPytestCheck` | pytest check derivation. |
| `mkEditableVenv` | Development environment using checkout source. |

Use helpers for normal flakes. Use `scope.pythonSet` when a package needs override work.

## Dependencies

`uv.lock` stays the dependency source.

By default, uvloom uses the default workspace dependency set from `uv2nix`. Pass another `project.workspace.deps.*` value when you need extra groups, such as test or development dependencies.

## Editable mode

Normal Nix builds use a store copy of your source. After editing source, rebuild to see changes.

Editable mode points selected local packages at your checkout while dependencies stay Nix-built. Use it in `devShells`, not release packages.

## Escape hatches

Use lower layers when needed:

- `project.workspace`: upstream `uv2nix` workspace.
- `scope.pythonSet`: pyproject.nix package set.
- `scope.editablePythonSet`: editable package set.
- `scope.nixpkgs.*`: `python.withPackages` and nixpkgs-style exports.

Need more control than that? Use `uv2nix` directly.
