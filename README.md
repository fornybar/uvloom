# uvloom

uvloom is a small Nix library flake for Python projects that use `uv` and `uv2nix`.

It removes common `uv2nix` boilerplate while keeping control in your own flake.

## Start here

| Need | Read |
| --- | --- |
| Create a new project | [Quick start](#quick-start) or [Tutorial](docs/tutorial.md) |
| Add one feature to an existing flake | [How-to guides](docs/how-to.md) |
| Check available functions | [Reference](docs/reference.md) |
| Understand the model | [Explanation](docs/explanation.md) |
| Browse all docs | [Documentation index](docs/index.md) |

> [!TIP]
> Use `uvloom.lib.loadProject` for normal `pyproject.toml` projects.
> Use `uvloom.lib.loadScript` for PEP 723 inline-metadata scripts.

## Quick start

Start from a template:

```sh
mkdir my-project
cd my-project
nix flake init -t github:fornybar/uvloom#simple
uv lock
nix flake check
```

Or add uvloom to an existing flake:

```nix
{
  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    uvloom.url = "github:fornybar/uvloom";
    uvloom.inputs.nixpkgs.follows = "nixpkgs";
  };

  outputs = { nixpkgs, uvloom, ... }:
    let
      system = "x86_64-linux";
      pkgs = nixpkgs.legacyPackages.${system};
      project = uvloom.lib.loadProject { root = ./.; };
      scope = project.forPython {
        inherit pkgs;
        interpreter = pkgs.python312;
      };
    in
    {
      packages.${system}.default = scope.mkApplication { package = "my-project"; };
      checks.${system}.pytest = scope.mkPytestCheck { package = "my-project"; };
    };
}
```

Run:

```sh
nix build
nix flake check
```

## Core model

uvloom has two main objects:

```nix
project = uvloom.lib.loadProject { root = ./.; };

scope = project.forPython {
  inherit pkgs;
  interpreter = pkgs.python312;
};
```

- `project` reads `pyproject.toml` and `uv.lock` through `uv2nix`.
- `scope` binds that project to one nixpkgs package set and Python interpreter.

Common helpers:

| Helper | Use |
| --- | --- |
| `scope.mkApplication` | Build console-script application wrapper. |
| `scope.mkVenv` | Build virtual environment. |
| `scope.mkPytestCheck` | Add pytest to `nix flake check`. |
| `scope.mkEditableVenv` | Use working-tree source in a dev shell. |
| `scope.pythonSet` | Drop to pyproject.nix package set for overrides. |

uvloom does not choose your flake layout. You still decide `packages`, `checks`, `devShells`, overlays, and multi-system structure.

## Common tasks

Build an application:

```nix
packages.${system}.default = scope.mkApplication {
  package = "my-project";
};
```

Build a virtual environment:

```nix
packages.${system}.env = scope.mkVenv {
  name = "my-project-env";
};
```

Run pytest:

```nix
checks.${system}.pytest = scope.mkPytestCheck {
  package = "my-project";
  groups = [ "test" ];
  paths = [ "tests" ];
};
```

Use editable source in `nix develop`:

```nix
scope = project.forPython {
  inherit pkgs;
  interpreter = pkgs.python312;
  editable = {
    root = "$PWD";
    members = [ "my-project" ];
  };
};

devShells.${system}.default = pkgs.mkShell {
  packages = [
    (scope.mkEditableVenv { name = "my-project-dev-env"; })
    pkgs.uv
  ];
};
```

More recipes: [How-to guides](docs/how-to.md).

## Templates

Bundled templates:

- `simple`: minimal application package.
- `editable`: editable development environment.
- `pytest`: pytest check integration.

Initialize one:

```sh
nix flake init -t github:fornybar/uvloom#pytest
```

## Advanced seams

Use these when helpers are not enough:

- `project.workspace`: raw upstream `uv2nix` workspace.
- `scope.pythonSet`: package set used by non-editable helpers.
- `scope.editablePythonSet`: package set used by editable helpers.
- `scope.nixpkgs.*`: export packages to nixpkgs-style Python sets.

If these seams are not enough, use `uv2nix` and `pyproject-nix` directly.

## Docs

- [Tutorial](docs/tutorial.md)
- [How-to guides](docs/how-to.md)
- [Reference](docs/reference.md)
- [Explanation](docs/explanation.md)
- [Full guide](docs/intro.md)

## Check project

```sh
nix flake check
```
