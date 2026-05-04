# RESEARCH

Background research for `uvloom`.

Purpose:
- document upstream `uv2nix` model
- capture constraints from docs and source
- identify pain points and edge cases
- provide evidence for decisions in [`DESIGN.md`](./DESIGN.md)

---

## 1. Scope

Goal under discussion:

> build thin Nix library / flake that makes `uv2nix` less verbose and nicer to use, without taking over flake architecture.

Important boundary from discussion:
- wrapper should **not** impose `mkFlake`, `forAllSystems`, `flake-parts`, `flake-utils`, or any other flake output architecture
- wrapper should instead provide syntactic sugar around `uv2nix` concepts that users can embed inside their own flake design

---

## 2. Primary sources

### User-provided sources
- Official docs intro: <https://pyproject-nix.github.io/uv2nix/introduction.html>
- DeepWiki overview: <https://deepwiki.com/pyproject-nix/uv2nix>

### Upstream repository
Repository:
- <https://github.com/pyproject-nix/uv2nix>

Research commit used for source permalinks:
- `60982c30e16db3e0cba6c0ed13f0894b06ab2bf1`

### Key documentation pages
- Getting started: <https://github.com/pyproject-nix/uv2nix/blob/60982c30e16db3e0cba6c0ed13f0894b06ab2bf1/doc/src/usage/getting-started.md>
- FAQ: <https://github.com/pyproject-nix/uv2nix/blob/60982c30e16db3e0cba6c0ed13f0894b06ab2bf1/doc/src/FAQ.md>
- Conflicts: <https://github.com/pyproject-nix/uv2nix/blob/60982c30e16db3e0cba6c0ed13f0894b06ab2bf1/doc/src/conflicts.md>
- Source filtering: <https://github.com/pyproject-nix/uv2nix/blob/60982c30e16db3e0cba6c0ed13f0894b06ab2bf1/doc/src/patterns/source-filtering.md>
- Applications: <https://github.com/pyproject-nix/uv2nix/blob/60982c30e16db3e0cba6c0ed13f0894b06ab2bf1/doc/src/patterns/applications.md>
- Advanced build systems: <https://github.com/pyproject-nix/uv2nix/blob/60982c30e16db3e0cba6c0ed13f0894b06ab2bf1/doc/src/patterns/advanced-build-systems.md>
- Private deps: <https://github.com/pyproject-nix/uv2nix/blob/60982c30e16db3e0cba6c0ed13f0894b06ab2bf1/doc/src/patterns/private-deps.md>
- Testing: <https://github.com/pyproject-nix/uv2nix/blob/60982c30e16db3e0cba6c0ed13f0894b06ab2bf1/doc/src/patterns/testing.md>
- Dist builds: <https://github.com/pyproject-nix/uv2nix/blob/60982c30e16db3e0cba6c0ed13f0894b06ab2bf1/doc/src/patterns/dist.md>
- nixpkgs wheels interop: <https://github.com/pyproject-nix/uv2nix/blob/60982c30e16db3e0cba6c0ed13f0894b06ab2bf1/doc/src/patterns/nixpkgs-wheels.md>
- Patching deps: <https://github.com/pyproject-nix/uv2nix/blob/60982c30e16db3e0cba6c0ed13f0894b06ab2bf1/doc/src/patterns/patching-deps.md>
- Platform quirks: <https://github.com/pyproject-nix/uv2nix/blob/60982c30e16db3e0cba6c0ed13f0894b06ab2bf1/doc/src/platform-quirks.md>
- Cross compilation: <https://github.com/pyproject-nix/uv2nix/blob/60982c30e16db3e0cba6c0ed13f0894b06ab2bf1/doc/src/patterns/cross/index.md>
- Inline metadata: <https://github.com/pyproject-nix/uv2nix/blob/60982c30e16db3e0cba6c0ed13f0894b06ab2bf1/doc/src/usage/inline-metadata.md>

### Key source files
- `lib/workspace.nix`: <https://github.com/pyproject-nix/uv2nix/blob/60982c30e16db3e0cba6c0ed13f0894b06ab2bf1/lib/workspace.nix>
- `lib/overlays.nix`: <https://github.com/pyproject-nix/uv2nix/blob/60982c30e16db3e0cba6c0ed13f0894b06ab2bf1/lib/overlays.nix>
- `lib/build.nix`: <https://github.com/pyproject-nix/uv2nix/blob/60982c30e16db3e0cba6c0ed13f0894b06ab2bf1/lib/build.nix>
- hello-world template: <https://github.com/pyproject-nix/uv2nix/blob/60982c30e16db3e0cba6c0ed13f0894b06ab2bf1/templates/hello-world/flake.nix>
- build-system override example: <https://github.com/pyproject-nix/uv2nix/blob/60982c30e16db3e0cba6c0ed13f0894b06ab2bf1/dev/build-system-overrides.nix>

### Community discussion
- NixOS Discourse announcement + maintainer discussion: <https://discourse.nixos.org/t/uv2nix-build-develop-python-projects-using-uv-with-nix/58563>

### Local comparison drafts in this repo
- Bare baseline: root [`flake.nix`](../flake.nix)
- Simplified draft: [`./flake-simple.nix`](./flake-simple.nix)
- Conflicts draft: [`./flake-conflicts.nix`](./flake-conflicts.nix)
- Editable draft: [`./flake-editable.nix`](./flake-editable.nix)
- Testing draft: [`./flake-tests.nix`](./flake-tests.nix)

---

## 3. Core upstream model

### 3.1 What `uv2nix` is

`uv2nix` ingests a `uv` workspace and turns `uv.lock` into Nix derivations using pure Nix code. It is designed for both development environments and production builds.

Sources:
- official intro: <https://pyproject-nix.github.io/uv2nix/introduction.html>
- upstream intro source: <https://github.com/pyproject-nix/uv2nix/blob/60982c30e16db3e0cba6c0ed13f0894b06ab2bf1/doc/src/introduction.md>

### 3.2 Top-level abstraction is workspace

`uv2nix` centers on:

```nix
workspace = uv2nix.lib.workspace.loadWorkspace { workspaceRoot = ./.; };
```

Source:
- getting started, loading workspace: <https://github.com/pyproject-nix/uv2nix/blob/60982c30e16db3e0cba6c0ed13f0894b06ab2bf1/doc/src/usage/getting-started.md#L68-L86>
- implementation: <https://github.com/pyproject-nix/uv2nix/blob/60982c30e16db3e0cba6c0ed13f0894b06ab2bf1/lib/workspace.nix#L93-L190>

### 3.3 Normal bare flow is multi-step

Typical flow from docs/template:

1. load workspace
2. pick Python interpreter
3. instantiate `pyproject-nix.build.packages`
4. create `workspace.mkPyprojectOverlay { ... }`
5. compose build-system overlay + generated overlay + user overrides
6. build venv with `pythonSet.mkVirtualEnv`
7. optionally wrap venv with `mkApplication`

Sources:
- getting started: <https://github.com/pyproject-nix/uv2nix/blob/60982c30e16db3e0cba6c0ed13f0894b06ab2bf1/doc/src/usage/getting-started.md#L41-L160>
- hello-world template: <https://github.com/pyproject-nix/uv2nix/blob/60982c30e16db3e0cba6c0ed13f0894b06ab2bf1/templates/hello-world/flake.nix#L34-L95>

---

## 4. Baseline code shape and pain

### 4.1 Bare baseline example

The root [`flake.nix`](../flake.nix) captures typical bare uv2nix shape:

```nix
workspace = uv2nix.lib.workspace.loadWorkspace {
  workspaceRoot = ../.;
};

pythonBase = pkgs.callPackage pyproject-nix.build.packages {
  python = pkgs.python312;
};

overlay = workspace.mkPyprojectOverlay {
  sourcePreference = "wheel";
};

pythonSet = pythonBase.overrideScope (
  lib.composeManyExtensions [
    pyproject-build-systems.overlays.wheel
    overlay
    (final: prev: { ... })
  ]
);

venv = pythonSet.mkVirtualEnv "smiley-plot-env" workspace.deps.default;
application = mkApplication {
  inherit venv;
  package = pythonSet."smiley-plot";
};
```

### 4.2 Boilerplate pain points

Common repeated boilerplate:
- flake inputs for `pyproject-nix`, `uv2nix`, `build-system-pkgs`
- separate workspace load and Python base construction
- explicit overlay composition
- coupling between `sourcePreference` and build-system overlay
- separate editable package-set setup for dev shells
- manual `mkApplication` import

Community reaction aligns with this pain. In Discourse, users explicitly called out boilerplate and wrapped parts behind local helper functions for readability.

Source:
- Discourse thread: <https://discourse.nixos.org/t/uv2nix-build-develop-python-projects-using-uv-with-nix/58563>

### 4.3 Upstream rationale for verbosity

Maintainer response matters.

Key points from discussion:
- verbosity is partly intentional
- API tries to preserve flexibility and performance
- workspace loading and parsing should happen once, at top level
- hiding too much can force reevaluation or block advanced use cases

Implication:
- wrapper should be **thin** and **syntax-oriented**, not a replacement architecture
- wrapper should keep upstream concepts visible

Source:
- Discourse thread: <https://discourse.nixos.org/t/uv2nix-build-develop-python-projects-using-uv-with-nix/58563>

---

## 5. Findings by topic

## 5.1 `sourcePreference` and build-system overlay are coupled

Production overlay creation:

```nix
overlay = workspace.mkPyprojectOverlay {
  sourcePreference = "wheel";
};
```

But user must also choose matching build-system overlay:

```nix
pyproject-build-systems.overlays.wheel
```

Sources:
- docs: <https://github.com/pyproject-nix/uv2nix/blob/60982c30e16db3e0cba6c0ed13f0894b06ab2bf1/doc/src/usage/getting-started.md#L88-L139>
- template: <https://github.com/pyproject-nix/uv2nix/blob/60982c30e16db3e0cba6c0ed13f0894b06ab2bf1/templates/hello-world/flake.nix#L38-L62>

Implication:
- wrapper should probably expose **one** source-preference knob and wire both sides consistently

## 5.2 `uv.lock` metadata is incomplete; overrides are normal

`uv2nix` intentionally does not ship bundled overrides. Missing metadata in Python ecosystem and in `uv.lock` means overrides remain common.

Sources:
- FAQ: <https://github.com/pyproject-nix/uv2nix/blob/60982c30e16db3e0cba6c0ed13f0894b06ab2bf1/doc/src/FAQ.md#L3-L21>
- build-system override example: <https://github.com/pyproject-nix/uv2nix/blob/60982c30e16db3e0cba6c0ed13f0894b06ab2bf1/dev/build-system-overrides.nix#L1-L60>

Implication:
- wrapper must preserve easy package-level overrides
- wrapper should not pretend overrides disappear

## 5.3 Conflicting dependency groups use `dependencies` at overlay / package-set creation time

For conflicting dependency groups, docs require choosing `dependencies` in `workspace.mkPyprojectOverlay { dependencies = ...; }`.

```nix
workspace.mkPyprojectOverlay {
  sourcePreference = "wheel";
  dependencies = {
    hello-world = [ "extra1" ];
  };
}
```

Sources:
- conflicts doc: <https://github.com/pyproject-nix/uv2nix/blob/60982c30e16db3e0cba6c0ed13f0894b06ab2bf1/doc/src/conflicts.md#L1-L13>
- `mkPyprojectOverlay` arg shape: <https://github.com/pyproject-nix/uv2nix/blob/60982c30e16db3e0cba6c0ed13f0894b06ab2bf1/lib/workspace.nix#L169-L190>

Implication:
- wrapper must preserve two stages:
  - package-set dependency selection at Python scope creation time
  - install-time dependency selection for `mkVenv`
- one generic `deps` knob is not enough
- but both stages can still use same uv2nix-native dependency value shape

## 5.4 Workspace dependency presets exist and are useful

`workspace.deps` exposes presets:
- `default`
- `optionals`
- `groups`
- `all`

Source:
- `workspace.deps`: <https://github.com/pyproject-nix/uv2nix/blob/60982c30e16db3e0cba6c0ed13f0894b06ab2bf1/lib/workspace.nix#L239-L275>

Implication:
- wrapper should keep dependency values close to upstream `workspace.deps.*` shape for easy fallback
- if presets stay behind explicit escape hatch, docs should avoid making `project.workspace` part of main path

## 5.5 Editable packages require separate overlay and separate package set

Editable support is not just a flag on package installation. Upstream creates a separate editable overlay and then a separate package set.

```nix
editableOverlay = workspace.mkEditablePyprojectOverlay {
  root = "$REPO_ROOT";
};

editablePythonSet = pythonSet.overrideScope editableOverlay;
virtualenv = editablePythonSet.mkVirtualEnv "hello-world-dev-env" workspace.deps.all;
```

Sources:
- getting started, dev shell section: <https://github.com/pyproject-nix/uv2nix/blob/60982c30e16db3e0cba6c0ed13f0894b06ab2bf1/doc/src/usage/getting-started.md#L162-L236>
- implementation: <https://github.com/pyproject-nix/uv2nix/blob/60982c30e16db3e0cba6c0ed13f0894b06ab2bf1/lib/workspace.nix#L192-L237>

Implication:
- wrapper must treat editable support as Python scope/package-set concern, not only a venv concern
- editable config must support:
  - non-store root, often `$REPO_ROOT`
  - subset of editable members in workspaces

## 5.6 Editable roots cannot be store paths

`mkEditablePyprojectOverlay` explicitly rejects store-path roots. This matters for flakes.

Source:
- assertion in `workspace.nix`: <https://github.com/pyproject-nix/uv2nix/blob/60982c30e16db3e0cba6c0ed13f0894b06ab2bf1/lib/workspace.nix#L205-L213>

Implication:
- wrapper API must make non-store roots visible and explicit
- wrapper must not “helpfully” default editables to flake store paths

## 5.7 Source filtering must happen per package, not at workspace root

Docs strongly warn against filtering the workspace root. Doing so causes import-from-derivation and breaks editables.

Sources:
- source filtering doc: <https://github.com/pyproject-nix/uv2nix/blob/60982c30e16db3e0cba6c0ed13f0894b06ab2bf1/doc/src/patterns/source-filtering.md#L6-L58>

Implication:
- any future source-filter sugar must operate on package overrides
- wrapper must not encourage filtering `root`

## 5.8 Advanced editable build systems need extra shell plumbing

For systems like `meson-python` or `cython`, dev shell may need `build-editable` and a shell hook to rerun editable builds for side effects.

Source:
- advanced build systems doc: <https://github.com/pyproject-nix/uv2nix/blob/60982c30e16db3e0cba6c0ed13f0894b06ab2bf1/doc/src/patterns/advanced-build-systems.md#L1-L31>

Implication:
- wrapper should not fully hide dev shell construction
- low-level package-set access still useful

## 5.9 Platform quirks use two different configuration channels

Two separate knobs:
- base package-set creation `stdenv` / `targetPlatform.darwinSdkVersion`
- overlay/environment marker evaluation `environ.platform_release`

Sources:
- platform quirks doc: <https://github.com/pyproject-nix/uv2nix/blob/60982c30e16db3e0cba6c0ed13f0894b06ab2bf1/doc/src/platform-quirks.md#L1-L38>

Implication:
- wrapper Python scope probably needs both:
  - Python-base args or `stdenv`
  - overlay `environ`

## 5.10 Private authenticated deps require manual fetcher override and sandbox setup

For private indexes, docs show overriding package `src` fetcher attributes and passing `extra-sandbox-paths` or equivalent Nix config.

Source:
- private deps doc: <https://github.com/pyproject-nix/uv2nix/blob/60982c30e16db3e0cba6c0ed13f0894b06ab2bf1/doc/src/patterns/private-deps.md#L1-L70>

Implication:
- wrapper must keep user in control of overlays and shell/build flags
- wrapper should not assume network/auth handled automatically

## 5.11 Tests are separate derivations, not package build phases

`uv2nix` test pattern uses `passthru.tests` and separate derivations, not inline `checkPhase` on the main package.

Sources:
- testing doc: <https://github.com/pyproject-nix/uv2nix/blob/60982c30e16db3e0cba6c0ed13f0894b06ab2bf1/doc/src/patterns/testing.md#L1-L20>
- testing example flake: <https://github.com/pyproject-nix/uv2nix/blob/60982c30e16db3e0cba6c0ed13f0894b06ab2bf1/doc/src/patterns/testing/flake.nix>

Implication:
- wrapper should expose a usable low-level package set for test derivations
- generic “one function returns final app only” is too small

## 5.12 Dist builds operate on individual packages

Building redistributable wheels/sdists happens by overriding individual package derivations, sometimes with `pyprojectDistHook`.

Source:
- dist doc: <https://github.com/pyproject-nix/uv2nix/blob/60982c30e16db3e0cba6c0ed13f0894b06ab2bf1/doc/src/patterns/dist.md#L1-L45>

Implication:
- wrapper must expose individual packages through a package set

## 5.13 nixpkgs interop can replace or supplement PyPI deps

`uv2nix` docs show using wheels from nixpkgs or `pyproject.nix` hacks for prebuilt packages.

Source:
- nixpkgs wheels doc: <https://github.com/pyproject-nix/uv2nix/blob/60982c30e16db3e0cba6c0ed13f0894b06ab2bf1/doc/src/patterns/nixpkgs-wheels.md#L1-L64>

Implication:
- wrapper must leave room for package-set level overrides and interop hacks

## 5.14 Patching deps again depends on package-level overrides

Source:
- patching deps doc: <https://github.com/pyproject-nix/uv2nix/blob/60982c30e16db3e0cba6c0ed13f0894b06ab2bf1/doc/src/patterns/patching-deps.md#L1-L20>

Implication:
- wrapper needs low-level access, not just high-level venv/app constructors

## 5.15 Cross compilation is special and may need duplicated overrides

Cross build systems may need overrides for both build-host and target-host package sets.

Source:
- cross compilation doc: <https://github.com/pyproject-nix/uv2nix/blob/60982c30e16db3e0cba6c0ed13f0894b06ab2bf1/doc/src/patterns/cross/index.md#L1-L15>

Implication:
- wrapper should avoid hardcoded native-only assumptions
- probably out of scope for v1 sugar, but must not be blocked

## 5.16 Inline metadata scripts are separate upstream API

`uv2nix` has a separate `lib.scripts.loadScript` flow for PEP-723 scripts.

Source:
- inline metadata doc: <https://github.com/pyproject-nix/uv2nix/blob/60982c30e16db3e0cba6c0ed13f0894b06ab2bf1/doc/src/usage/inline-metadata.md#L1-L20>
- template: <https://github.com/pyproject-nix/uv2nix/blob/60982c30e16db3e0cba6c0ed13f0894b06ab2bf1/templates/inline-metadata/flake.nix>

Implication:
- likely separate API surface later
- should not distort initial workspace/project wrapper API

---

## 6. Evidence from source code and tests

### 6.1 `loadWorkspace` merges workspace config and computes defaults

`workspace.loadWorkspace`:
- parses lockfile
- discovers local projects
- loads selected `tool.uv.*` config
- creates `mkPyprojectOverlay`
- creates `mkEditablePyprojectOverlay`
- exposes dependency presets

Source:
- <https://github.com/pyproject-nix/uv2nix/blob/60982c30e16db3e0cba6c0ed13f0894b06ab2bf1/lib/workspace.nix#L93-L275>

### 6.2 `loadConfig` honors `tool.uv` knobs

Supported config includes:
- `compile-bytecode`
- `no-binary`
- `no-build`
- `no-binary-package`
- `no-build-package`
- `extra-build-dependencies`
- `extra-build-variables`

Source:
- <https://github.com/pyproject-nix/uv2nix/blob/60982c30e16db3e0cba6c0ed13f0894b06ab2bf1/lib/workspace.nix#L278-L357>

Implication:
- wrapper `sourcePreference` is a preference/default, not whole source selection policy

### 6.3 Remote package build logic confirms source selection complexity

The builder chooses wheel vs sdist using combined information from:
- workspace config
- per-package config
- user `sourcePreference`
- available compatible wheels

Source:
- <https://github.com/pyproject-nix/uv2nix/blob/60982c30e16db3e0cba6c0ed13f0894b06ab2bf1/lib/build.nix#L296-L335>

### 6.4 Test fixtures show breadth of cases

Fixtures include:
- conflicts
- dependency groups
- dynamic dependencies
- dynamic version
- git subdirectory
- multi-pythons
- no-binary / no-build
- optional deps
- supported environments
- workspace layouts
- legacy workspace behavior
- extra build dependencies/variables

Source:
- fixture tree under `lib/fixtures/`

Implication:
- wrapper should stay thin; upstream problem space broad

---

## 7. Local target examples and what they test

## 7.1 `flake-simple.nix`

Tests baseline desired shape:
- load project once
- create per-system Python scope from `pkgs`
- single `sourcePreference` knob
- `dependencies` at scope level, for package-set creation
- `dependencies` at venv level, for env install
- user still owns flake outputs

File:
- [`./flake-simple.nix`](./flake-simple.nix)

## 7.2 `flake-conflicts.nix`

Tests:
- multiple Python scopes from one loaded project
- conflicting dependency selections like CPU/CUDA
- separate scope-level `dependencies` for package-set creation and install-time `dependencies`

File:
- [`./flake-conflicts.nix`](./flake-conflicts.nix)

## 7.3 `flake-editable.nix`

Tests:
- editable config on Python scope
- non-store editable root
- subset editable members
- dev shell still manually constructed
- editable packages exposed for shell env

File:
- [`./flake-editable.nix`](./flake-editable.nix)

## 7.4 `flake-tests.nix`

Tests:
- package-set exposure enough for separate test derivations
- `mkVenv` enough for test env construction
- no generic `raw` bag needed for this pattern

File:
- [`./flake-tests.nix`](./flake-tests.nix)

---

## 8. Research conclusions

### 8.1 Thin wrapper, not replacement architecture

Strong conclusion from both docs and community discussion:
- wrapper should reduce ceremony
- wrapper should not hide upstream model completely
- wrapper should not dictate flake output architecture

### 8.2 Two levels of dependency choice are mandatory

Need separate concepts:
- **scope-level `dependencies`**: package-set selection while creating overlay/package set
- **env-level `dependencies`**: install selection for a particular venv/app

Without this, conflict groups are not representable cleanly.

### 8.3 Curated low-level access needed

Need direct access to useful low-level concepts such as package sets.

Probably enough:
- resolved package set
- editable package set
- helpers for venv/app creation

No evidence yet that a broad generic `raw` escape hatch is required.

### 8.4 Testing is good candidate for first-class wrapper support

Upstream testing pattern is consistent:
- tests are separate derivations
- test env is built from same resolved package set
- enabling named dependency group such as `test` is straightforward

This makes testing, especially `pytest`, a good candidate for dedicated wrapper support.

### 8.5 Editable support belongs at Python scope level

Editable support is fundamentally about constructing a separate package set.

### 8.6 Overlays remain necessary

Even with sugar, user-defined overlays remain core for:
- patching
- private deps
- build-system fixes
- nixpkgs interop
- source filtering

### 8.7 First version should stay focused

Good v1 target:
- workspace/project loading
- per-system Python scope construction
- source preference wiring
- same dependency value shape across scope/env/workspace APIs
- editable package-set support
- application helper
- package-set exposure

Later / maybe separate:
- inline scripts API
- structured override DSL
- source-filter helper DSL
- cross-compilation sugar
- flake-parts module

---

## 9. Outstanding questions carried into design

- remaining naming/details polish for secondary knobs such as `project.load`, `pythonBaseArgs`, and `sourcePreference`
- whether editable venv uses `mkVenv { editable = true; }` or separate constructor
- how much of package-set internals to expose beyond `pythonSet` and `editablePythonSet`
- exact policy for when users should fall back to `project.workspace` vs add explicit upstream flake inputs

See [`DESIGN.md`](./DESIGN.md) for current decisions and proposed API shape.
