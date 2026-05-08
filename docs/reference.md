# Reference

Stable user-facing uvloom API. Generated API docs include fuller comments from `uvloom.lib`.

## API stability

```nix
uvloom.lib.apiVersion
```

Current documented API version: `1`.

## Projects

### `uvloom.lib.loadProject`

Load a `uv` workspace from `pyproject.toml` and `uv.lock`.

```nix
project = uvloom.lib.loadProject { root = ./.; };
```

Arguments:

| Argument | Required | Meaning |
| --- | --- | --- |
| `root` | Yes | Project root containing `pyproject.toml` and `uv.lock`. |

Returns:

| Attribute | Meaning |
| --- | --- |
| `project.workspace` | Raw upstream `uv2nix` workspace. Escape hatch for `workspace.deps.*`, `mkPyprojectOverlay`, and related upstream APIs. |
| `project.forPython` | Create one build scope for one nixpkgs package set and interpreter. |
| `project.nixpkgs.pythonPackagesExtension` | Export selected locked packages as a nixpkgs Python package-set extension. |
| `project.nixpkgs.overlay` | Flake-overlay convenience wrapper around `pythonPackagesExtension`. |

### `project.forPython`

Create a build scope:

```nix
scope = project.forPython {
  inherit pkgs;
  interpreter = pkgs.python312;
};
```

Arguments:

| Argument | Default | Meaning |
| --- | --- | --- |
| `pkgs` | Required | nixpkgs package set for target system. |
| `interpreter` | inferred | Python interpreter derivation. If omitted, uvloom chooses one matching workspace `requires-python` when possible. |
| `sourcePreference` | `"wheel"` | Build-system overlay preference, usually `"wheel"` or `"sdist"`. |
| `dependencies` | `project.workspace.deps.default` | uv2nix dependency selection used by generated workspace overlay. |
| `overlays` | `[ ]` | Extra pyproject.nix package-set overlays. Must be a list. |
| `environ` | `{ }` | Environment passed to upstream workspace overlay. |
| `stdenv` | `pkgs.stdenv` | stdenv used by pyproject.nix builds and checks. |

Returns scope helpers:

| Attribute | Meaning |
| --- | --- |
| `scope.interpreter` | Resolved Python interpreter derivation. |
| `scope.pythonSet` | Final pyproject.nix package set. |
| `scope.mkVenv` | Build virtual environment. Accepts `editable` for working-tree source. |
| `scope.mkApplication` | Build console-script application wrapper. |
| `scope.mkPytestCheck` | Build pytest derivation for `checks`. |
| `scope.nixpkgs.package` | Export and return one nixpkgs-compatible package. |

## Scope helpers

### `scope.interpreter`

Resolved Python interpreter. Useful in dev shells:

```nix
env = {
  UV_NO_SYNC = "1";
  UV_PYTHON = pkgs.lib.getExe scope.interpreter;
  UV_PYTHON_DOWNLOADS = "never";
};

shellHook = ''
  unset PYTHONPATH
'';
```

### `scope.mkVenv`

Build virtual environment.

```nix
scope.mkVenv {
  name = "my-project-env";
}
```

Build editable virtual environment:

```nix
scope.mkVenv {
  name = "my-project-dev-env";
  editable = {
    root = "$PWD";
    members = [ "my-project" ];
  };
}
```

Arguments:

| Argument | Default | Meaning |
| --- | --- | --- |
| `name` | Required | Derivation/environment name. |
| `dependencies` | `project.workspace.deps.default` | uv2nix dependency selection. |
| `editable` | `false` | `false` for store-source venv, or an attrset like `{ root = "$PWD"; members = [ "my-project" ]; }` for working-tree source. |

### `scope.mkApplication`

Build console-script application wrapper for a local package.

```nix
scope.mkApplication {
  package = "my-project";
}
```

Arguments:

| Argument | Default | Meaning |
| --- | --- | --- |
| `package` | inferred | Local package name. May be omitted only when workspace has exactly one local package. |
| `venv` | generated | Virtual environment used by wrapper. |
| `pname` | package metadata | Override output package name. |
| `version` | package metadata | Override output version. |

### `scope.mkPytestCheck`

Build pytest derivation for `checks`.

```nix
scope.mkPytestCheck {
  package = "my-project";
  groups = [ "test" ];
  paths = [ "tests" ];
  pytestFlags = [ "-q" ];
}
```

Arguments:

| Argument | Default | Meaning |
| --- | --- | --- |
| `package` | inferred | Local package under test. May be omitted only when workspace has exactly one local package. |
| `groups` | `[ "test" ]` | Optional dependency groups included when `dependencies = null`. |
| `dependencies` | `null` | Full uv2nix dependency selection override. When null, uvloom uses `{ ${package} = groups; }`. |
| `name` | `${package}-pytest` | Check derivation name. |
| `paths` | `[ "tests" ]` | Paths passed to pytest. |
| `pytestFlags` | `[ ]` | Extra pytest arguments. |
| `env` | `{ }` | Environment variables for check derivation. |
| `nativeBuildInputs` | `[ ]` | Extra native build inputs for check derivation. |

### `scope.pythonSet`

Final pyproject.nix package set after build-system overlay, workspace overlay, and user overlays.

Use for advanced package overrides, custom derivations, and interop with pyproject.nix APIs.

### `scope.nixpkgs.package`

Return one nixpkgs-compatible package directly from a scope.

```nix
packages.${system}.nixpkgs-style = scope.nixpkgs.package {
  package = "my-project";
};
```

Arguments:

| Argument | Default | Meaning |
| --- | --- | --- |
| `package` | inferred | Local package to return. |
| `exportPackages` | `[ package ]` | Packages exported into temporary nixpkgs-style Python package set. Add locked dependencies here when needed. |

## nixpkgs export helpers

### `project.nixpkgs.overlay`

Create a nixpkgs flake overlay that appends uvloom's export adapter to `pythonPackagesExtensions`.

```nix
overlays.default = project.nixpkgs.overlay {
  packages = [ "my-project" ];
};
```

This is convenience syntax for appending `project.nixpkgs.pythonPackagesExtension args`:

```nix
final: prev: {
  pythonPackagesExtensions = (prev.pythonPackagesExtensions or [ ]) ++ [
    (project.nixpkgs.pythonPackagesExtension args)
  ];
}
```

### `project.nixpkgs.pythonPackagesExtension`

Create a nixpkgs-style Python package-set extension.

```nix
python = pkgs.python312.override {
  self = python;
  packageOverrides = project.nixpkgs.pythonPackagesExtension {
    packages = [ "my-project" ];
  };
};
```

Arguments:

| Argument | Default | Meaning |
| --- | --- | --- |
| `packages` | local workspace packages | Generated packages to export into nixpkgs-style package set. |
| `sourcePreference` | `"wheel"` | Build-system overlay preference. |
| `dependencies` | `project.workspace.deps.default` | uv2nix dependency selection. |
| `overlays` | `[ ]` | pyproject.nix package-set overlays applied before export. |
| `environ` | `{ }` | Environment passed to workspace overlay. |
| `stdenv` | package set default | stdenv used by builds. |

List dependencies explicitly when they are missing from nixpkgs or need lockfile versions:

```nix
project.nixpkgs.pythonPackagesExtension {
  packages = [
    "my-project"
    "locked-dependency"
  ];
}
```

## Scripts

### `uvloom.lib.loadScript`

Load a PEP 723 inline-metadata script.

```nix
script = uvloom.lib.loadScript {
  script = ./scripts/tool.py;
};
```

Arguments:

| Argument | Default | Meaning |
| --- | --- | --- |
| `script` | Required | Python script containing inline metadata. |
| `lockPath` | `${script}.lock` | uv script lock file. |
| `config` | `{ }` | uv2nix script config overrides. |

Returns:

| Attribute | Meaning |
| --- | --- |
| `script.name` | Script basename without `.py`. |
| `script.metadata` | Parsed inline script metadata. |
| `script.config` | Loaded script config. |
| `script.raw` | Raw upstream uv2nix script value. |
| `script.forPython` | Create one script scope. |

### `script.forPython`

```nix
scope = script.forPython {
  inherit pkgs;
  interpreter = pkgs.python312;
};
```

Arguments mirror project scopes: `pkgs`, optional `interpreter`, `sourcePreference`, `overlays`, `environ`, `workspaceRoot`, and `stdenv`.

Script scope helpers:

| Helper | Meaning |
| --- | --- |
| `scope.pythonSet` | Package set containing script dependencies. |
| `scope.mkVenv { }` | Build script virtual environment. |
| `scope.renderScript { }` | Render script with venv shebang. |
| `scope.mkApplication { }` | Build runnable script application. |
| `scope.mkEditableApplication { path ? basename, root ? "$PWD", venv ? mkVenv { } }` | Build dev-shell command that runs the live working-tree script with locked deps. |

### `uvloom.lib.loadScripts`

Load all `.py` inline-metadata scripts from a directory.

```nix
scripts = uvloom.lib.loadScripts {
  root = ./scripts;
};
```

Arguments:

| Argument | Default | Meaning |
| --- | --- | --- |
| `root` | Required | Directory containing scripts. |
| `config` | `{ }` | uv2nix script config overrides for each script. |

Result keys are script filenames without `.py`.

## Check commands

```sh
nix build
nix flake check
nix build .#docs
```
