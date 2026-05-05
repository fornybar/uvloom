# uvloom guide

uvloom is a thin Nix library for Python projects that use `uv` and `uv2nix`. It removes repeated setup code while keeping control in your flake.

You still choose nixpkgs, Python, dependency groups, overlays, packages, checks, shells, editable venvs, and exports.

## Use uvloom when

- You already have `pyproject.toml` and `uv.lock`.
- You want short flakes for applications, virtual environments, checks, or dev shells.
- You want access to underlying pyproject.nix package sets for overrides.
- You do not want to adopt `flake-parts`, `flake-utils`, or another flake framework.

Use upstream `uv2nix` directly when you need full manual control over every composition step.

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

For multi-system flakes, define `project` once outside the per-system function, then create a `scope` inside each system.

## Core model

uvloom has two main objects:

1. **Project**: loaded from `pyproject.toml` and `uv.lock`.
2. **Scope**: project bound to nixpkgs, Python, dependency selection, and overlays.

```nix
project = uvloom.lib.loadProject { root = ./.; };

scope = project.forPython {
  inherit pkgs;
  interpreter = pkgs.python312;
};
```

Scope helpers become normal flake outputs:

| Helper | Purpose |
| --- | --- |
| `scope.mkApplication` | Console-script application package. |
| `scope.mkVenv` | Virtual environment, optionally editable. |
| `scope.mkPytestCheck` | pytest derivation for `checks`. |
| `scope.nixpkgs.package` | One nixpkgs-compatible package export. |
| `scope.pythonSet` | Advanced pyproject.nix package set access. |

uvloom does not own your outputs. Put helpers wherever your flake needs them.

## Start from a template

```sh
nix flake init -t github:fornybar/uvloom#simple
# or
nix flake init -t github:fornybar/uvloom#editable
# or
nix flake init -t github:fornybar/uvloom#pytest
```

Then refresh lock and check:

```sh
uv lock
nix flake check
```

## Common outputs

### Application wrapper

Use when project exposes a console script:

```nix
packages.${system}.default = scope.mkApplication {
  package = "my-project";
};
```

If workspace has exactly one local package, `package` can be omitted.

### Virtual environment

```nix
packages.${system}.env = scope.mkVenv {
  name = "my-project-env";
};
```

Include all dependency groups:

```nix
packages.${system}.dev = scope.mkVenv {
  name = "my-project-dev-env";
  dependencies = project.workspace.deps.all;
};
```

### pytest check

```nix
checks.${system}.pytest = scope.mkPytestCheck {
  package = "my-project";
  groups = [ "test" ];
  paths = [ "tests" ];
  pytestFlags = [ "-q" ];
};
```

### Editable development shell

Expose an editable venv:

```nix
devShells.${system}.default = pkgs.mkShell {
  packages = [
    (scope.mkVenv {
      name = "my-project-dev-env";
      editable = {
        root = "$PWD";
        members = [ "my-project" ];
      };
    })
    pkgs.uv
  ];

  env = {
    UV_PYTHON = pkgs.lib.getExe scope.interpreter;
    UV_PYTHON_DOWNLOADS = "never";
  };
};
```

Use editable mode for development only. Release packages should use normal store source.

## Package overrides

Pass pyproject.nix package-set overlays to `forPython`:

```nix
scope = project.forPython {
  inherit pkgs;
  interpreter = pkgs.python312;
  overlays = [
    (final: prev: {
      my-project = prev.my-project.overrideAttrs (old: {
        nativeBuildInputs = (old.nativeBuildInputs or [ ]) ++ [ pkgs.pkg-config ];
      });
    })
  ];
};
```

These are uv2nix-style package-set overlays, not nixpkgs flake overlays.

## nixpkgs-style exports

Expose generated packages to consumers who expect `python.withPackages` or `pythonPackages.my-project`:

```nix
overlays.default = project.nixpkgs.overlay {
  packages = [ "my-project" ];
};
```

Consumer:

```nix
pkgs = import nixpkgs {
  inherit system;
  overlays = [ my-project.overlays.default ];
};

pkgs.python3.withPackages (ps: [ ps.my-project ])
```

Export dependencies explicitly when consumers need locked versions that nixpkgs does not provide:

```nix
overlays.default = project.nixpkgs.overlay {
  packages = [ "my-project" "locked-dependency" ];
};
```

## Inline scripts

For PEP 723 scripts:

```nix
script = uvloom.lib.loadScript {
  script = ./scripts/tool.py;
};

scope = script.forPython {
  inherit pkgs;
  interpreter = pkgs.python312;
};

packages.${system}.tool = scope.mkApplication { };
```

For live script development, add `scope.mkVenv { }` to a dev shell and run:

```sh
python scripts/tool.py
```

Or add `scope.mkEditableApplication { path = "scripts/tool.py"; }` to the shell and run `tool`. It includes a venv by default.

Create script lock with:

```sh
uv lock --script scripts/tool.py
```

## Escape hatches

Use helpers first. Drop lower when needed:

- `project.workspace`: raw upstream `uv2nix` workspace.
- `scope.pythonSet`: final pyproject.nix package set.
- `project.nixpkgs.pythonPackagesExtension`: package-set export adapter.
- `project.nixpkgs.overlay`: flake-overlay export convenience.
- `scope.nixpkgs.package`: direct one-package export.

## Where next

- New project: [Tutorial](tutorial.md).
- Recipes: [How-to guides](how-to.md).
- Exact arguments: [Reference](reference.md).
- Deeper model: [Explanation](explanation.md).
