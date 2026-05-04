# Tutorial: first uvloom project

Goal: create a small Python project from a template, lock dependencies with `uv`, then build and test with Nix.

## Prerequisites

- Nix with flakes enabled
- `uv`

## 1. Create project

```sh
mkdir my-project
cd my-project
nix flake init -t github:fornybar/uvloom#simple
```

Template gives you:

- `flake.nix`: Nix outputs
- `pyproject.toml`: Python package metadata
- `uv.lock`: Python dependency lock file
- `tests/`: smoke test

## 2. Rename package

Edit `pyproject.toml`:

```toml
[project]
name = "my-project"
```

If you also rename Python modules, update console scripts and tests to match.

## 3. Refresh lock file

```sh
uv lock
```

Keep `uv.lock` in version control. uvloom reads `pyproject.toml` and `uv.lock` through `uv2nix`.

## 4. Build

```sh
nix build
```

`result` points to the built package or application wrapper from the template.

## 5. Test

```sh
nix flake check
```

This runs checks declared by the template.

## 6. See the pattern

Open `flake.nix`. Main uvloom shape:

```nix
project = uvloom.lib.loadProject { root = ./.; };

scope = project.forPython {
  inherit pkgs;
  interpreter = pkgs.python312;
};
```

- `project` loads workspace metadata once.
- `scope` chooses nixpkgs and Python.
- Helpers like `scope.mkApplication` and `scope.mkPytestCheck` become normal flake outputs.

## 7. Next step

- Need `nix develop`? See [Create editable development environment](how-to.md#create-editable-development-environment).
- Need tests in CI? See [Run pytest in `nix flake check`](how-to.md#run-pytest-in-nix-flake-check).
- Need API details? See [Reference](reference.md).
