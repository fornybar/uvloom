# Implementation plan for script-selecting package apps

Implement `scope.app { package = "..."; script = "..."; }` for uvloom package mode. The feature lets a package app expose exactly one executable from the generated or supplied venv at `$out/bin/${script}`. Script mode intentionally does not support binary renaming: the Python script name is the Nix output binary name. Existing package mode and command mode must stay compatible when `script` is omitted.

Work test-first in vertical slices. Add one observable behavior test, make the smallest implementation change to pass it, then continue.

## Relevant files

- `spec-script-selecting-apps.md` - Source spec for expected behavior and constraints.
- `lib/scope.nix` - Contains `mkApplication`; main implementation location for `scope.app` package/command modes.
- `test/eval.nix` - Evaluation checks for public `scope.app` expressions.
- `test/builds.nix` - Build checks for public flake/check outputs and output filesystem behavior.
- `test/negative.nix` - Expected evaluation-failure checks for invalid public API usage.
- `test/fixtures/multi-script-app/pyproject.toml` - New fixture package with multiple console scripts.
- `test/fixtures/multi-script-app/src/multi_script_app/__init__.py` - New fixture module implementing two tiny console-script entrypoints.
- `README.md` - User-facing overview and examples for `scope.app`.
- `docs/reference.md` - API reference for `scope.app`; should document `script`, validation, and naming rules.
- `docs/how-to.md` - How-to docs; should include selecting one console script.
- `docs/intro.md` - Intro docs; should mention package apps can select one script.
- `docs/tutorial.md` - Tutorial docs; may need light mention/link depending current flow.
- `docs/index.md` - Docs landing page; may need brief mention if it summarizes `scope.app`.
- `docs/explanation.md` - Conceptual docs; should explain why package mode can expose all executables and when `script` narrows output.

## Instructions for completing tasks

Before starting work, check the current state of tasks (find out what has already been completed), and read the Notes section.

**IMPORTANT:** As you complete each task, you must check it off in this markdown file by changing `- [ ]` to `- [x]`. This helps track progress and ensures you don't skip any steps.

Example:
- `- [ ] 1.1 Read file` → `- [x] 1.1 Read file` (after completing)

Update the file after completing each sub-task, not just after completing an entire parent task.

If applicable, update the Notes section with lessons, discoveries and design choices that may be of interest to the engineer that takes on the next parent task, assuming they are not aware of any of the thought processes so far and only see the result of the finalized tasks prior.

## Tasks

- [x] 1.0 Add tracer-bullet script mode for one package executable
  - [x] 1.1 RED: Add one failing behavior check in `test/builds.nix` for `scope.app { package = "smiley-plot"; script = "smiley-plot"; }` that builds and exposes `$out/bin/smiley-plot`.
  - [x] 1.2 GREEN: Add `script ? null` to `mkApplication` in `lib/scope.nix` and implement minimal package-mode script branch that symlinks `${appVenv}/bin/${script}` to `$out/bin/${script}`.
  - [x] 1.3 GREEN: Preserve existing package mode when `script == null` by continuing to call `pyproject-nix.build.util.mkApplication` exactly as before.
  - [x] 1.4 REFACTOR: Bind `packageName`, `appPackage`, and `appVenv` once in package mode if it reduces duplication without changing behavior.
  - [x] 1.5 VERIFY: Run targeted build/eval check for the new script app and existing package app.

- [x] 2.0 Prove multi-script package output excludes sibling executables
  - [x] 2.1 RED: Add `test/fixtures/multi-script-app` with two console scripts, `first-tool` and `second-tool`, and add a failing build check selecting `first-tool` that asserts `$out/bin/first-tool` exists and `$out/bin/second-tool` does not.
  - [x] 2.2 GREEN: Extend test fixture loading/test setup as needed so uvloom can build the multi-script package fixture.
  - [x] 2.3 GREEN: Adjust script-mode implementation only if the multi-script behavior fails; output should contain only the selected symlink.
  - [x] 2.4 RED: Add a behavior assertion that running selected `first-tool` prints its expected distinct output.
  - [x] 2.5 GREEN: Fix fixture or wrapper behavior minimally so the selected command runs successfully.
  - [x] 2.6 VERIFY: Run targeted build checks for single-script and multi-script script apps.

- [x] 3.0 Add public API validation for script mode
  - [x] 3.1 RED: Add one negative eval test for using `script` with command mode.
  - [x] 3.2 GREEN: In command mode, reject `script != null` with `errors.fail "app" "pass `script` only with package mode"` before existing command validation continues.
  - [x] 3.3 RED: Add one negative eval test for invalid `script` type or empty string.
  - [x] 3.4 GREEN: Validate `script` is a non-empty string before using it in package script mode.
  - [x] 3.5 RED: Add one negative eval test for `script = "nested/tool"`.
  - [x] 3.6 GREEN: Reject slash-containing `script` values.
  - [x] 3.7 RED: Add one negative eval test proving any `name` value with `script` fails.
  - [x] 3.8 GREEN: Reject `name != null` in script mode with an error explaining output binary name is `script`.
  - [x] 3.9 RED: Add one negative eval test for invalid `pname` in script mode (`""`, non-string, or slash-containing value; add cases incrementally if harness style supports multiple assertions).
  - [x] 3.10 GREEN: Validate `pname`, when provided in script mode, is a non-empty string without `/`.
  - [x] 3.11 VERIFY: Run `test/negative.nix` check and confirm existing negative cases still pass.

- [x] 4.0 Preserve metadata behavior and missing-script diagnostics
  - [x] 4.1 RED: Add a behavior check for `scope.app { package = "smiley-plot"; script = "smiley-plot"; pname = "custom-smiley-plot"; }` that proves `$out/bin/smiley-plot` exists and `$out/bin/custom-smiley-plot` does not.
  - [x] 4.2 GREEN: Ensure script-mode `appName = script` and `appPname = if pname != null then pname else script`.
  - [x] 4.3 RED: Add a build-time missing-script check if existing check infrastructure supports expected-failure builds; otherwise document and manually verify `script = "missing-script"` fails with the specified message.
  - [x] 4.4 GREEN: Add build-time executable check for `${appVenv}/bin/${script}` and print `uvloom.app: script `<script>` not found in venv for package `<packageName>`` before exiting non-zero.
  - [x] 4.5 REFACTOR: Preserve `version`, `meta`, and `passthru` where feasible without making tests implementation-coupled.
  - [x] 4.6 VERIFY: Run targeted checks for script mode, `pname` metadata behavior, and existing package/command apps.

- [x] 5.0 Document script selection across user-facing docs
  - [x] 5.1 RED: If docs checks validate examples or generated docs, add/update a minimal docs expectation that fails until `script` docs exist; otherwise treat doc updates as review-only and continue.
  - [x] 5.2 GREEN: Update `docs/reference.md` package-mode arguments and validation rules: `script` selects `${venv}/bin/${script}`, output binary is always `script`, `name` is rejected, `pname` is metadata only.
  - [x] 5.3 GREEN: Update `docs/how-to.md` with “Build one app for one console script” using a package with multiple scripts and no rename option.
  - [x] 5.4 GREEN: Update `README.md` with a concise `script` example.
  - [x] 5.5 GREEN: Update `docs/intro.md`, `docs/tutorial.md`, `docs/index.md`, and `docs/explanation.md` only where they summarize or explain `scope.app` behavior.
  - [x] 5.6 VERIFY: Run docs checks or formatting checks available in this repo.

- [x] 6.0 Final integration and cleanup
  - [x] 6.1 VERIFY: Run formatter if project provides one.
  - [x] 6.2 VERIFY: Run targeted checks for eval, builds, negative tests, and docs.
  - [x] 6.3 VERIFY: Run full `nix flake check` or closest repo-supported CI command.
  - [x] 6.4 REFACTOR: Clean up naming, duplicated Nix expressions, and fixture code while keeping all checks green.
  - [x] 6.5 UPDATE: Mark completed tasks in this plan and add any implementation notes worth preserving.

## Notes

- Script mode intentionally does not support binary renaming. `$out/bin` name must equal `script`.
- `name` is rejected in script mode to avoid confusing it with a supported rename API.
- `pname` remains derivation metadata only in script mode.
- `script` selects an executable basename from venv `bin`; uvloom should not parse `[project.scripts]`.
- Prefer behavior checks through `scope.app` outputs over tests coupled to internal implementation details.
- Docs updated for script mode across README/reference/how-to/intro/tutorial/index/explanation. `nix build .#docs -L` passes.
- Missing-script case validated manually with impure expression build:
  `nix build -L --impure --expr 'let flake = builtins.getFlake (toString ./.); system = builtins.currentSystem; pkgs = import flake.inputs.nixpkgs { inherit system; }; uvloom = { lib = flake.outputs.lib; }; project = uvloom.lib.project.load { root = ./test/fixtures/smiley-plot; }; scope = project.forPython { inherit pkgs; interpreter = pkgs.python312; }; in scope.app { package = "smiley-plot"; script = "missing-script"; }'`
  and confirmed error ``uvloom.app: script `missing-script` not found in venv for package `smiley-plot` ``.
- Reviewer caught unsafe shell target path construction; fixed by assigning `target_name` with `lib.escapeShellArg` before `ln -s "$source_script" "$out/bin/$target_name"`.
- Added explicit-venv script-mode coverage and list-valued `script` negative coverage after review.
- Final verification: `nix fmt`, targeted `nix build -L` for eval/negative/script/docs checks, and `nix flake check -L` all passed.
