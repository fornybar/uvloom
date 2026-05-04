# Implementation plan for uvloom v1

Implement `uvloom` as a thin, tested Nix wrapper around `uv2nix`, based on `plan/DESIGN.md`. Work TDD-first: add failing eval/build checks before implementing each public API slice, then make those checks pass. Preserve upstream concepts (`workspace`, `pythonSet`, overlays, dependency selections) while reducing boilerplate for common project, venv, app, editable, and pytest flows.

## Relevant files

- `flake.nix` - Exposes `uvloom.lib`; must also define dev/check wiring for eval and build tests.
- `lib/default.nix` - Public library entrypoint implementing `loadProject` and wiring `forPython`.
- `lib/scope.nix` - Python scope construction, overlay composition, venv/application/pytest/editable helpers.
- `lib/interpreter.nix` - Helper for omitted-interpreter selection from `workspace.requires-python`.
- `lib/packages.nix` - Helper for local workspace package candidate discovery and inference errors.
- `lib/errors.nix` - Shared clear error formatting for wrapper-owned validation failures.
- `test/fixtures/smiley-plot/pyproject.toml` - Simple single-package uv workspace fixture.
- `test/fixtures/smiley-plot/uv.lock` - Lockfile for simple fixture.
- `test/fixtures/multi-package/pyproject.toml` - Multi-local-package fixture for ambiguous package inference.
- `test/fixtures/multi-package/uv.lock` - Lockfile for multi-package fixture.
- `test/fixtures/editable/pyproject.toml` - Fixture for editable attr presence and `mkEditableVenv` eval.
- `test/fixtures/editable/uv.lock` - Lockfile for editable fixture.
- `test/fixtures/bad-python/pyproject.toml` - Fixture with impossible `requires-python` for negative interpreter-selection eval test.
- `test/fixtures/bad-python/uv.lock` - Lockfile for bad interpreter fixture if upstream load requires it.
- `test/eval.nix` - Positive eval checks for public API surface.
- `test/negative.nix` - Negative eval checks for expected wrapper errors.
- `test/builds.nix` - Real build checks: simple `mkVenv`, auto-venv `mkApplication`, and `mkPytestCheck`.
- `README.md` - Getting-started docs and API examples, if absent create it.
- `plan/flake-simple.nix` - Existing design example; use as reference for docs/tests.
- `plan/flake-editable.nix` - Existing editable design example; use as reference.
- `plan/flake-tests.nix` - Existing pytest design example; use as reference.

## Instructions for completing tasks

Before starting work, check the current state of tasks (find out what has already been completed), and read the Notes section.

**IMPORTANT:** As you complete each task, you must check it off in this markdown file by changing `- [ ]` to `- [x]`. This helps track progress and ensures you don't skip any steps.

Example:
- `- [ ] 1.1 Read file` → `- [x] 1.1 Read file` (after completing)

Update the file after completing each sub-task, not just after completing an entire parent task.

If applicable, update the Notes section with lessons, discoveries and design choices that may be of interest to the engineer that takes on the next parent task, assuming they are not aware of any of the thought processes so far and only see the result of the finalized tasks prior.

## Tasks

- [x] 1.0 Establish TDD fixture and check harness
  - [x] 1.1 Inspect upstream input shapes in `flake.lock`/Nix repl or eval snippets, especially `uv2nix.lib.workspace.loadWorkspace`, `workspace.deps.default`, `workspace.requires-python`, and build-system overlay attrs.
  - [x] 1.2 Create minimal `test/fixtures/smiley-plot` package with `pyproject.toml`, source module, CLI entrypoint, tests, and `uv.lock`.
  - [x] 1.3 Create `test/fixtures/multi-package` with at least two declared local workspace members for ambiguous inference tests.
  - [x] 1.4 Create `test/fixtures/editable` or reuse `smiley-plot` if sufficient for editable eval tests.
  - [x] 1.5 Create `test/fixtures/bad-python` with unsatisfied `requires-python` for omitted-interpreter negative test.
  - [x] 1.6 Add initial `test/eval.nix`, `test/negative.nix`, and `test/builds.nix` with expected failing assertions for v1 surface.
  - [x] 1.7 Wire `flake.nix` checks so `nix flake check` runs eval checks and selected real build checks.

- [ ] 2.0 Implement project loading and Python scope construction
  - [x] 2.1 Create `lib/default.nix` so existing `flake.nix` import succeeds.
  - [x] 2.2 Implement `loadProject { root = ...; }` using `uv2nix.lib.workspace.loadWorkspace { workspaceRoot = root; }`.
  - [x] 2.3 Return project attrs `workspace` and `forPython`; do not expose `project.deps`, `project.dependencies`, or `raw`.
  - [x] 2.4 Implement `forPython` required `pkgs` arg and optional args: `interpreter`, `sourcePreference ? "wheel"`, `dependencies ? workspace.deps.default`, `overlays ? [ ]`, `editable`, `environ ? { }`, `stdenv ? pkgs.stdenv`.
  - [x] 2.5 Implement omitted-interpreter selection from `workspace.requires-python`; on failure throw clear `uvloom.forPython` error containing requires-python value when available.
  - [x] 2.6 Validate `overlays` is list; throw wrapper error when not list.
  - [x] 2.7 Validate build-system overlay lookup for `sourcePreference`; on miss, list available keys from `pyproject-build-systems.overlays`.
  - [x] 2.8 Build base Python package set via `pkgs.callPackage pyproject-nix.build.packages { python = resolvedInterpreter; inherit stdenv; }`.
  - [x] 2.9 Compose overlays in contract order: selected build-system overlay, generated uv overlay, user overlays.
  - [x] 2.10 Expose `scope.pythonSet` as exact final non-editable package set.

- [x] 3.0 Implement virtual environment and editable environment helpers
  - [x] 3.1 Add failing positive eval test for `scope.mkVenv { name = "..."; }` with default dependencies.
  - [x] 3.2 Implement `mkVenv { name, dependencies ? workspace.deps.default; } = pythonSet.mkVirtualEnv name dependencies`.
  - [x] 3.3 Add real build check for simple `mkVenv` fixture.
  - [x] 3.4 Add failing eval tests confirming `editablePythonSet` and `mkEditableVenv` are absent when `editable` config omitted.
  - [x] 3.5 Add failing eval tests confirming editable attrs are present when `editable = { root = "$REPO_ROOT"; members = [ "smiley-plot" ]; };` is provided.
  - [x] 3.6 Validate `editable.root` is string-only; add negative eval test for non-string root.
  - [x] 3.7 Implement editable overlay with `workspace.mkEditablePyprojectOverlay`, passing `members` only when supplied.
  - [x] 3.8 Implement `editablePythonSet = pythonSet.overrideScope editableOverlay`.
  - [x] 3.9 Implement `mkEditableVenv` mirroring `mkVenv` but using `editablePythonSet`.

- [x] 4.0 Implement package inference, lookup errors, and application helper
  - [x] 4.1 Investigate reliable way to obtain declared local workspace package names from `workspace`; document chosen upstream attrs in Notes.
  - [x] 4.2 Add tests for package inference: single local package succeeds, multiple local packages error lists candidates.
  - [x] 4.3 Add tests for requested missing package: error includes helper name, requested package, and available local candidates.
  - [x] 4.4 Implement shared package resolver for helpers with `package ? null`.
  - [x] 4.5 Implement package pre-check against `scope.pythonSet.${package}` before calling helper internals.
  - [x] 4.6 Add failing eval/build test for `scope.mkApplication { package = "smiley-plot"; venv = ...; }`.
  - [x] 4.7 Implement `scope.mkApplication` by wrapping `pyproject-nix.build.util.mkApplication`.
  - [x] 4.8 Implement omitted `venv` behavior: auto-create `scope.mkVenv { name = "${resolvedPackageName}-env"; }`.
  - [x] 4.9 Pass through optional `pname` and `version` when provided.
  - [x] 4.10 Add real build check for auto-venv `mkApplication`.

- [x] 5.0 Implement pytest check helper with derived test scope
  - [x] 5.1 Refactor scope construction into internal reusable function so `mkPytestCheck` can derive sibling test scopes from current config.
  - [x] 5.2 Add eval tests for `scope.mkPytestCheck { package = "smiley-plot"; groups = [ "test" ]; }` returning derivation-suitable value.
  - [x] 5.3 Add tests that omitted `package` uses same inference and ambiguity errors as `mkApplication`.
  - [x] 5.4 Add tests that omitted/null `dependencies` expands to `{ ${resolvedPackageName} = groups; }`.
  - [x] 5.5 Add tests that explicit `dependencies` replaces auto-expanded group selection.
  - [x] 5.6 Implement `mkPytestCheck` args: `package ? null`, `groups ? [ "test" ]`, `dependencies ? null`, `name ? "${resolvedPackageName}-pytest"`, `paths ? [ "tests" ]`, `pytestFlags ? [ ]`, `env ? { }`, `nativeBuildInputs ? [ ]`.
  - [x] 5.7 Build internal `testScope` from current `forPython` args plus selected test dependencies.
  - [x] 5.8 Build `pytestVenv = testScope.mkVenv { name = "${resolvedPackageName}-pytest-env"; dependencies = testDependencies; }`.
  - [x] 5.9 Return `stdenv.mkDerivation` with `src = testScope.pythonSet.${package}.src`, `nativeBuildInputs = [ pytestVenv ] ++ nativeBuildInputs`, `env`, `dontConfigure = true`, pytest `buildPhase`, and `installPhase = "touch $out"`.
  - [x] 5.10 Use `lib.escapeShellArgs` for `paths` and `pytestFlags` in `buildPhase`.
  - [x] 5.11 Add real build check for one fixture `mkPytestCheck`.

- [ ] 6.0 Polish examples, docs boundaries, and final flake checks
  - [x] 6.1 Run `nix flake check`; fix all eval and build failures.
  - [x] 6.2 Split `lib/default.nix` into public entrypoint plus focused scope/interpreter/package/error helpers.
  - [ ] 6.3 Ensure required eval coverage from `plan/DESIGN.md` §16.2 exists: `loadProject`, `forPython`, `scope.pythonSet`, `mkVenv`, `mkApplication`, `scope.mkPytestCheck`, editable attr presence/absence, `mkEditableVenv`.
  - [ ] 6.4 Ensure required negative coverage exists: omitted interpreter unsatisfied, bad `sourcePreference`, ambiguous inferred package, requested package absent, `overlays` not list, `editable.root` not string.
  - [ ] 6.5 Ensure required real builds exist: simple `mkVenv`, auto-venv `mkApplication`, one `mkPytestCheck`.
  - [ ] 6.6 Add or update `README.md` with minimal examples for load project, `forPython`, `mkVenv`, `mkApplication`, editable shell, pytest check, and `project.workspace` escape-hatch boundary.
  - [ ] 6.7 Compare docs/examples with `plan/flake-simple.nix`, `plan/flake-editable.nix`, and `plan/flake-tests.nix`; align names and API shape.
  - [ ] 6.8 Remove accidental internal API exposure such as generic `raw`, dependency preset aliases, or extra package-set aliases.
  - [ ] 6.9 Update Notes with any deviations from `plan/DESIGN.md` and why.

## Notes

- Follow `plan/DESIGN.md` as source of truth for v1 API shape and non-goals.
- Keep wrapper thin. Validate wrapper-owned control flow and lookup errors only; defer upstream schema validation to upstream libraries.
- Use fixture package name `smiley-plot` to align with existing design examples unless implementation discovers this is costly.
- Upstream `uv2nix.lib.workspace.loadWorkspace` returns `config`, `deps`, `mkPyprojectOverlay`, `mkEditablePyprojectOverlay`, and `requires-python`; `workspace.deps` has `all`, `default`, `groups`, and `optionals`.
- `pyproject-build-systems.overlays` currently exposes `default`, `sdist`, and `wheel`.
- Local package inference uses `builtins.attrNames workspace.deps.default`, avoiding wrapper-side uv workspace glob parsing.
- Omitted interpreter selection scans available `pkgs.python*` interpreters and matches `workspace.requires-python` with `pyproject-nix.lib.pep440` comparators.
- Library code is split by responsibility: `default.nix` public entrypoint, `scope.nix` composition/helpers, `interpreter.nix` Python selection, `packages.nix` package inference/checks, `errors.nix` throw/show helpers.
- NixOS command order: run commands directly first; if missing and flake dev shell exists, use `nix develop -c`; else use `nix run nixpkgs#<pkg> --command <command>`.
