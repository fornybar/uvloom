# Reference

Stable user-facing uvloom API. Generated API docs include fuller comments from `uvloom.lib`.

## API stability

```nix
uvloom.lib.apiVersion
```

Current documented API version: `2`.

## Projects

### `uvloom.lib.project.load`

Load a `uv` workspace from `pyproject.toml` and `uv.lock`.

```nix
project = uvloom.lib.project.load { root = ./.; };
```

Arguments:

| Argument | Required | Meaning |
| --- | --- | --- |
| `root` | Yes | Project root containing `pyproject.toml` and `uv.lock`. |
| `forgeFetch` | No | Project-wide forge fetch config. Defaults to `"auto"`. |
| `fetcher` | No | Registry artifact fetch mode. Defaults to `"auto"`; authenticated indexes marked `authenticate = "always"` use evaluator-side fetching. |

Returns:

| Attribute | Meaning |
| --- | --- |
| `project.root` | Root path passed to `project.load`. Useful for wrappers, shells, and commands needing workspace cwd. |
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
| `forgeFetch` | project default | Override project-wide forge fetch config for this scope. |
| `fetcher` | project default | `"auto"` fetches artifacts from authenticated indexes during evaluation; `"evaluator"` fetches all locked registry artifacts during evaluation; `"nixpkgs"` disables evaluator fetching. |

Returns scope helpers:

| Attribute | Meaning |
| --- | --- |
| `scope.interpreter` | Resolved Python interpreter derivation. |
| `scope.pythonSet` | Final pyproject.nix package set. |
| `scope.venv` | Build virtual environment. Accepts `editable` for working-tree source. |
| `scope.app` | Build console-script application wrapper. |
| `scope.check.pytest` | Build pytest derivation for `checks`. |
| `scope.nixpkgs.package` | Export and return one nixpkgs-compatible package. |

## Scope helpers

### `scope.interpreter`

Resolved Python interpreter.

### `scope.hook` and `scope.hooks`

Shell hook fragments for Nix dev shells. `scope.hook` is the default hook:

```nix
shellHook = scope.hook;
```

It exports `REPO_ROOT` when unset, configures `uv` to use the Nix interpreter, and unsets `PYTHONPATH`.

Pieces are available as `scope.hooks.repoRoot`, `scope.hooks.uv`, and `scope.hooks.python` when you need custom composition. If you already have a shell hook, append it after `scope.hook`:

```nix
shellHook = ''
  ${scope.hook}
  echo "ready"
'';
```

### `scope.venv`

Build virtual environment.

```nix
scope.venv {
  name = "my-project-env";
}
```

Build editable virtual environment:

```nix
scope.venv {
  name = "my-project-dev-env";
  editable = {
    members = [ "my-project" ];
  };
}
```

Arguments:

| Argument | Default | Meaning |
| --- | --- | --- |
| `name` | Required | Derivation/environment name. |
| `dependencies` | parent scope `dependencies` | uv2nix dependency selection installed into the venv. |
| `editable` | `false` | `false` for store-source venv, `true` for all local members with `root = "$REPO_ROOT"`, or an attrset like `{ members = [ "my-project" ]; }`. `root` defaults to `"$REPO_ROOT"` and can be overridden. |

Virtual projects remain in the dependency selection. uv2nix propagates their dependencies without installing the virtual project itself.

### `scope.app`

Build application wrapper from local package (package mode) or explicit command (command mode).

Package mode example:

```nix
scope.app {
  package = "my-project";
}
```

Command mode example (for non-package/source-tree apps):

```nix
scope.app {
  name = "my-project";
  command = [ "python" ./app.py ];
  pythonPath = [ ./. ];
}
```

Command mode accepts list commands only. Do not pass shell string like `"python app.py"`.

#### Package mode arguments

| Argument | Default | Meaning |
| --- | --- | --- |
| `package` | inferred | Local package name. May be omitted only when workspace has exactly one local package. |
| `script` | `null` | Select one executable basename from `${venv}/bin/${script}`. When set, output exposes only `$out/bin/${script}`. |
| `venv` | generated | Virtual environment used by wrapper. |
| `pname` | package metadata | Override derivation `pname`. In script mode this does not rename output binary. |
| `version` | package metadata | Override output version. |

#### Script mode notes

When `script` is set in package mode:

- uvloom links exactly one executable from `${venv}/bin/${script}` into `$out/bin/${script}`.
- `script` selects executable basename from venv `bin`; executable may come from project scripts, dependency installs, or other build-time executables in venv.
- Output binary name is always `script`.
- `name` is rejected in script mode.
- `pname` controls derivation metadata only.
- Omitting `script` keeps existing package mode behavior (all executables from package app output).

#### Command mode arguments

| Argument | Default | Meaning |
| --- | --- | --- |
| `name` | `pname` | Wrapper name. Required in command mode unless `pname` set. |
| `command` | `null` | Non-empty list of strings/paths, for example `[ "python" ./app.py ]`. |
| `venv` | generated | Virtual environment used by wrapper. |
| `pythonPath` | `[ ]` | Prepended to `PYTHONPATH`; existing `PYTHONPATH` preserved as suffix. |
| `workingDirectory` | `project root` | Directory wrapper changes into before running command. |

`pythonPath = [ ./. ]` helps source-tree imports, but can shadow installed modules. Prefer narrower paths when possible (for example `[ ./src ]` instead of repo root).

#### Validation rules

`scope.app` fails when:

- both `package` and `command` passed
- `command` passed as shell string
- `command` not list / empty list / contains values that are not strings or paths
- command mode used without `name`/`pname`
- `script` passed with command mode
- `script` not non-empty string
- `script` contains `/` in script mode
- `name` passed together with `script`
- script-mode `pname` not non-empty string or contains `/`

### `scope.check.pytest`

Build pytest derivation for `checks`.

```nix
scope.check.pytest {
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

### `uvloom.lib.inline.load`

Load a PEP 723 inline-metadata script.

```nix
script = uvloom.lib.inline.load {
  path = ./scripts/tool.py;
};
```

Arguments:

| Argument | Default | Meaning |
| --- | --- | --- |
| `path` | Required | Python script containing inline metadata. |
| `lockPath` | `path + ".lock"` | uv script lock file, for example `./scripts/tool.py.lock`. |
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
| `scope.venv { }` | Build script virtual environment. |
| `scope.render { }` | Render script with venv shebang. |
| `scope.app { }` | Build runnable script application. |
| `scope.app.editable { path ? basename, root ? "$REPO_ROOT", venv ? scope.venv { } }` | Build dev-shell command that runs the live working-tree script with locked deps. |

### `uvloom.lib.inline.fromDir`

Load all `.py` inline-metadata scripts from a directory.

```nix
scripts = uvloom.lib.inline.fromDir {
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

## Forge fetch

`forgeFetch` fetches locked Git dependencies from GitHub/GitLab through Nix's forge-aware `builtins.fetchTree` support. It defaults to `"auto"` for projects.

Accepted values:

| Value | Meaning |
| --- | --- |
| `null` | Disabled. |
| `"auto"` | Apply to all Git packages in `uv.lock`. Default. |
| `[ "pkg" ]` | Apply only to named packages. |
| `{ packages = [ "pkg" ]; }` | Explicit package-list form. |

Package names use Python package-name normalization.

Supported sources:

- GitHub and GitLab.com repositories.
- URL forms: `https://...`, `git+https://...`, `ssh://git@...`, and `git@host:owner/repo.git`.

Unsupported sources fail during evaluation with a `forgeFetch` error. `forgeFetch` supports locked uv Git URLs with `rev`/`branch`/`tag`, `subdirectory`, and commit fragments, including GitLab nested groups. Git submodules, Git LFS, and legacy `egg` fragments are not supported. User overlays run after `forgeFetch` and can still override package attributes.
