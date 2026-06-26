# Explanation

uvloom keeps common `uv2nix` flakes small while leaving flake ownership with you.

It does not replace `uv2nix`. It packages the repeated composition steps behind a small, stable helper API and leaves escape hatches open when you need lower-level control.

## Why project and scope are separate

Most flakes start with two values:

```nix
project = uvloom.lib.project.load { root = ./.; };

scope = project.forPython {
  inherit pkgs;
  interpreter = pkgs.python312;
};
```

`project` is Python-workspace information from `pyproject.toml` and `uv.lock`.

`scope` is Nix build context:

- nixpkgs package set
- Python interpreter
- dependency selection
- build-system source preference
- pyproject.nix overlays
- environment and stdenv

Split lets one locked project be reused across systems, Python versions, overlays, and output types.

## Build pipeline

At a high level:

1. `uv` writes `uv.lock`.
2. `uv2nix` loads workspace metadata and dependency selections.
3. uvloom composes build-system overlay, workspace overlay, and user overlays.
4. pyproject.nix builds a `pythonSet`.
5. uvloom helpers turn that package set into flake outputs.

Helpers all use the same composed package set unless you ask for a different dependency selection.

## Helpers versus package set

Use helpers for normal flake outputs:

| Helper | Use for |
| --- | --- |
| `app` | Console-script wrappers under `packages`; optional `script` selects one executable from package venv. |
| `venv` | Virtual environments under `packages` or shells, including editable development envs. |
| `check.pytest` | pytest derivations under `checks`. |
| `scope.nixpkgs.package` | one nixpkgs-compatible package export. |

Use `scope.pythonSet` when a helper is too high-level. Common reasons:

- inspect generated package attrs
- write custom derivation
- override package internals
- call pyproject.nix APIs directly

## Dependencies

`uv.lock` remains dependency source. uvloom does not invent dependency resolution.

Default project scopes use:

```nix
project.workspace.deps.default
```

Pass another dependency selection when output needs extras or groups:

```nix
scope.venv {
  name = "my-project-dev-env";
  dependencies = project.workspace.deps.all;
}
```

`check.pytest` defaults differently: it builds a test scope with dependency selection equivalent to:

```nix
{ my-project = [ "test" ]; }
```

Override `groups` for common cases, or `dependencies` for full control.

## Package app script selection

Package mode default exposes executables from package application output. For multi-script distributions, use `script` to narrow one app to one executable:

```nix
scope.app {
  package = "multi-script-app";
  script = "first-tool";
}
```

Script mode creates `$out/bin/first-tool` only. Binary rename is intentionally unsupported: output binary name always equals `script`; `name` is rejected; `pname` remains metadata-only.

## Package inference

Several helpers accept `package ? null`.

Omitting `package` works only when workspace has exactly one local package. In multi-package workspaces, pass package names explicitly:

```nix
scope.app { package = "my-app"; }
scope.check.pytest { package = "my-library"; }
```

This avoids accidental builds when workspace membership changes.

## Editable mode

Normal Nix package builds copy source into the store. After changing source files, rebuild to see changes.

Editable mode on `venv` adds a pyproject.nix editable overlay so selected workspace members import from your checkout instead:

```nix
scope.venv {
  name = "my-project-dev-env";
  editable = {
    members = [ "my-project" ];
  };
}
```

Use editable mode for dev shells, REPLs, language servers, and fast test loops. Avoid using it for release packages because it intentionally points at a mutable working tree.

Editable `root` defaults to `"$REPO_ROOT"`, a runtime shell variable. `scope.hook` exports `REPO_ROOT` for dev shells so the environment follows the checkout path instead of a Nix store path. Override `editable.root` only for nonstandard layouts.

Do not combine uvloom `venv` environments with `uv sync`. A uvloom venv is a Nix store output built through uv2nix; `uv sync` creates or mutates a separate `.venv` and bypasses uv2nix overlays, package fixes, and Nix-built dependencies. Use `uv lock` to update the lock file, then rebuild or reload the Nix shell so uvloom can rebuild its environment from `uv.lock`.

## Overlay layers

uvloom uses two different overlay concepts. Mixing them up is the most common advanced-use mistake.

### pyproject.nix package-set overlays

Passed to `project.forPython { overlays = [ ... ]; }` or `project.nixpkgs.pythonPackagesExtension { overlays = [ ... ]; }`.

They run inside uv2nix/pyproject.nix composition:

```nix
overlays = [
  (final: prev: {
    my-project = prev.my-project.overrideAttrs (old: {
      nativeBuildInputs = (old.nativeBuildInputs or [ ]) ++ [ pkgs.pkg-config ];
    });
  })
];
```

Use these to fix generated Python package builds.

### nixpkgs flake overlays

Returned by `project.nixpkgs.overlay`. They run at nixpkgs level and append a Python package-set extension to `pythonPackagesExtensions`:

```nix
overlays.default = project.nixpkgs.overlay {
  packages = [ "my-project" ];
};
```

Use these when consumers should access your package through nixpkgs conventions.

## Exporting to nixpkgs style

uv2nix builds environments from a lockfile-oriented package set. nixpkgs users often expect `python.withPackages` and `pythonPackages`.

uvloom export adapters bridge those worlds:

- `project.nixpkgs.pythonPackagesExtension` creates a Python package-set extension.
- `project.nixpkgs.overlay` appends that extension in a flake overlay.
- `scope.nixpkgs.package` exports and returns one package directly.

Export only packages consumers need. If a locked dependency is absent from nixpkgs or must use lockfile version, include it in `packages` or `exportPackages` explicitly.

After export, dependency resolution follows nixpkgs Python package-set rules. That is useful for integration, but different from uv2nix virtualenv resolution.

## Script support

`inline.load` is the script-shaped sibling of `project.load`.

Use it for PEP 723 inline-metadata scripts with `uv` script locks:

```nix
script = uvloom.lib.inline.load { path = ./scripts/tool.py; };
scope = script.forPython { inherit pkgs; };
packages.${system}.tool = scope.app { };
```

For development, put `scope.venv { }` in a dev shell and run `python scripts/tool.py`. That uses locked deps while reading the live working-tree script. If you want a command alias, put `scope.app.editable { path = "scripts/tool.py"; }` in the shell; it includes a venv by default.

Use `project.load` for packages/workspaces. Use `inline.load` for single-file scripts.

## When to use uv2nix directly

Use uvloom when your flake matches these patterns:

- build app wrapper
- build virtualenv
- run pytest
- make editable dev shell
- export locked package to nixpkgs style
- add focused package-set overlays

Use upstream `uv2nix` directly when you need to replace the composition pipeline itself or depend on upstream workspace internals beyond uvloom's documented escape hatches.

## Escape hatches

Stable seams:

- `project.workspace`: raw upstream `uv2nix` workspace.
- `scope.pythonSet`: final pyproject.nix package set.
- `project.nixpkgs.pythonPackagesExtension`: package-set export adapter.
- `project.nixpkgs.overlay`: flake-overlay export convenience.
- `scope.nixpkgs.package`: direct one-package export.

Anything deeper belongs to uv2nix or pyproject.nix. uvloom keeps those layers reachable instead of wrapping every possible upstream API.
