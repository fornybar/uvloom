# DESIGN INTERVIEW

Running summary of design interview for `uvloom`.

Status: complete
Last updated: 2026-04-25 (post-review updates included)

## Settled decisions so far

### 1. `loadProject`
- `loadProject` accepts only `path` values for `root`.
- Missing `pyproject.toml` / `uv.lock` validation is deferred to upstream.
- v1 accepts only `{ root = ...; }`; no pre-loaded workspace escape hatch.

### 2. `forPython`
- `interpreter` is optional.
- If `interpreter` is omitted, wrapper delegates interpreter selection to upstream `requires-python`-aware functionality using workspace metadata and available interpreters from `pkgs`.
- No `.python-version` support in v1.
- If no compatible interpreter can be selected, wrapper should surface a clear `uvloom.forPython` error with the workspace `requires-python` value when available.
- If provided explicitly, `interpreter` is trusted without wrapper type validation.

### 3. `sourcePreference`
- Default is `"wheel"`.
- Wrapper validates its own build-system overlay lookup for this value.
- If no matching `pyproject-build-systems.overlays.${sourcePreference}` exists, wrapper throws clear error listing available overlay keys.
- Wrapper otherwise passes value to uv2nix without duplicating upstream source-selection validation.

### 4. Scope-level `dependencies`
- Default is upstream workspace default dependency selection.
- Main docs/examples should usually omit this default rather than spelling `project.workspace.deps.default`.

### 5. Overlay handling
- User `overlays` default to `[]`.
- Wrapper itself includes matching build-system overlay by default, keyed off `sourcePreference`.
- Composition order is locked:
  1. wrapper-selected build-system overlay
  2. generated uv overlay
  3. user overlays
- `overlays` accepts list only.

### 6. Editable config
- `editable.root` is string-only.
- `editable.members` omitted => defer to upstream default behavior.
- `editable.members = []` is passed through literally.
- Unknown editable member validation is deferred to upstream.

### 7. `environ`
- Default is `{}`.
- Wrapper passes through keys/values without validation.

### 8. `mkVenv`
- `name` is required.
- `dependencies` defaults to upstream workspace default dependency selection.
- No additional convenience args in v1.

### 9. `mkApplication`
- `package` is string package name in wrapper API.
- Wrapper may infer `package` if there is exactly one local workspace package.
- Explicit `package` remains allowed.
- `venv` is optional; if omitted/null, wrapper auto-builds venv from default dependencies.
- If `venv` is omitted, wrapper auto-creates `scope.mkVenv { name = "${resolvedPackageName}-env"; }`.
- `pname` and `version` overrides are allowed and passed through.

### 10. `scope.mkPytestCheck`
- Helper lives on `scope` to keep common API simple.
- It derives an internal test scope from current scope construction args plus test dependency selection, so users do not need to add test groups to the original scope.
- Dependency arg is `groups`, not `dependencyGroup`.
- `groups ? [ "test" ]`.
- If `dependencies` omitted/null, helper expands `groups` into `{ ${package} = groups; }` and uses that for both internal test package set and test venv.
- If `dependencies` is provided, it is full test dependency selection, useful for conflict/group combinations like `{ my-app = [ "cuda" "test" ]; }`.
- `package ? null`; infer only if exactly one local workspace package exists.
- Explicit `package` remains allowed.
- `editable` support is dropped from v1.
- Source strategy uses `testScope.pythonSet.${package}.src` from internally created test scope.
- Successful check can simply `touch $out`.
- `paths ? [ "tests" ]`.
- Keep `pytestFlags ? [ ]`, `env ? { }`, and `nativeBuildInputs ? [ ]` in v1.
- Derivation contract:
  - create internal `testScope` from current scope construction args plus test dependency selection
  - use `stdenv.mkDerivation`
  - `name = "${package}-pytest"` unless overridden
  - `src = testScope.pythonSet.${package}.src`
  - `nativeBuildInputs = [ pytestVenv ] ++ nativeBuildInputs`
  - pass `env` through
  - `dontConfigure = true`
  - `buildPhase` runs `pytest` over chosen `paths` and `pytestFlags` using shell-escaped args
  - `installPhase` defaults to `touch $out`
  - working dir is unpacked source root
  - return plain derivation suitable for `checks`

### 11. `stdenv`
- `forPython.stdenv` defaults to `pkgs.stdenv`.
- Custom `stdenv` is used for base package-set construction.
- Wrapper-created helper derivations should use same chosen `stdenv`.
- No public `scope.stdenv` attr in v1.

### 12. Low-level exposure / naming
- `scope.pythonSet` is exact final non-editable Python set used by scope helpers.
- `scope.editablePythonSet` is exact final editable Python set used by editable helpers.
- Names intentionally match common upstream `pythonSet` terminology.
- When editable config is absent, `scope.editablePythonSet` is fully absent, not `null`.
- No parallel alias attrs like `scope.packages`, `scope.pythonPackages`, or `scope.editablePackages`.

### 13. Inference of “local workspace package”
- Inference uses declared local workspace members only.
- It should not include arbitrary path dependencies from lock file.
- No new public attr for candidate package lists.
- Error messages should list candidate package names when inference is ambiguous.

### 14. `mkEditableVenv`
- `mkEditableVenv` mirrors `mkVenv` arg shape.
- `name` is required.
- `dependencies` defaults to upstream workspace default dependency selection.
- It should not implicitly default to `deps.all` or to scope-level `dependencies`.
- Attr exists only when scope was created with `editable` config.
- When editable config is absent, `scope.mkEditableVenv` is fully absent, not present-and-throwing.

### 15. Smoke checks / fixtures
- Keep example flakes as smoke fixtures.
- Required eval coverage:
  - `loadProject`
  - `forPython`
  - `scope.pythonSet`
  - `mkVenv`
  - `mkApplication`
  - editable attr presence/absence
  - `mkEditableVenv`
  - `scope.mkPytestCheck`
- Required negative eval coverage:
  - omitted `interpreter` with unsatisfied/unselectable `requires-python`
  - `sourcePreference` with no matching build-system overlay
  - ambiguous inferred package
  - requested package absent from helper package set
  - `overlays` not list
  - `editable.root` not string
- Required real builds:
  - one simple `mkVenv`
  - one auto-venv `mkApplication`
  - one `scope.mkPytestCheck`
- Editable path may stay eval-only initially if CI/runtime setup cost is high.

### 16. Docs boundary for `project.workspace`
- `project.workspace` stays public as advanced upstream escape hatch.
- Main docs/examples should not put `project.workspace` front and center.
- Main path should prefer:
  - omitted defaults
  - literal `dependencies = { ...; }` selections when customization is needed
- Good escape-hatch uses include:
  - `workspace.deps.*`
  - `mkPyprojectOverlay`
  - `mkEditablePyprojectOverlay`
  - other narrow upstream interop cases
- If user needs broader upstream composition primitives directly, docs should tell them to add explicit upstream inputs instead of depending on uvloom internals.

### 17. v1 validation policy
- Keep wrapper validation focused.
- Wrapper should throw clear errors for wrapper-owned control-flow/inference/lookup failures:
  - no compatible interpreter selected from workspace `requires-python`
  - no build-system overlay matching `sourcePreference`
  - ambiguous inferred package name
- Wrapper should not duplicate upstream validation for:
  - dependency schema
  - overlay element types beyond requiring list shape
  - editable member existence
  - `environ` key correctness
  - root contents or missing files beyond upstream failure

### 18. Helper package lookup errors
- When `mkApplication` resolves explicit or inferred package name, wrapper should pre-check package presence in `scope.pythonSet`.
- When `scope.mkPytestCheck` resolves explicit or inferred package name, wrapper should pre-check package presence in internal `testScope.pythonSet`.
- On failure, throw clear wrapper error instead of leaking raw missing-attr error.
- Error should include:
  - helper name
  - requested package name
  - available local workspace package candidates

### 19. v1 scope freeze
- Freeze v1 core API at current decisions.
- Do not keep interviewing deferred helper families yet.
- Next step:
  1. update `plan/DESIGN.md` to match interview record
  2. align example flakes with final names and behavior
  3. implement API and smoke checks
