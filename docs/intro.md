# uvloom

uvloom is a thin Nix library flake for Python projects that use `uv` and `uv2nix`.

It removes repeated setup code while keeping control in your flake. You still choose nixpkgs, Python interpreter, dependency selections, overlays, editable mode, packages, checks, and shells.

## When to use uvloom

Use uvloom when you want:

- shorter `uv2nix` flakes
- reusable helpers for virtual environments, apps, editable dev environments, and pytest checks
- access to underlying `pyproject.nix` package sets for overrides and advanced builds
- no commitment to `flake-parts`, `flake-utils`, or any other flake architecture

Use upstream `uv2nix` directly when you need full manual control over every composition step.

## Reading map

| Need | Section |
| --- | --- |
| Try working template | [Quick start](#quick-start) |
| Understand object model | [Core model](#core-model) |
| Copy minimal flake | [Minimal flake shape](#minimal-flake-shape) |
| Build apps, envs, tests | [Common patterns](#common-patterns) |
| Override packages | [Add overlays](#add-overlays) |
| Drop to lower-level APIs | [Advanced escape hatches](#advanced-escape-hatches) |

## Quick start

Use one of the bundled templates:

```sh
nix flake init -t github:fornybar/uvloom#simple
# or
nix flake init -t github:fornybar/uvloom#editable
# or
nix flake init -t github:fornybar/uvloom#pytest
```

Then update Python metadata and lock file as usual:

```sh
uv lock
nix flake check
```

## Core model

uvloom has two main objects:

1. **Project**: loaded once from `pyproject.toml` and `uv.lock`.
2. **Scope**: created per nixpkgs package set / Python interpreter.

```nix
project = uvloom.lib.loadProject { root = ./.; };

scope = project.forPython {
  inherit pkgs;
  interpreter = pkgs.python312;
};
```

The resulting `scope` contains helpers for common flake outputs:

| Helper | Purpose |
| --- | --- |
| `scope.mkVenv` | Build virtual environment. |
| `scope.mkApplication` | Expose console-script application package. |
| `scope.mkPytestCheck` | Build pytest derivation for `checks`. |
| `scope.mkEditableVenv` | Build editable dev environment when `editable` is enabled. |
| `scope.pythonSet` | Access underlying pyproject.nix package set. |
| `scope.nixpkgs.*` | Export generated packages to nixpkgs-style Python sets. |

> [!IMPORTANT]
> uvloom does not own your flake outputs. You decide where helpers go under `packages`, `checks`, `devShells`, and overlays.

## Minimal flake shape

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
    };
}
```

## Common patterns

### Build an application

Use this when your project exposes console scripts through `pyproject.toml`:

```nix
packages.default = scope.mkApplication { package = "my-project"; };
```

If the workspace has exactly one local package, `package` can often be omitted:

```nix
packages.default = scope.mkApplication { };
```

### Build a virtual environment

```nix
packages.default = scope.mkVenv {
  name = "my-project-env";
};
```

By default this uses `workspace.deps.default`. Override dependency groups when needed:

```nix
packages.dev = scope.mkVenv {
  name = "my-project-dev-env";
  dependencies = project.workspace.deps.all;
};
```

### Run pytest in `nix flake check`

```nix
checks.pytest = scope.mkPytestCheck {
  package = "my-project";
  groups = [ "test" ];
};
```

Extra pytest flags and paths are supported:

```nix
checks.pytest = scope.mkPytestCheck {
  package = "my-project";
  paths = [ "tests" ];
  pytestFlags = [ "-q" ];
};
```

### Editable virtual environments

Use an editable virtual environment for local development. Normal Nix builds copy project sources into the store, so changing `src/` means rebuilding the package before imports or console scripts see the change. Editable mode points selected workspace members at your working tree instead, while keeping dependencies built by Nix.

Good fit for:

- quick edit-run-test loops
- language servers and REPLs that should import current source files
- console scripts that should use the checkout without rebuilding after every edit

First enable editable mode on the scope:

```nix
scope = project.forPython {
  inherit pkgs;
  interpreter = pkgs.python312;
  editable = {
    root = "$PWD";
    members = [ "my-project" ];
  };
};
```

Then expose an editable virtual environment as a package:

```nix
packages.dev = scope.mkEditableVenv {
  name = "my-project-dev-env";
};
```

Or put it in a development shell:

```nix
devShells.default = pkgs.mkShell {
  packages = [
    (scope.mkEditableVenv { name = "my-project-dev-env"; })
  ];
};
```

For multi-package workspaces, list editable members explicitly:

```nix
scope = project.forPython {
  inherit pkgs;
  interpreter = pkgs.python312;
  editable = {
    root = "$PWD";
    members = [
      "my-app"
      "my-library"
    ];
  };
};
```

To include optional development dependencies in the editable environment, override `dependencies`:

```nix
packages.dev = scope.mkEditableVenv {
  name = "my-project-dev-env";
  dependencies = project.workspace.deps.all;
};
```

### Add overlays

`forPython` accepts extra pyproject.nix package-set overlays after uvloom's build-system and workspace overlays. These are the same kind of overlays uv2nix passes to `pythonSet.overrideScope`; they are not nixpkgs flake overlays.

```nix
scope = project.forPython {
  inherit pkgs;
  overlays = [
    (final: prev: {
      my-project = prev.my-project.overrideAttrs (old: {
        nativeBuildInputs = (old.nativeBuildInputs or [ ]) ++ [ pkgs.pkg-config ];
      });
    })
  ];
};
```

Capture `pkgs` from the surrounding scope when an overlay needs nixpkgs packages. This matches uv2nix's normal pattern.

### Export generated packages to nixpkgs-style Python sets

Use this when a project is built internally with `uv2nix`, but consumers should still use normal nixpkgs patterns such as `python3.pkgs.withPackages` or `python3Packages.my-project`.

At flake overlay level, export selected generated packages through `pythonPackagesExtensions`:

```nix
let
  project = uvloom.lib.loadProject { root = ./.; };
in
{
  overlays.default = project.nixpkgs.overlay {
    packages = [
      "my-project"
      "locked-dependency"
    ];
  };
}
```

`project.nixpkgs.overlay` is a convenience wrapper. It is equivalent to writing:

```nix
overlays.default = final: prev: {
  pythonPackagesExtensions = (prev.pythonPackagesExtensions or [ ]) ++ [
    (project.nixpkgs.pythonPackagesExtension {
      packages = [
        "my-project"
        "locked-dependency"
      ];
    })
  ];
};
```

Use the explicit form when package-set overlays need nixpkgs `final` or when you need to append another nixpkgs Python extension after uvloom's export.

List dependencies explicitly when they are missing from nixpkgs or need lockfile versions. This avoids overriding the whole dependency closure and reduces conflicts with consumers' nixpkgs package set.

Consumers can then use normal nixpkgs Python package sets:

```nix
pkgs = import nixpkgs {
  inherit system;
  overlays = [ my-project.overlays.default ];
};

devShells.default = pkgs.mkShell {
  packages = [
    (pkgs.python3.withPackages (ps: [ ps.my-project ]))
  ];
};
```

When only one concrete Python interpreter/package set is needed, export a Python package-set extension from a scope:

```nix
python = pkgs.python312.override {
  self = python;
  packageOverrides = scope.nixpkgs.pythonPackagesExtension {
    packages = [ "my-project" ];
  };
};

packages.nixpkgs-style = python.pkgs.my-project;
```

Or ask uvloom for one nixpkgs-compatible package directly:

```nix
packages.nixpkgs-style = scope.nixpkgs.package {
  package = "my-project";
};
```

Default export package list is local workspace packages. Pass dependencies too when consumers need generated locked versions that nixpkgs does not provide:

```nix
overlays.default = project.nixpkgs.overlay {
  packages = [
    "my-project"
    "my-locked-dependency"
  ];
};
```

The export adapter converts uv2nix packages into nixpkgs-compatible Python packages. This preserves normal nixpkgs Python propagation and `withPackages` behavior, but dependency resolution after export follows nixpkgs package-set rules instead of uv2nix virtualenv resolution.

There are two override layers when exporting:

1. `overlays` passed to `project.nixpkgs.pythonPackagesExtension` are pyproject.nix package-set overlays. They run before export, inside uv2nix/pyproject.nix composition.
2. Extra entries appended to `pythonPackagesExtensions` are nixpkgs Python package-set extensions. They run after export, against nixpkgs-style Python packages.

Example with both layers:

```nix
overlays.default = final: prev: {
  pythonPackagesExtensions = (prev.pythonPackagesExtensions or [ ]) ++ [
    (project.nixpkgs.pythonPackagesExtension {
      packages = [ "my-project" ];
      overlays = [
        (config.patches.my-project { pkgs = final; })
      ];
    })

    (python-final: python-prev: {
      my-project = python-prev.my-project.overridePythonAttrs (old: {
        propagatedBuildInputs = (old.propagatedBuildInputs or [ ]) ++ [
          python-final.numpy
        ];
      });
    })
  ];
};
```

## Advanced escape hatches

uvloom keeps common workflows on helpers such as `scope.mkVenv`, `scope.mkApplication`, and `scope.mkPytestCheck`. When you need lower-level interop, these seams are intentional:

- `project.workspace` is the raw upstream `uv2nix` workspace. Use it for narrow interop such as `project.workspace.deps.*`, `mkPyprojectOverlay`, or `mkEditablePyprojectOverlay`. uvloom guarantees this attr is present, but does not wrap or stabilize every upstream workspace detail.
- `scope.pythonSet` is the final pyproject.nix package set used by non-editable helpers after build-system, workspace, and user overlays are composed.
- `scope.editablePythonSet` is present only when `editable` is configured and is the final editable package set used by `scope.mkEditableVenv`.
- `scope.nixpkgs.pythonPackagesExtension` and `scope.nixpkgs.package` are the supported nixpkgs-style export adapters.

If you need to replace uvloom's composition pipeline wholesale, add `uv2nix`, `pyproject-nix`, and `build-system-pkgs` as explicit inputs and compose upstream modules directly.
