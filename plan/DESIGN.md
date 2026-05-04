# DESIGN

Design draft for `uvloom`.

This document builds on [`RESEARCH.md`](./RESEARCH.md) and reflects settled v1 interview decisions from [`INTERVIEW.md`](./INTERVIEW.md).

Status:
- draft
- v1 core API shape settled
- next focus: implementation, smoke checks, docs polish

---

## 1. Problem statement

Bare `uv2nix` is powerful and explicit, but common usage repeats lots of ceremony:
- three auxiliary inputs (`pyproject-nix`, `uv2nix`, `build-system-pkgs`)
- explicit `workspace` load
- explicit Python base set construction
- explicit overlay composition
- separate editable package-set construction
- separate `mkApplication` import

Goal:
- make common `uv2nix` usage shorter and prettier
- keep advanced use possible
- keep user in control of flake output structure
- preserve upstream concepts closely enough that docs and mental model still transfer

Non-goal:
- replacing flake architecture with `mkFlake`, `forAllSystems`, `flake-parts` modules, etc.

---

## 2. Goals

### 2.1 Primary goals

1. **Reduce boilerplate around uv2nix composition**
2. **Keep flake architecture user-owned**
3. **Preserve advanced package-set level access**
4. **Support workspaces, not only single-package apps**
5. **Support both production and editable development flows**
6. **Represent conflicting dependency selections cleanly**
7. **Make common pytest-based testing easy and first-class**

### 2.2 Secondary goals

1. collapse source/build-system choice into one obvious knob
2. make `mkApplication` usage ergonomic
3. preserve override-based workflows
4. expose enough low-level surface for tests/dist/patching without broad internal leaks

---

## 3. Non-goals

For v1, this library should **not** try to:
- choose flake output architecture
- abstract `forAllSystems`
- abstract `perSystem`
- auto-generate full apps/packages/checks output trees
- eliminate all manual overlays
- hide all upstream concepts
- provide comprehensive cross-compilation sugar
- unify workspace-project API with inline-metadata scripts API
- provide broad wrapper-side validation for upstream concepts

---

## 4. Design principles

### 4.1 Thin wrapper over upstream model

Wrapper should keep these concepts recognizable:
- project/workspace
- resolved package set
- editable package set
- venv creation
- application wrapping
- overlays

### 4.2 User owns flake outputs

Wrapper should fit inside:
- bare flakes
- `flake-parts`
- `flake-utils`
- custom patterns

Therefore wrapper API should return values users compose into outputs themselves.

### 4.3 Load once, specialize later

Heavy workspace parsing should happen once.
Then per-system per-`pkgs` scopes should be created from loaded project.

This aligns with upstream performance guidance.

### 4.4 Separate package-set dependencies from env dependencies

Two stages must remain distinct:
- **scope-level `dependencies`**: selects dependency graph for overlay/package set
- **env-level `dependencies`**: selects what gets installed in given env

This is mandatory for conflict groups.

### 4.5 Curated low-level access, not generic internals bag

Expose useful domain objects directly.
Do **not** expose generic `raw` / `internal` bag in v1.

Reason:
- broad internal escape hatches freeze implementation accidentally
- package set access solves most advanced cases already

### 4.6 Opinionated syntax, unopinionated architecture

Wrapper may choose concise API shapes and defaults.
Wrapper should not choose overall flake architecture.

### 4.7 Validate wrapper control flow, not upstream schema

Wrapper should provide clear errors for wrapper-owned inference and helper lookup.
Wrapper should also validate wrapper-owned lookups such as selecting a build-system overlay from `sourcePreference`.
Wrapper should otherwise defer upstream validation of upstream-shaped concepts.

---

## 5. Proposed object model

### 5.1 Project object

Top-level loaded object. Created once.

Illustrative shape:

```nix
project = uvloom.lib.loadProject {
  root = ./.;
};
```

Responsibilities:
- load workspace/project metadata once
- serve as source for multiple per-system scopes
- expose narrow upstream fallback for advanced cases

Likely stable attrs/methods:
- `project.forPython`
- `project.workspace` as advanced escape hatch

`project.workspace` policy:
- public on purpose, but advanced
- keep out of main getting-started path
- good for `workspace.deps.*`, `mkPyprojectOverlay`, `mkEditablePyprojectOverlay`, other narrow upstream interop
- **not** covered by wrapper stability guarantees beyond attr presence
- if user needs broader manual upstream composition pipeline, docs should tell them to add explicit upstream inputs

### 5.2 Python scope object

System- / `pkgs`-specific Python scope for project.

Illustrative shape:

```nix
scope = project.forPython {
  inherit pkgs;

  interpreter = pkgs.python312;
  sourcePreference = "wheel";
  stdenv = pkgs.stdenv;
  overlays = [ ];
};
```

Responsibilities:
- instantiate base Python package set
- resolve interpreter from explicit `interpreter` or upstream `requires-python`-based selection
- compose build-system overlay + generated uv2nix overlay + user overlays
- optionally construct editable variant of package set
- expose constructors for venv/app/checks on top of package sets

Likely stable attrs/methods:
- `scope.pythonSet`
- `scope.mkVenv`
- `scope.mkApplication`
- `scope.mkPytestCheck`
- `scope.editablePythonSet` when editable config present
- `scope.mkEditableVenv` when editable config present

Policy:
- `scope.pythonSet` is exact final Python set used by non-editable helpers
- `scope.editablePythonSet` is exact final editable Python set used by editable helpers
- names intentionally match common upstream `pythonSet` terminology
- no alias attrs like `packages`, `pythonPackages`, or `editablePackages`
- when editable config absent, `scope.editablePythonSet` and `scope.mkEditableVenv` are absent, not `null`

---

## 6. Proposed API shape

### 6.1 Project loading

```nix
project = uvloom.lib.loadProject {
  root = ./.;
};
```

#### Arguments

- `root`: workspace/project root, path only

v1 policy:
- accepts only `{ root = ...; }`
- no pre-loaded workspace escape hatch
- missing `pyproject.toml` / `uv.lock` validation is deferred to upstream

#### Returns

At minimum:
- `forPython`
- `workspace` as advanced escape hatch

### 6.2 Python scope construction

```nix
scope = project.forPython {
  inherit pkgs;

  interpreter = pkgs.python312;
  sourcePreference = "wheel";

  overlays = [
    (final: prev: { ... })
  ];

  editable = {
    root = "$REPO_ROOT";
    members = [ "my-app" ];
  };

  environ = {
    platform_release = "5.10.65";
  };

  stdenv = pkgs.stdenv;
};
```

#### Required arguments

- `pkgs`

#### Optional arguments

- `interpreter`
  - optional
  - if omitted, wrapper delegates interpreter selection to upstream `requires-python`-aware functionality using `project.workspace.requires-python` and the available interpreters from `pkgs`
  - no `.python-version` support in v1
  - if upstream cannot select a compatible interpreter, wrapper should surface a clear `uvloom.forPython` error with the workspace `requires-python` value when available
  - if explicitly provided, wrapper trusts value and does not type-check it

- `sourcePreference ? "wheel"`
  - wrapper keeps upstream name intentionally
  - wrapper passes value to uv2nix without duplicating upstream source-selection validation
  - wrapper **does** validate its own build-system overlay lookup for this value
  - if no matching `pyproject-build-systems.overlays.${sourcePreference}` exists, wrapper throws a clear error listing available overlay keys
  - wrapper maps this to both uv overlay and matching build-system overlay choice

- `dependencies ? <workspace default dependency selection>`
  - dependency graph selection at package-set creation time
  - uses same uv2nix-native schema as env construction
  - supports conflict groups
  - exact underlying default matches upstream workspace `deps.default`
  - main docs/examples should usually omit this default rather than spell `project.workspace.deps.default`
  - custom selections can be written literally; advanced users can still reach `project.workspace.deps.*` through escape hatch

- `overlays ? [ ]`
  - user overlays composed after generated overlay
  - must be list
  - wrapper does not validate element types beyond list shape

- `editable`
  - optional editable scope configuration
  - presence enables editable package-set creation and editable env helper
  - shape:

```nix
editable = {
  root = "$REPO_ROOT";
  members = [ "my-app" ];
};
```

  - `editable.root` is string-only
  - `editable.members` omitted defers to upstream default behavior
  - `editable.members = [ ]` is passed through literally
  - unknown editable member validation is deferred to upstream

- `environ ? { }`
  - passed to uv overlay marker evaluation layer
  - wrapper passes keys/values through without validation

- `stdenv ? pkgs.stdenv`
  - passed to Python base package-set construction
  - intentionally not `pkgs.stdenvNoCC`
  - same chosen `stdenv` is also used by wrapper-created helper derivations
  - no public `scope.stdenv` attr in v1

#### Overlay composition order

Order is fixed:
1. wrapper-selected build-system overlay matching `sourcePreference`
2. generated uv overlay
3. user overlays

This order is part of v1 contract.

#### Return attrs

Always available:
- `pythonSet`
- `mkVenv`
- `mkApplication`
- `mkPytestCheck`

Available only when `editable` config present:
- `editablePythonSet`
- `mkEditableVenv`

When `editable` config absent:
- `scope.editablePythonSet` attr absent
- `scope.mkEditableVenv` attr absent

---

## 7. Dependency selection model

Wrapper should keep dependency selections close to uv2nix.

That same schema should be used everywhere:
- `project.forPython { dependencies = ...; }`
- `scope.mkVenv { dependencies = ...; }`
- `scope.mkEditableVenv { dependencies = ...; }`
- `scope.mkPytestCheck { dependencies = ...; }`
- `project.workspace.mkPyprojectOverlay { dependencies = ...; }`

`scope.mkPytestCheck { groups = ...; }` is sugar that expands selected groups into this same dependency shape for both its derived test package set and test venv.

### 7.1 Public shape

```nix
dependencies = {
  my-app = [ "test" "cuda" ];
};
```

Design rules:
- keys are workspace package names
- values are uv2nix-style lists of selected dependency names
- wrapper does not try to distinguish groups from extras in core API
- same values should work with wrapper helpers and direct `project.workspace` fallback

Examples:

```nix
dependencies = {
  smiley-plot = [ "test" ];
};

dependencies = {
  my-app = [ "cuda" ];
};
```

### 7.2 No wrapper-owned dependency preset namespace

Wrapper should **not** re-export workspace dependency presets as `project.deps` or `project.dependencies`.

Main path should prefer:
- omitted defaults when default selection is fine
- literal dependency selections when customization is needed

Advanced path may still use upstream presets through escape hatch, e.g. `project.workspace.deps.*`.

Reason:
- avoids duplicate naming surface
- avoids freezing upstream preset structure under wrapper namespace
- keeps dependency schema obviously uv2nix-native
- keeps `project.workspace` out of main API path

### 7.3 Scope-level `dependencies`

Purpose:
- choose which dependency graph gets resolved into package set
- must happen before env creation
- supports conflict groups and mutually exclusive selections

Default:
- upstream workspace default dependency selection

Main-path example:

```nix
scope = project.forPython {
  inherit pkgs;
  interpreter = pkgs.python312;
  sourcePreference = "wheel";
};
```

### 7.4 Env-level `dependencies`

Purpose:
- choose what gets installed into particular venv/app/check

Default for `mkVenv` and `mkEditableVenv`:
- upstream workspace default dependency selection

Example:

```nix
testVenv = scope.mkVenv {
  name = "smiley-plot-test-env";
  dependencies = {
    smiley-plot = [ "test" ];
  };
};
```

### 7.5 Design rule

Scope-level and env-level `dependencies` may coincide often, but are not same stage.

Example:
- scope selects CUDA-flavored package set
- one env installs runtime dependencies
- another env installs test group from same package set

### 7.6 Direct workspace fallback

Wrapper should make special-case fallback straightforward.

Because `dependencies` uses uv2nix-native shape, same literal value should work in both wrapper and workspace APIs:

```nix
selection = {
  smiley-plot = [ "test" ];
};

scope = project.forPython {
  inherit pkgs;
  interpreter = pkgs.python312;
  sourcePreference = "wheel";
  dependencies = selection;
};

overlay = project.workspace.mkPyprojectOverlay {
  sourcePreference = "sdist";
  dependencies = selection;
};
```

Important:
- `project.workspace` is public escape hatch
- it is not covered by wrapper stability guarantees beyond attr presence
- main docs/examples should not rely on it for default path
- when user needs full manual `uv2nix` / `pyproject-nix` composition, docs should point them to explicit upstream inputs

---

## 8. Virtual environment model

### 8.1 Non-editable env construction

```nix
venv = scope.mkVenv {
  name = "smiley-plot-env";
};
```

Arguments:
- `name`: required string
- `dependencies ? <workspace default dependency selection>`
  - env-level install selection
  - uses uv2nix-native dependency schema
  - passed to `scope.pythonSet.mkVirtualEnv`

Design rules:
- `mkVenv` uses `scope.pythonSet` explicitly
- `mkVenv` never creates editables
- no `mkVenv { editable = true; }` mode
- no extra convenience args in v1

## 9. Editable model

### 9.1 Scope-level editable configuration

Editable behavior belongs at scope level because upstream creates separate editable package set.

Illustrative shape:

```nix
editable = {
  root = "$REPO_ROOT";
  members = [ "smiley-plot" ];
};
```

#### Required fields

- `root`
  - string only
  - should support non-store values such as `$REPO_ROOT`

#### Optional fields

- `members`
  - subset of workspace members to expose as editables
  - omitted means defer to upstream default behavior
  - `[ ]` is passed through literally

### 9.2 Editable env construction

Editable envs use separate constructor:

```nix
devVenv = scope.mkEditableVenv {
  name = "smiley-plot-dev-env";
};
```

Design rules:
- `mkEditableVenv` mirrors `mkVenv` arg shape
- `name` is required
- `dependencies ? <workspace default dependency selection>`
- `mkEditableVenv` exists only when scope was created with `editable = { ... };`
- `mkEditableVenv` uses editable package set explicitly
- `mkVenv` stays non-editable constructor
- no `mkVenv { editable = true; }` mode

### 9.3 Dev shell remains user-owned

Wrapper should not try to fully abstract dev shell creation.

Typical shell should remain explicit:

```nix
pkgs.mkShell {
  packages = [
    devVenv
    pkgs.uv
  ];

  env = {
    UV_NO_SYNC = "1";
    UV_PYTHON = scope.editablePythonSet.python.interpreter;
    UV_PYTHON_DOWNLOADS = "never";
  };

  shellHook = ''
    unset PYTHONPATH
    export REPO_ROOT=$(git rev-parse --show-toplevel)
  '';
}
```

Reason:
- advanced editable build systems may require more shell packages / hook logic
- wrapper should not hide upstream shell realities

---

## 10. Application model

Wrapper should provide ergonomic access to `mkApplication`.

Illustrative explicit shape:

```nix
application = scope.mkApplication {
  venv = scope.mkVenv {
    name = "smiley-plot-env";
  };
  package = "smiley-plot";
};
```

### 10.1 v1 API

Arguments:
- `package ? null`
  - string package name
  - if omitted, infer only when workspace has exactly one local workspace package
  - inference candidate set is declared local workspace members only, not arbitrary local/path dependencies from lock file
  - if ambiguous, wrapper throws clear error listing candidates
- `venv ? null`
  - if omitted or `null`, wrapper auto-creates:

```nix
scope.mkVenv {
  name = "${resolvedPackageName}-env";
}
```

- `pname ? null`
- `version ? null`

### 10.2 Package lookup behavior

When helper resolves package name, wrapper should pre-check package presence in `scope.pythonSet`.
On failure, wrapper throws clear error including:
- helper name
- requested package name
- available local workspace package candidates

Rationale:
- common pattern
- removes need for user to import `pyproject-nix.build.util.mkApplication`
- still explicit enough
- avoids raw missing-attr errors for wrapper-owned lookup path

---

## 11. Testing model

Testing should be first-class in wrapper.

Key design choice for v1:
- pytest helper lives on `scope`, but derives a test-specific sibling scope internally
- helper reuses current scope configuration and adds test dependency selection in the derived scope
- selected `groups` are included at both package-set creation time and test-env install time
- users should not need to remember to add test groups to the original `project.forPython { dependencies = ...; }`

Target outcome:
- default to `pytest`
- easy one-call common case
- use same Python-scope knobs as `project.forPython`
- pull test dependencies from named dependency groups in `pyproject.toml`
- still allow lower-level custom derivations when needed

### 11.1 Default helper

Illustrative shape:

```nix
scope = project.forPython {
  inherit pkgs;
  interpreter = pkgs.python312;
  sourcePreference = "wheel";
};

pytest = scope.mkPytestCheck {
  package = "smiley-plot";
  groups = [ "test" ];
};
```

Intended behavior:
- create separate test derivation
- create test-specific package set using same construction logic as `project.forPython`
- include selected test groups in the test package-set `dependencies`
- create test virtualenv from that test package set
- install selected test groups into the test virtualenv
- run `pytest tests` by default

Rationale:
- avoids scope/env dependency-stage footgun for tests
- matches upstream pattern that tests are separate derivations
- matches common Python project convention of `test` dependency group
- keeps normal runtime `scope` clean when tests need extra dependency groups
- avoids adding hidden mutable behavior to existing `scope.pythonSet`

### 11.2 Mapping groups to dependency selections

For package `smiley-plot` and groups `[ "test" ]`, helper computes a dependency selection equivalent to:

```nix
testDependencies = {
  smiley-plot = [ "test" ];
};
```

That selection is used twice:

```nix
testScope = deriveTestScopeFromCurrentScope {
  dependencies = testDependencies;
};

pytestVenv = testScope.mkVenv {
  name = "smiley-plot-pytest-env";
  dependencies = testDependencies;
};
```

This uses named dependency groups from `pyproject.toml`, not separate wrapper-owned test dependency config.

### 11.3 v1 helper arguments

`scope.mkPytestCheck` accepts pytest-specific args. It reuses current scope construction args internally.

```nix
scope.mkPytestCheck {
  package ? null;
  groups ? [ "test" ];
  name ? "${resolvedPackageName}-pytest";
  paths ? [ "tests" ];
  pytestFlags ? [ ];
  env ? { };
  nativeBuildInputs ? [ ];
}
```

Rules:
- if `package` passed, use it
- if `package` omitted and workspace has exactly one local package, infer it
- if `package` omitted and workspace has multiple local packages, throw clear error listing candidates
- inference candidate set is declared local workspace members only, not arbitrary local/path dependencies from lock file
- package lookup is pre-checked in the internally created test scope's `pythonSet`
- no editable mode in v1

`dependencies` behavior:
- if omitted or `null`, helper uses `{ ${resolvedPackageName} = groups; }` as the test dependency selection
- if provided, helper uses the provided value as the full test dependency selection
- provided `dependencies` lets users combine test groups with conflict selections, e.g. `{ my-app = [ "cuda" "test" ]; }`
- `groups` still defaults to `[ "test" ]`, but is only auto-expanded when `dependencies` is omitted/null

### 11.4 Derivation contract

`scope.mkPytestCheck` should return plain derivation suitable for `checks`.

Recommended contract:
- create internal `testScope` from current scope construction args plus test dependency selection
- use `stdenv.mkDerivation` where `stdenv` is chosen from helper args
- `name = "${resolvedPackageName}-pytest"` unless overridden
- `src = testScope.pythonSet.${package}.src`
- construct pytest venv using `testScope.mkVenv`
- `nativeBuildInputs = [ pytestVenv ] ++ nativeBuildInputs`
- pass `env` through
- `dontConfigure = true`
- working directory is unpacked source root
- `buildPhase` runs `pytest` over chosen `paths` and `pytestFlags` using shell-escaped args
- `installPhase` defaults to `touch $out`

### 11.5 Advanced custom tests still supported

When helper not enough, user should still be able to build custom test derivations with:
- `scope.pythonSet`
- `scope.editablePythonSet` when editable config present
- `scope.mkVenv`
- explicit `project.forPython { dependencies = ...; }` for custom test package sets

So testing should be well-supported by default, but not locked to helper only.

---

## 12. Low-level exposure policy

### 12.1 Expose these directly

#### `scope.pythonSet`

Must be available.

Value:
- exact final non-editable Python set attrset used by scope helpers
- same kind of object commonly called `pythonSet` in upstream `uv2nix` examples

Use cases:
- separate test derivations
- dist/sdist builds
- patching dependencies
- nixpkgs interop
- package-specific overrides

#### `scope.editablePythonSet`

Must be available when editable config present.

Value:
- exact final editable Python set attrset used by editable helpers

Use cases:
- shell env vars
- advanced editable workflows
- debugging editable behavior

#### `project.workspace`

Must be available as direct upstream fallback.

Use cases:
- custom overlay generation
- direct `workspace.deps.*` access in advanced cases
- advanced cases not worth wrapper-specific API

Stability note:
- public escape hatch
- keep out of main getting-started path
- not covered by wrapper stability guarantees beyond attr presence

### 12.2 Do not expose generic `raw`

Not in v1.

Rejected shape:

```nix
scope.raw.workspace
scope.raw.overlay
scope.raw.pythonBase
```

Reason:
- too broad
- encourages accidental dependence on internal composition details
- harder to version safely

### 12.3 Do not expose wrapper dependency preset namespace

Rejected shapes:

```nix
project.deps.default
project.dependencies.default
```

Reason:
- duplicates upstream preset surface
- encourages wrapper-specific naming for upstream concept
- advanced users can still reach `project.workspace.deps.*` through escape hatch when literals are not enough

---

## 13. Example target usage

### 13.1 Simple app

Matches [`./flake-simple.nix`](./flake-simple.nix):

```nix
project = uvloom.lib.loadProject {
  root = ../.;
};

scope = project.forPython {
  inherit pkgs;
  interpreter = pkgs.python312;
  sourcePreference = "wheel";

  overlays = [
    (final: prev: {
      meshpy = prev.meshpy.overrideAttrs (old: {
        buildInputs = (old.buildInputs or [ ]) ++ [ pkgs.stdenv.cc.cc.lib ];
      });
    })
  ];
};

venv = scope.mkVenv {
  name = "smiley-plot-env";
};

application = scope.mkApplication {
  inherit venv;
  package = "smiley-plot";
};
```

### 13.2 Conflicting dependency selections

Matches [`./flake-conflicts.nix`](./flake-conflicts.nix):

```nix
cpuScope = project.forPython {
  inherit pkgs;
  interpreter = pkgs.python312;
  sourcePreference = "wheel";
  dependencies = {
    my-app = [ "cpu" ];
  };
};

cudaScope = project.forPython {
  inherit pkgs;
  interpreter = pkgs.python312;
  sourcePreference = "wheel";
  dependencies = {
    my-app = [ "cuda" ];
  };
};
```

### 13.3 Editable shell

Matches [`./flake-editable.nix`](./flake-editable.nix):

```nix
project = uvloom.lib.loadProject {
  root = ../.;
};

scope = project.forPython {
  inherit pkgs;
  interpreter = pkgs.python312;
  sourcePreference = "wheel";

  editable = {
    root = "$REPO_ROOT";
    members = [ "smiley-plot" ];
  };
};

devVenv = scope.mkEditableVenv {
  name = "smiley-plot-dev-env";
};
```

### 13.4 Pytest helper for common tests

Matches [`./flake-tests.nix`](./flake-tests.nix):

```nix
checks.${system}.pytest = scope.mkPytestCheck {
  package = "smiley-plot";
  groups = [ "test" ];
};
```

This should cover most application/library projects with minimal boilerplate.

### 13.5 Custom tests without generic `raw`

When needed, custom derivations should still be possible:

```nix
testVenv = scope.mkVenv {
  name = "smiley-plot-test-env";
  dependencies = {
    smiley-plot = [ "test" ];
  };
};

smileyPlotWithTests = scope.pythonSet."smiley-plot".overrideAttrs (old: {
  passthru.tests.pytest = stdenv.mkDerivation { ... };
});
```

This is strong evidence that `pythonSet` exposure is enough low-level surface.

---

## 14. Internal mapping to upstream concepts

This section defines design intent, not exact implementation.

### 14.1 Project load

Wrapper project load should map roughly to:

```nix
workspace = uv2nix.lib.workspace.loadWorkspace {
  workspaceRoot = root;
};
```

### 14.2 Python scope creation

Wrapper scope creation should map roughly to:

```nix
resolvedInterpreter =
  interpreter
  or (selectInterpreterFromRequiresPython {
    inherit pkgs;
    requiresPython = workspace.requires-python;
  });

pythonBase = pkgs.callPackage pyproject-nix.build.packages {
  python = resolvedInterpreter;
  inherit stdenv;
};

overlay = workspace.mkPyprojectOverlay {
  sourcePreference = sourcePreference;
  dependencies = dependencies;
  environ = environ;
};

pythonSet = pythonBase.overrideScope (
  lib.composeManyExtensions [
    selectBuildSystemOverlay sourcePreference
    overlay
  ] ++ overlays
);
```

Notes:
- `sourcePreference` name intentionally matches upstream
- `sourcePreference` default is `"wheel"`
- wrapper validates that a matching build-system overlay exists before composing overlays
- `dependencies` default is upstream workspace default dependency selection
- exact underlying default is reachable through `project.workspace.deps.default` when needed via escape hatch
- `stdenv` default is `pkgs.stdenv`
- user overlays run after wrapper-selected overlays

### 14.3 Editable scope

If editable config present:

```nix
editableOverlay = workspace.mkEditablePyprojectOverlay {
  root = editable.root;
  members = editable.members or ...;
};

editablePythonSet = pythonSet.overrideScope editableOverlay;
```

Editable helpers then build from `editablePythonSet`:

```nix
scope.mkEditableVenv { ... }
```

### 14.4 Environment helpers

`mkVenv` and `mkEditableVenv` should map roughly to:

```nix
pythonSet.mkVirtualEnv name dependencies
```

using either resolved package set or editable package set.

### 14.5 Application helper

`scope.mkApplication` should wrap `pyproject-nix.build.util.mkApplication`.

### 14.6 Pytest helper

`scope.mkPytestCheck` should map roughly to:
- resolve package name from declared local workspace members
- compute test dependency selection from `groups`, unless explicit `dependencies` provided
- create internal test scope from current scope construction args plus test dependency selection
- build pytest env with `testScope.mkVenv`
- build `stdenv.mkDerivation`
- use package `src` from `testScope.pythonSet`
- run `pytest`
- `touch $out`

---

## 15. Stability policy draft

### 15.1 Intended stable surface

Likely stable:
- `loadProject` entrypoint
- `loadProject { root = ...; }` shape
- `project.forPython`
- requires-python-based interpreter selection when `interpreter` omitted
- `dependencies` concept
- uv2nix-native dependency schema
- `scope.pythonSet`
- `scope.mkVenv`
- `scope.mkApplication`
- `scope.mkPytestCheck`
- `scope.editablePythonSet` when editable config present
- `scope.mkEditableVenv` when editable config present
- `sourcePreference` arg name and default
- top-level `stdenv` arg on `forPython`
- `overlays` default and composition order
- presence of `project.workspace` attr as escape hatch
- attr absence semantics for editable-only surface

### 15.2 Intended unstable / hidden surface

Should remain hidden or clearly non-API:
- exact internals of interpreter auto-selection beyond documented behavior
- internal normalized attr names
- intermediate generated overlays
- detailed shape under `project.workspace`
- upstream workspace helper attrs like `project.workspace.deps.*`
- any internal convenience helpers used to implement package inference

In short:
- `project.workspace` is public
- what sits under it remains upstream-shaped and unstable from wrapper perspective

---

## 16. Settled v1 decisions

Settled:
- project load entrypoint is `loadProject`
- `loadProject` accepts only path `root`
- no pre-loaded workspace escape hatch in v1
- `project.forPython` stays
- docs variable name for per-system object is `scope`
- `interpreter` is optional
- omitted `interpreter` uses upstream `requires-python`-aware interpreter selection
- no `.python-version` support in v1
- explicit `interpreter` value is trusted
- `sourcePreference` name stays and matches upstream
- `sourcePreference` default is `"wheel"`
- wrapper validates its own build-system overlay lookup for `sourcePreference`
- wrapper otherwise does not duplicate upstream source-selection validation
- scope-level `dependencies` default to upstream workspace default dependency selection
- main docs/examples should omit default `dependencies` rather than put `project.workspace` front and center
- `overlays ? [ ]`
- overlay order is fixed: build-system overlay, generated uv overlay, user overlays
- wrapper does **not** expose `project.deps` / `project.dependencies`
- `project.workspace` is public escape hatch
- `project.workspace` is not covered by wrapper stability guarantees beyond attr presence
- editable env constructor is separate `mkEditableVenv`
- `editable.root` is string-only
- `scope.editablePythonSet` absent when editable config absent
- `scope.mkEditableVenv` absent when editable config absent
- `mkEditableVenv.dependencies` defaults to upstream workspace default dependency selection
- `stdenv` promoted to top-level `forPython` arg
- `stdenv` default is `pkgs.stdenv`
- helper derivations reuse chosen `stdenv`
- `scope.pythonSet` is exact final non-editable Python set used by scope helpers
- `scope.editablePythonSet` is exact final editable Python set used by helpers
- `pythonSet` naming intentionally matches common upstream terminology
- `mkApplication.package` is string package name
- `mkApplication.package` may be inferred for single-local-package workspaces
- `mkApplication.venv` is optional
- omitted `venv` auto-builds `${resolvedPackageName}-env` with default dependencies
- `mkApplication` allows `pname` and `version` passthrough overrides
- `scope.mkPytestCheck` uses `groups`, not `dependencyGroup`
- `scope.mkPytestCheck.groups ? [ "test" ]`
- `scope.mkPytestCheck.package` may be inferred for single-local-package workspaces
- `scope.mkPytestCheck` constructs an internal test scope so test groups are included at package-set creation time
- `scope.mkPytestCheck.dependencies` may override the full test dependency selection for conflict/group combinations
- `scope.mkPytestCheck` editable mode is out of scope for v1
- `scope.mkPytestCheck` uses package `src` from internal `testScope.pythonSet`
- `scope.mkPytestCheck` returns plain derivation suitable for `checks`
- helper lookup errors should be clear wrapper errors, not raw missing attrs
- wrapper validation stays minimal and focused on wrapper-owned inference/control flow

### 16.1 Remaining non-API follow-up items

Still to do:
- implement smoke fixtures and checks
- decide exact fixture wiring in flake/CI
- polish docs around `project.workspace` fallback boundary
- verify error message wording during implementation

### 16.2 Smoke-check targets

Required eval coverage:
- `loadProject`
- `forPython`
- `scope.pythonSet`
- `mkVenv`
- `mkApplication`
- `scope.mkPytestCheck`
- editable attr presence/absence
- `mkEditableVenv`

Required negative eval coverage for wrapper-owned errors:
- omitted `interpreter` with unsatisfied/unselectable `requires-python`
- `sourcePreference` with no matching build-system overlay
- ambiguous inferred package
- requested package absent from helper package set
- `overlays` not list
- `editable.root` not string

Required real builds:
- one simple `mkVenv`
- one auto-venv `mkApplication`
- one `scope.mkPytestCheck`

Editable path may stay eval-only initially if CI/runtime setup cost is high.

---

## 17. Deferred features

Good candidates for later iterations:
- override DSL
- source-filter helper DSL
- script / inline-metadata wrapper API
- flake-parts module
- cross-compilation helper layer
- shell helper snippets for common editable env vars
- private index helper patterns
- additional helper families derived from project metadata

These should wait until core shape proves correct in implementation.

---

## 18. Current recommended direction

Build around two core operations:

1. **load project once**
2. **derive per-system scope from `pkgs`**

Keep these public capabilities:
- infer interpreter from workspace `requires-python` or accept explicit one
- choose source preference
- choose dependency selections for package sets and envs
- create venvs with chosen dependencies
- create editable venvs when editable config exists
- create application wrappers
- configure editables
- access resolved package sets
- attach manual overlays
- run first-class pytest checks
- fall back to `project.workspace` for advanced upstream cases

Avoid these for now:
- flake architecture abstractions
- generic internal escape-hatch bags
- wrapper-owned dependency preset namespaces
- giant opinionated top-level generators
- broad duplicate validation of upstream concepts

This gives wrapper that is:
- thinner than bare uv2nix
- still recognizably uv2nix
- compatible with many flake styles
- open enough for advanced real-world cases
- small enough to stabilize before growing helper surface
