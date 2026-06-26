# Tutorial: first uvloom project

Goal: create a small Python application from a template, refresh its `uv.lock`, then build and test it with Nix.

## Prerequisites

- Nix with flakes enabled.
- `uv` available on `PATH`.
- Internet access for first dependency fetch.

## 1. Create a project

```sh
mkdir my-project
cd my-project
nix flake init -t github:fornybar/uvloom#simple
```

Template creates:

| Path | Purpose |
| --- | --- |
| `flake.nix` | Nix outputs built with uvloom. |
| `pyproject.toml` | Python project metadata, scripts, dependencies. |
| `uv.lock` | Locked Python dependency graph. |
| `src/smiley_plot/` | Example package. |
| `tests/` | Smoke test you can keep or replace. |

## 2. Rename package

Edit `pyproject.toml`:

```toml
[project]
name = "my-project"
```

If you also rename the Python module, update the script target and tests:

```toml
[project.scripts]
my-project = "my_project:main"
```

Then update `flake.nix` package names:

```nix
packages.default = scope.app { package = "my-project"; };
```

In a multi-system flake this appears as `packages.${system}.default`.

## 3. Refresh lock file

```sh
uv lock
```

Commit `uv.lock`. uvloom reads `pyproject.toml` and `uv.lock` through `uv2nix`; it does not resolve Python dependencies during Nix evaluation.

## 4. Build application

```sh
nix build
```

`result` points to the built application wrapper. Run it:

```sh
./result/bin/my-project
```

If you kept the template name, command is:

```sh
./result/bin/smiley-plot
```

Need one app output per script from multi-script package? Use package mode with `script`:

```nix
packages.${system}.first-tool = scope.app {
  package = "multi-script-app";
  script = "first-tool";
};
```

That output exposes only `bin/first-tool`.

## 5. Run checks

```sh
nix flake check
```

The `simple` template mainly proves the package builds. If you want pytest wired in from the start, use the pytest template:

```sh
nix flake init -t github:fornybar/uvloom#pytest
```

Or add the check yourself:

```nix
checks.${system}.pytest = scope.check.pytest {
  package = "my-project";
};
```

## 6. See the uvloom pattern

Open `flake.nix`. Important lines:

```nix
project = uvloom.lib.project.load { root = ./.; };

scope = project.forPython {
  inherit pkgs;
  interpreter = pkgs.python312;
};
```

- `project` loads workspace metadata once.
- `scope` selects nixpkgs, Python, dependency selection, and overlays.
- Helpers such as `scope.app`, `scope.venv`, and `scope.check.pytest` become normal flake outputs.

## 7. Add a development shell

For source changes without rebuilding after every edit, use editable mode. Easiest start:

```sh
nix flake init -t github:fornybar/uvloom#editable
```

For an existing flake, see [Create editable development environment](how-to.md#create-editable-development-environment).

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| `package ... not found` | Match `package = "..."` to `[project].name` in `pyproject.toml`. |
| `could not infer package; candidates: ...` | Pass `package = "..."` explicitly in multi-package workspaces. |
| Source changes do not show up in `nix develop` | Use `scope.venv { editable = { members = [ "my-project" ]; }; }` and `shellHook = scope.hook;`. |
| Python version mismatch | Pass `interpreter = pkgs.python312;` or another interpreter matching `requires-python`. |

## Next steps

- Need recipes? See [How-to guides](how-to.md).
- Need exact arguments? See [Reference](reference.md).
- Need concepts? See [Explanation](explanation.md).
