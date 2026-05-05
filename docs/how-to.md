# How-to guides

Copy these recipes into an existing uvloom flake. Replace `my-project` with the `[project].name` from `pyproject.toml`.

## Add uvloom to an existing flake

Add input:

```nix
inputs = {
  nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
  uvloom.url = "github:fornybar/uvloom";
  uvloom.inputs.nixpkgs.follows = "nixpkgs";
};
```

Load project once, then create a scope per system:

```nix
outputs = { nixpkgs, uvloom, ... }:
  let
    systems = [ "x86_64-linux" "aarch64-linux" "x86_64-darwin" "aarch64-darwin" ];
    forAllSystems = nixpkgs.lib.genAttrs systems;
    project = uvloom.lib.loadProject { root = ./.; };
  in
  {
    packages = forAllSystems (system:
      let
        pkgs = nixpkgs.legacyPackages.${system};
        scope = project.forPython {
          inherit pkgs;
          interpreter = pkgs.python312;
        };
      in
      {
        default = scope.mkApplication { package = "my-project"; };
      });
  };
```

## Let uvloom choose Python

If `requires-python` can be satisfied by a Python interpreter in nixpkgs, you may omit `interpreter`:

```nix
scope = project.forPython { inherit pkgs; };
```

Pass an interpreter explicitly when you need reproducible interpreter choice or a custom Python:

```nix
scope = project.forPython {
  inherit pkgs;
  interpreter = pkgs.python312;
};
```

## Build an application wrapper

Use this when `pyproject.toml` defines console scripts:

```toml
[project.scripts]
my-project = "my_project:main"
```

Expose wrapper:

```nix
packages.${system}.default = scope.mkApplication {
  package = "my-project";
};
```

Single-package workspaces can omit `package`:

```nix
packages.${system}.default = scope.mkApplication { };
```

Override wrapper metadata if needed:

```nix
packages.${system}.default = scope.mkApplication {
  package = "my-project";
  pname = "my-cli";
  version = "1.2.3";
};
```

## Build a virtual environment

Build default dependency environment:

```nix
packages.${system}.env = scope.mkVenv {
  name = "my-project-env";
};
```

Include all dependency groups from `uv2nix`:

```nix
packages.${system}.dev = scope.mkVenv {
  name = "my-project-dev-env";
  dependencies = project.workspace.deps.all;
};
```

Use a custom dependency selection when upstream `uv2nix` exposes one you need:

```nix
packages.${system}.docs = scope.mkVenv {
  name = "my-project-docs-env";
  dependencies = { my-project = [ "docs" ]; };
};
```

## Run pytest in `nix flake check`

```nix
checks.${system}.pytest = scope.mkPytestCheck {
  package = "my-project";
};
```

Common options:

```nix
checks.${system}.pytest = scope.mkPytestCheck {
  package = "my-project";
  groups = [ "test" ];
  paths = [ "tests" ];
  pytestFlags = [ "-q" ];
  env = {
    MY_SETTING = "test";
  };
};
```

Run:

```sh
nix flake check
```

## Create editable development environment

Use editable mode when imports and console scripts should see working-tree source without rebuilding package derivations after every edit.

Expose an editable venv in a dev shell:

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

Enter shell:

```sh
nix develop
```

Editable config is explicit. For multi-package workspaces, list editable local packages explicitly:

```nix
editable = {
  root = "$PWD";
  members = [ "my-app" "my-library" ];
};
```

Include dev/test dependencies in editable environment:

```nix
(scope.mkVenv {
  name = "my-project-dev-env";
  editable = {
    root = "$PWD";
    members = [ "my-project" ];
  };
  dependencies = project.workspace.deps.all;
})
```

## Add a package override

Use pyproject.nix package-set overlays when a locked Python package needs extra build inputs or attribute changes. These overlays are passed to `pythonSet.overrideScope`; they are not nixpkgs flake overlays.

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

Capture `pkgs` from the surrounding Nix scope when an override needs nixpkgs packages.

## Prefer source distributions

uvloom defaults to `sourcePreference = "wheel"`. Prefer sdists when a package must be built from source:

```nix
scope = project.forPython {
  inherit pkgs;
  interpreter = pkgs.python312;
  sourcePreference = "sdist";
};
```

## Export packages to nixpkgs-style Python sets

Use this when consumers should use normal nixpkgs patterns such as `python3.withPackages` or `python3Packages.my-project`.

Common flake overlay:

```nix
let
  project = uvloom.lib.loadProject { root = ./.; };
in
{
  overlays.default = project.nixpkgs.overlay {
    packages = [ "my-project" ];
  };
}
```

Consumer:

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

List dependencies explicitly when they are missing from nixpkgs or must come from the lock file:

```nix
overlays.default = project.nixpkgs.overlay {
  packages = [
    "my-project"
    "locked-dependency"
  ];
};
```

Need nixpkgs `final` while building pyproject overlays? Write the overlay explicitly:

```nix
overlays.default = final: prev: {
  pythonPackagesExtensions = (prev.pythonPackagesExtensions or [ ]) ++ [
    (project.nixpkgs.pythonPackagesExtension {
      packages = [ "my-project" ];
      overlays = [
        (config.patches.my-project { pkgs = final; })
      ];
    })
  ];
};
```

Need a customization after uvloom exports packages to nixpkgs style? Append another Python package-set extension after uvloom's extension:

```nix
overlays.default = final: prev: {
  pythonPackagesExtensions = (prev.pythonPackagesExtensions or [ ]) ++ [
    (project.nixpkgs.pythonPackagesExtension {
      packages = [ "my-project" ];
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

## Build one nixpkgs-compatible package from a scope

Use this when you already have a scope and only need one exported package:

```nix
packages.${system}.nixpkgs-style = scope.nixpkgs.package {
  package = "my-project";
};
```

By default, uvloom exports the selected package into a temporary nixpkgs-style Python package set. Pass `exportPackages` when that package needs additional locked dependencies exported too:

```nix
packages.${system}.nixpkgs-style = scope.nixpkgs.package {
  package = "my-project";
  exportPackages = [ "my-project" "locked-dependency" ];
};
```

## Build a PEP 723 inline script

For a script with inline metadata:

```python
# /// script
# requires-python = ">=3.12"
# dependencies = ["tqdm"]
# ///

from tqdm import tqdm
```

Load and build it:

```nix
script = uvloom.lib.loadScript {
  script = ./scripts/progress.py;
};

scope = script.forPython {
  inherit pkgs;
  interpreter = pkgs.python312;
};

packages.${system}.progress = scope.mkApplication { };
```

For development, put the script dependency venv in a shell and run the working-tree file with Python:

```nix
devShells.${system}.default = pkgs.mkShell {
  packages = [
    (scope.mkVenv { })
  ];
};
```

```sh
nix develop
python scripts/progress.py
```

Script edits are picked up on the next run. Re-enter the shell only when dependencies, lock file, or interpreter change.

If you want a command alias in the dev shell, add an editable application. `path` is relative to `root`; `root = "$PWD"` keeps the wrapper pointed at the live checkout:

```nix
devShells.${system}.default = pkgs.mkShell {
  packages = [
    (scope.mkEditableApplication { path = "scripts/progress.py"; })
  ];
};
```

```sh
nix develop
progress
```

`mkEditableApplication` includes a script dependency venv by default. Add `scope.mkVenv { }` separately only when you also want to run the script directly with `python scripts/progress.py`.

`loadScript` expects a uv script lock at `./scripts/progress.py.lock` by default. Create or refresh it with uv:

```sh
uv lock --script scripts/progress.py
```

Load every `.py` script in a directory:

```nix
scripts = uvloom.lib.loadScripts { root = ./scripts; };
progressScope = scripts.progress.forPython { inherit pkgs; };
```

## Troubleshoot common errors

| Error | Meaning | Fix |
| --- | --- | --- |
| `uvloom.forPython: unknown sourcePreference ...` | `sourcePreference` is not supported by build-system overlays. | Use `"wheel"` or `"sdist"`. |
| `uvloom.forPython: overlays must be a list` | `overlays` got an attrset or function directly. | Wrap overlays in `[ ... ]`. |
| `uvloom.mkVenv: editable.root must be a string` | Editable root was not a shell-time path string. | Use `root = "$PWD";`. |
| `uvloom.mkApplication: could not infer package; candidates: ...` | Workspace has multiple local packages. | Pass `package = "..."`. |
| `uvloom.mkPytestCheck: package ... not found` | Package name does not match a local package. | Check `[project].name` and workspace members. |
| `could not infer interpreter for requires-python ...` | No nixpkgs Python matches metadata. | Pass a compatible `interpreter` explicitly or change `requires-python`. |

## Use lower-level uv2nix APIs

Supported escape hatches:

- `project.workspace`: upstream `uv2nix` workspace.
- `scope.pythonSet`: final pyproject.nix package set.
- `project.nixpkgs.pythonPackagesExtension`: package-set export adapter.
- `project.nixpkgs.overlay`: flake-overlay convenience wrapper.
- `scope.nixpkgs.package`: one-package nixpkgs-style export.

If your flake mostly needs custom `uv2nix` composition, use `uv2nix` and `pyproject-nix` directly.
