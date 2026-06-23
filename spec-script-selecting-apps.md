# Spec: Script-selecting package apps for uvloom

## Introduction / overview

uvloom currently exposes `scope.app` in two modes:

- **Package mode**: `scope.app { package = "my-project"; }` builds a Python package application output through `pyproject-nix.build.util.mkApplication`.
- **Command mode**: `scope.app { name = "tool"; command = [ "python" ./app.py ]; }` builds a wrapper around an explicit command.

Package mode works well for packages with one console script. It is less precise for packages that expose multiple console scripts via `[project.scripts]`: the resulting app package contains every executable installed into the generated virtual environment. Setting `pname` changes package metadata/output naming, but does not select which binary the app represents.

Add a `script` argument to package-mode `scope.app`. When set, uvloom builds a narrow app output containing only one selected executable from the venv. `script` means executable basename in `${venv}/bin` and the output binary name in `$out/bin`. It is often a PEP 621 `[project.scripts]` command, but may also come from dependencies or custom build behavior.

This makes flake outputs clearer for downstream Docker images, NixOS services, CI jobs, and other consumers that expect one package to represent one command.

## Goals

1. Allow users to create one uvloom app package for one executable installed in a package venv.
2. Preserve current `scope.app { package = ...; }` behavior when `script` is omitted.
3. Preserve current command mode behavior when `command` is used.
4. Make script-mode command naming unambiguous: `$out/bin/${script}` only.
5. Provide clear validation errors for invalid `script` use.
6. Document the new API across README and docs.
7. Cover the feature with eval, build, and negative tests, including a tiny multi-script fixture to prove sibling scripts are excluded.

## Functional requirements

1. `scope.app` must accept a new optional argument named `script`.

2. `script = null` or omitted must preserve existing behavior:
   - package mode continues to delegate to `pyproject-nix.build.util.mkApplication`;
   - package-mode outputs continue to expose all executables from the package application output;
   - command mode remains unchanged.

3. When `script` is a non-empty string in package mode, uvloom must build an app derivation exposing exactly one executable:

   ```nix
   scope.app {
     package = "smiley-plot";
     script = "smiley-plot";
   }
   ```

   Expected output shape:

   ```text
   $out/bin/smiley-plot
   ```

4. In script mode, `script` must select an executable from the generated or supplied virtual environment:

   ```text
   ${venv}/bin/${script}
   ```

   uvloom does not need to parse `[project.scripts]`. The selected executable may come from package console scripts, dependencies, or custom build behavior. `script` is a venv executable basename, not strictly a PEP 621 script key.

5. In script mode, output binary name must always equal `script`.

   Script mode must not support binary renaming. If users want a different command name, they should rename the console script upstream in `pyproject.toml` or whichever build mechanism creates the executable.

6. In script mode, derivation naming/version metadata must follow existing package-mode expectations where possible:
   - default `version` comes from the selected local package (`pythonSet.${packageName}.version`) via explicit assignment or equivalent behavior;
   - explicit `version` overrides default version;
   - `pname`, when explicitly provided, controls derivation package name metadata only and does not affect the output binary name;
   - when `pname` is omitted, derivation `pname` should default to `script`.

7. In script mode, the app derivation should preserve useful package metadata where feasible:
   - inherit `meta` from `pythonSet.${packageName}`;
   - inherit `passthru` from `pythonSet.${packageName}` only if practical and compatible with the builder used.

   Metadata preservation is desirable but not a hard blocker for the first implementation unless tests or downstream usage reveal a regression.

8. `scope.app` must fail during evaluation when `script` is used with command mode:

   ```nix
   scope.app {
     name = "bad";
     command = [ "python" "-c" "print(1)" ];
     script = "smiley-plot";
   }
   ```

   Suggested error:

   ```text
   uvloom.app: pass `script` only with package mode
   ```

9. `scope.app` must fail during evaluation when `script` is not a non-empty string:
   - `script = ""` fails;
   - `script = 123` fails;
   - `script = [ "tool" ]` fails.

   Suggested error:

   ```text
   uvloom.app: `script` must be a non-empty string
   ```

10. In script mode, `script` and `pname` must not contain `/`. `pname`, when provided, must be a non-empty string. Invalid values must fail during evaluation.

    Suggested errors:

    ```text
    uvloom.app: `script` must not contain `/` when using script mode
    uvloom.app: `pname` must be a non-empty string when using script mode
    uvloom.app: `pname` must not contain `/` when using script mode
    ```

11. Script mode must fail during evaluation when `name` is provided. `name` would imply output binary renaming, which script mode intentionally does not support.

    Suggested error:

    ```text
    uvloom.app: `name` cannot be used with `script`; the output binary name is `script`
    ```

12. If `${venv}/bin/${script}` does not exist or is not executable, the script-mode derivation must fail during build.

    Suggested error:

    ```text
    uvloom.app: script `missing-script` not found in venv for package `smiley-plot`
    ```

13. Script mode must work with generated venvs:

    ```nix
    scope.app {
      package = "smiley-plot";
      script = "smiley-plot";
    }
    ```

14. Script mode must work with explicitly supplied venvs:

    ```nix
    let
      appVenv = scope.venv { name = "smiley-plot-env"; };
    in
    scope.app {
      package = "smiley-plot";
      script = "smiley-plot";
      venv = appVenv;
    }
    ```

15. Script mode must not add command-mode-only behavior:
    - no `pythonPath` support in package/script mode;
    - no `workingDirectory` support in package/script mode;
    - no shell command parsing.

## Non-goals / out of scope

1. Do not parse `pyproject.toml` or `[project.scripts]` to discover valid scripts.
2. Do not infer one app per script automatically.
3. Do not remove or alter existing package mode that exposes all executables.
4. Do not make `pname` a script selector.
5. Do not support binary renaming in script mode.
6. Do not add script selection to `scope.app.editable` as part of this change.
7. Do not redesign command mode.
8. Do not auto-discover or auto-generate apps for every script in a multi-script package.

## Technical considerations

### Current implementation location

Main implementation lives in `lib/scope.nix`, inside `mkApplication`.

Current high-level structure:

```nix
mkApplication =
  {
    package ? null,
    venv ? null,
    pname ? null,
    version ? null,
    name ? pname,
    command ? null,
    pythonPath ? [ ],
    workingDirectory ? workspaceRoot,
  }:
  if command != null then
    ... command mode ...
  else
    ... package mode ...
```

Add `script ? null` to this argument set.

### Suggested control flow

1. If `command != null`, handle command mode.
2. In command mode, reject `script != null` before continuing with existing validation.
3. Else handle package mode.
4. In package mode:
   - resolve `packageName` as today;
   - construct `appPackage = pythonSet.${packageName}`;
   - construct `appVenv = if venv == null then mkVenv { name = "${packageName}-env"; } else venv;`;
   - if `script == null`, use existing `pyproject-nix.build.util.mkApplication` path unchanged;
   - if `script != null`, validate script-mode fields and build narrow wrapper derivation.

Pseudo-code:

```nix
mkApplication =
  {
    package ? null,
    venv ? null,
    pname ? null,
    version ? null,
    name ? pname,
    command ? null,
    script ? null,
    pythonPath ? [ ],
    workingDirectory ? workspaceRoot,
  }:
  if command != null then
    if script != null then
      errors.fail "app" "pass `script` only with package mode"
    else
      ... existing command mode ...
  else
    let
      packageName = packageLib.resolveLocalPackage "app" candidates pythonSet package;
      appPackage = pythonSet.${packageName};
      appVenv = if venv == null then mkVenv { name = "${packageName}-env"; } else venv;
    in
    if script == null then
      (pkgs.callPackage pyproject-nix.build.util { }).mkApplication (
        {
          venv = appVenv;
          package = appPackage;
        }
        // lib.optionalAttrs (pname != null) { inherit pname; }
        // lib.optionalAttrs (version != null) { inherit version; }
      )
    else
      ... script mode ...
```

### Script-mode builder

A narrow wrapper derivation can be implemented with `pkgs.runCommand`.

Use symlink, not shell wrapper, unless tests reveal symlink behavior is insufficient. Symlink keeps behavior close to the original console script generated in the venv and preserves the invariant that output binary name equals `script`.

Pseudo-code:

```nix
let
  appName = script;
  appPname = if pname != null then pname else script;
  appVersion = if version != null then version else appPackage.version;
  sourceScript = "${appVenv}/bin/${script}";
in
pkgs.runCommand "${appPname}-${appVersion}"
  {
    pname = appPname;
    version = appVersion;
    meta = appPackage.meta or { };
    passthru = appPackage.passthru or { };
  }
  ''
    mkdir -p "$out/bin"
    if [ ! -x ${lib.escapeShellArg sourceScript} ]; then
      echo ${lib.escapeShellArg "uvloom.app: script `${script}` not found in venv for package `${packageName}`"} >&2
      exit 1
    fi
    ln -s ${lib.escapeShellArg sourceScript} "$out/bin/${appName}"
  ''
```

Validation rejects slash-containing `script` and `pname` values. This prevents nested output paths and path traversal-like surprises. Do not build target paths by embedding `lib.escapeShellArg appName` inside a double-quoted `$out/bin/...` string. Either reject unsafe path characters as above or compute a fully shell-escaped target path separately.

### Validation style

Use existing `errors.fail "app" ...` style from `lib/scope.nix`.

Evaluation-time validation should cover type/empty checks because those are known without building:

```nix
else if script != null && !builtins.isString script then
  errors.fail "app" "`script` must be a non-empty string"
else if script == "" then
  errors.fail "app" "`script` must be a non-empty string"
else if lib.hasInfix "/" script then
  errors.fail "app" "`script` must not contain `/` when using script mode"
else if name != null then
  errors.fail "app" "`name` cannot be used with `script`; the output binary name is `script`"
else if pname != null && (!builtins.isString pname || pname == "") then
  errors.fail "app" "`pname` must be a non-empty string when using script mode"
else if pname != null && lib.hasInfix "/" pname then
  errors.fail "app" "`pname` must not contain `/` when using script mode"
else
  ... builder ...
```

Build-time validation should cover filesystem checks inside `${appVenv}/bin`.

### Compatibility notes

- Existing users of `scope.app { pname = "custom"; }` in package mode must not see behavior changes when `script` is omitted.
- Existing users of command mode must not see behavior changes unless they also pass `script`, which should fail clearly.
- `name` currently defaults to `pname`; do not change command mode semantics.
- In package mode without `script`, `name` is currently ignored. Preserve that behavior unless a separate future cleanup changes it.
- In package mode with `script`, reject `name` so users do not confuse it for a supported binary rename API.

## Documentation requirements

Update all relevant user-facing docs and examples because user selected broad docs scope.

Minimum updates:

1. `README.md`
   - Mention `script` in quick examples or package app section.
   - Include short package-with-one-script example if space allows.

2. `docs/reference.md`
   - Add `script` to package mode arguments table.
   - Explain script mode naming rule: output binary is always `script`; `name` is rejected; `pname` only controls derivation metadata.
   - Add validation rules for `script`.
   - Add example showing one selected script.

3. `docs/how-to.md`
   - Add how-to entry: “Build one app for one console script”.
   - Show selected script output and explain that renaming is intentionally unsupported.

4. `docs/intro.md`, `docs/tutorial.md`, `docs/index.md`, `docs/explanation.md`
   - Add or adjust mentions where `scope.app` is described as console-script application wrapper.
   - Avoid overloading introductory docs with edge-case detail; one sentence/link to reference is enough.

Docs should make clear:

- `package` chooses package/dependencies/metadata.
- `script` chooses executable basename from venv `bin`; it is often but not necessarily a PEP 621 `[project.scripts]` key.
- Output binary name is always `script` in script mode.
- `name` is rejected in script mode.
- `pname` controls derivation metadata only in script mode and does not rename `$out/bin/...`.
- Omitting `script` keeps current all-executables package app behavior.

## Test plan

Use existing test infrastructure. Add a tiny multi-script fixture because the feature is specifically about packages with multiple console scripts.

### Fixture

Add a small local fixture package with two console scripts, for example `test/fixtures/multi-script-app`:

```toml
[project]
name = "multi-script-app"
version = "0.1.0"
requires-python = ">=3.12,<3.13"

[project.scripts]
first-tool = "multi_script_app:first"
second-tool = "multi_script_app:second"
```

Implementation can be minimal Python functions that print distinct strings.

### Eval tests

Update `test/eval.nix`:

1. Add script-mode app using existing single-script fixture:

   ```nix
   scriptApplication = scope.app {
     package = "smiley-plot";
     script = "smiley-plot";
   };
   ```

2. Add multi-script app selecting only `first-tool`.
3. Add `pname` metadata-only script app and assert/verify it still exposes `$out/bin/smiley-plot`, not `$out/bin/<pname>`.
4. Assert all derivations evaluate.

### Build tests

Update `test/builds.nix`:

1. Add check output for script-mode app.
2. Add check output for multi-script fixture selecting `first-tool`.
3. Add check output for `pname` metadata-only behavior.
4. Verify selected binary exists:

   ```sh
   test -x $out/bin/smiley-plot
   ```

5. Verify sibling script from multi-script fixture is not present:

   ```sh
   test -x $out/bin/first-tool
   test ! -e $out/bin/second-tool
   ```

6. Verify `pname` does not rename output binary in script mode:

   ```sh
   test -x $out/bin/smiley-plot
   test ! -e $out/bin/custom-smiley-plot
   ```

7. If easy, run selected multi-script command and assert it prints expected output.

### Negative eval tests

Update `test/negative.nix` with assertions for:

1. `script` with command mode fails.
2. `script = ""` fails.
3. `script` non-string fails.
4. `script = "nested/tool"` fails.
5. any `name` value with script mode fails.
6. `pname = ""` with script mode fails.
7. `pname` non-string with script mode fails.
8. `pname = "nested/tool"` with script mode fails.

Example:

```nix
assert fails (
  scope.app {
    package = "smiley-plot";
    script = "";
  }
);
```

### Missing script build test

If current negative test harness only handles evaluation failures, do not force a build-time failure test there. Instead add a normal derivation/check that intentionally tries to build missing script only if existing CI patterns support expected-failure builds. Otherwise rely on builder error and document manual verification.

Manual verification command:

```sh
nix build '.#checks.x86_64-linux.missing-script-application' -L
```

Expected log contains:

```text
uvloom.app: script `missing-script` not found in venv for package `smiley-plot`
```

## Success metrics

Implementation is complete when:

1. Existing tests pass unchanged for current package mode and command mode.
2. `scope.app { package = "smiley-plot"; script = "smiley-plot"; }` builds.
3. The built output contains `$out/bin/smiley-plot`.
4. Script mode rejects `name` because output binary name must equal `script`.
5. Invalid `script` usage fails at evaluation with clear uvloom errors.
6. Missing/non-executable selected scripts fail during build with a clear uvloom error.
7. Multi-script fixture proves selected output contains `first-tool` and excludes `second-tool`.
8. `pname` in script mode affects derivation metadata only and does not rename `$out/bin/...`.
9. README and docs describe script mode accurately.
10. `nix flake check` or project CI check set passes on supported systems.

## Suggested implementation order

1. Update `lib/scope.nix` function signature to include `script ? null`.
2. Add command-mode rejection for `script != null`.
3. Refactor package-mode branch to bind `packageName`, `appPackage`, and `appVenv` once.
4. Add script-mode evaluation validation.
5. Add script-mode `runCommand` builder.
6. Add eval/build/negative tests.
7. Run targeted checks.
8. Update docs and README.
9. Run formatter if project has one.
10. Run full check suite or closest available CI equivalent.

## Open follow-up ideas

These are intentionally out of scope for this spec:

1. Add a helper that auto-generates an attrset of apps from discovered scripts.
2. Extend similar script-selection semantics to `scope.app.editable` if users need it.
3. Add richer docs for NixOS service/Docker image use cases.
