# uvloom CLI

The `uvloom` command runs uv projects on NixOS without writing any Nix. You keep uv's workflow — `lock`, `add`, `sync`, `run` — but the environment is built by Nix, so native-code wheels work and the result is reproducible.

This is the **CLI path**, intended for onboarding and the local development loop. Use the [library path](intro.md) for a flake you own when the project needs declared CI or deployment packages, checks, dev shells, overlays, or custom Nix composition.

## Install

```sh
nix profile install github:fornybar/uvloom#uvloom-cli
```

Or try it without installing:

```sh
nix shell github:fornybar/uvloom#uvloom-cli
```

The CLI bundles its own `uv`; it only needs `nix` on your `PATH`.

The flake publishes the CLI for x86_64 and aarch64 Linux and macOS. CI runs
full end-to-end coverage on x86_64 Linux and native build, unit, and fast
end-to-end coverage on aarch64 macOS. Other published systems receive the
same Nix package definition but do not have native CI coverage.

## First project

Create a project (or start in any existing uv project):

```sh
uvloom init my-project
cd my-project
uvloom add requests
```

Build the environment and run something in it:

```sh
uvloom sync
uvloom run -- python -c 'import requests; print(requests.__version__)'
```

`sync` builds a virtual environment with Nix and links it at `.venv`. Environment defaults follow workspace-root `[tool.uv] default-groups`: absent means `dev`, `[]` means none, and `"all"` means every dependency group. Use dependency selectors to add or choose another set. `run` executes a command inside it, rebuilding first if `pyproject.toml` or `uv.lock` changed. When nothing changed, `run` starts your command immediately — no Nix involved.

That's the whole loop:

```sh
uvloom add numpy      # edit dependencies with uv
uvloom sync           # rebuild the environment
uvloom run my-cmd     # run inside it
```

## Commands

Familiar uv commands delegate project and lockfile mutations to the bundled, pinned `uv`, but they never sync or mutate the Nix-built environment — run `uvloom sync` afterwards:

```
uvloom lock | add | remove | tree | export | init | build | version
```

After a successful `add`, `remove`, or a mutating `version` (a positional version or `--bump`), uvloom prints a reminder that the environment is out of date — run `uvloom sync`.

Pass-through commands preserve uv's project selectors. `--directory <dir>`
(or `UV_WORKING_DIR`) changes discovery base; `--project <dir>` (or
`UV_PROJECT`) selects project to read and invalidate. Paths are resolved as uv
does: a relative `--project` is relative to `--directory`. `lock --script
file.py` targets only script lock and never touches a project `.venv` marker.
`build [SRC]` is true pass-through and never invalidates `.venv-uvloom.json`:
when `SRC` names a local project directory, or `--project`/`UV_PROJECT` selects
a project with no positional `SRC`, uvloom may set `UV_PYTHON` from that
project's lock; archive, file, missing, or outside-project sources pass through
without binding the caller project's interpreter.
Environment-building commands (`sync`, `run`, `venv`, `check`) and `flakify`
use uvloom's current-directory project discovery; `UV_PROJECT` and
`UV_WORKING_DIR` only apply to pass-through uv commands.

The rest manage the Nix-built environment:

| Command | What it does |
| --- | --- |
| `uvloom sync` | Build `.venv`. Defaults follow `[tool.uv] default-groups` at workspace root. `--group <g>`/`--group=<g>` adds groups on top of defaults; `--extra <e>`/`--extra=<e>` adds extras; `--all-groups` selects every dependency group but not extras. `--include <p>` (repeatable) widens filtered source; `--no-filter-source` copies whole project source. Also `--no-editable`, `--no-hammer`, `--force`, `-v`/`--verbose`, and `-q`/`--quiet` (suppress the `synced .venv -> ...` message). |
| `uvloom run [--] <cmd>` | Run `<cmd>` inside environment, rebuilding first if needed. `--group <g>`/`--group=<g>` adds groups on top of defaults; `--extra <e>`/`--extra=<e>` adds extras; `--all-groups` selects every dependency group but not extras. Explicit dependency or source selection (`--include`, `--no-filter-source`) rebuilds and becomes sticky for later plain runs, like `sync`. Also accepts `--no-editable`, `--no-hammer`, `--force`, `-v`/`--verbose`, and `-q`/`--quiet`. |
| `uvloom venv` | Build environment and print store path. Takes same flags as `sync` (`--group`, `--extra`, `--all-groups`, `--no-editable`, `--include`, `--no-filter-source`, `--no-hammer`, `--force`, `-v`/`--verbose`, `-q`/`--quiet`). |
| `uvloom check` | Run project's pytest suite as Nix build, on filtered source plus test paths (`tests/` by default). `--paths <p>` (repeatable) selects test paths to copy and run instead of `tests/`; `--include <p>` (repeatable) copies extra directories into filtered source without running pytest on them; `--no-filter-source` copies whole project source; `--group <g>` (repeatable) selects dependency groups for test environment instead of default `test` group. Also accepts `--no-hammer` and `-v`/`--verbose`. Pytest flags go after `--`. |
| `uvloom flakify` | Write a `flake.nix` for the project (`--no-hammer` to omit the bundled overrides). Creates `uv.lock` first when missing. See [Graduating to a flake](#graduating-to-a-flake). |

If `uv.lock` is missing, `sync`, `run`, `venv`, `check`, and `flakify` create it first (the equivalent of `uv lock`), just like uv would. `flakify` first refuses an existing `flake.nix`, so this bootstrap never mutates a project it will not write.

From a nested project, uvloom uses an ancestor only when that project matches an ancestor `[tool.uv.workspace].members` pattern and no valid `exclude` pattern. An ancestor `uv.lock` alone does not capture an unrelated nested project. Workspace member and exclude patterns that are absolute or escape through `..` are ignored for this discovery decision; fix them in `pyproject.toml` before invoking uv directly.

`check` installs the `test` dependency group by default. If `pyproject.toml` does not define it, add one — `[dependency-groups] test = ["pytest"]` — or pass `--group <existing-group>` to select a group you do have.

Environment builds and checks use filtered store source by default, not working tree. For `[tool.uv] package = false` projects that copy includes top-level `*.py` files and `src/` automatically, but other directories your code imports (say `utils/` or `assets/`) may be dropped; pass `uvloom sync --include utils` or `uvloom run --include utils -- ...` to copy them in. Those source flags are sticky for later plain `run`. Use `--no-filter-source` for custom backend discovery, symlinks, generated files, or unusual layouts. `check --include` widens check source only; `--paths` also makes pytest collect those paths. `--include` and `--no-filter-source` cannot be combined. Note that copying alone does not make imports resolve: a non-package project is never installed into venv, so pytest needs project root on `sys.path` — exactly as with local `uv run pytest`. Add standard pytest configuration to `pyproject.toml`:

```toml
[tool.pytest.ini_options]
pythonpath = ["."]
```

A few uv commands are not wrapped because they mutate environments or interpreters imperatively, which store-built environments rule out: `pip`, `tool`/`uvx`, and `python`. `publish` and `self` don't involve Nix — call `uv` directly. Trying any of these prints a one-line explanation.

When an underlying uv subprocess — including the automatic `uv lock` and `uv lock --script` — is interrupted by a signal, uvloom exits with the conventional shell status: 128 plus the signal number, so Ctrl-C reports 130.

## The environment

`.venv` is a symlink into the Nix store, not a directory. It doubles as a garbage-collector root: the environment survives `nix-collect-garbage`, and old environments are cleaned up naturally after a new sync replaces the link. A marker file, `.venv-uvloom.json`, records what the environment was built from, and `.venv-uvloom.lock` serializes concurrent builds; all three belong in `.gitignore`. `check` also creates `.venv-uvloom-check.lock`; ignore it. PEP 723 scripts create `<script>.py.uvloom.json` markers beside scripts; ignore `*.py.uvloom.json` too.

If `.venv` is a real directory — say, plain `uv sync` created one — uvloom refuses to touch it. Remove it, or let uvloom replace it:

```sh
uvloom sync --force   # also forces a rebuild even when the cache is current
```

### Editing code

Local packages are installed editable by default. Warm edits to imported source files are picked up on the next `uvloom run` with no rebuild. Changes to installation metadata in `pyproject.toml` — including console-script entry points or package discovery — require an explicit `uvloom sync` so the editable install metadata is regenerated; dependency changes require a sync as well.

To build a self-contained environment from store copies of your source instead (what a deployment would see):

```sh
uvloom sync --no-editable
```

## Picking a Python

uvloom chooses the interpreter from a version request in `UV_PYTHON`, then a `.python-version` file if present, else `requires-python` in `pyproject.toml` — matching uv's precedence. nixpkgs carries one patch level per minor, so an exact request like `3.12.4` becomes `python312` with a warning. Set `UV_PYTHON` to a version such as `3.12`, not an executable path. Reuse of an already resolved interpreter by nested uvloom processes is an internal implementation detail, not a supported selection interface.

```sh
echo 3.12 > .python-version
```

## When a build fails

Some packages need system libraries or build tools that their sdists don't declare. A pinned collection of community overrides ([uv2nix_hammer_overrides](https://github.com/TyberiusPrime/uv2nix_hammer_overrides)) is applied by default and fixes many of these before you ever see them.

When a build still fails, uvloom reports the failing package and version, the tail of its build log, and — for common failure classes like a missing `pkg-config` or a missing shared library — a ready-to-paste fix:

```
uvloom: build of pycairo 1.26.0 failed
...
detected: 'pkg-config' is missing at build time.
paste into uv.nix at the project root (create the file if missing):

final: prev: {
  "pycairo" = prev."pycairo".overrideAttrs (old: {
    nativeBuildInputs = (old.nativeBuildInputs or [ ]) ++ [ final.pkgs.pkg-config ];
  });
}
```

`uv.nix` is an overlay on the Python package set, applied after the bundled overrides so your fixes always win. `final.pkgs` is nixpkgs. Save the file and re-run `uvloom sync` — it's picked up automatically.

Pass `-v` to stream the raw Nix build output instead.

## Configuration

uvloom uses uv project metadata where its Nix model can represent it. It does
not implement every uv setting:

| To get | Do |
| --- | --- |
| A specific Python | `UV_PYTHON` with a `MAJOR.MINOR[.PATCH]` version, then `.python-version`, then `requires-python`. Executable paths are not a supported request. |
| Build from sdists | `UV_NO_BINARY`, then top-level `no-binary` in project `uv.toml`, then `[tool.uv] no-binary = true` in `pyproject.toml`. `UV_NO_BINARY` accepts uv 0.11.8 boolean spellings: `1`/`0`, `true`/`false`, `yes`/`no`, `on`/`off`, or `t`/`f`/`y`/`n` (case-insensitive). Per-package `no-binary-package` and `UV_NO_BINARY_PACKAGE` are rejected by environment builds because one Nix environment cannot represent package-specific source choices. `flakify` ignores both inherited source-preference variables, even malformed values, and warns: generated flakes use only project configuration. |
| Default dependency groups | `[tool.uv] default-groups = ["dev", "docs"]`, `[]`, or `"all"` in workspace-root `pyproject.toml`. Applies to `sync`, `run`, and `venv`; absent means `["dev"]`. |
| Non-editable install | `uvloom sync --no-editable`, same flag as `uv sync`. |
| No bundled overrides | `uvloom sync --no-hammer`. |

## Hermetic and authenticated tests

`uvloom check` is the hermetic path: pytest runs in a Nix build sandbox against the filtered store copy, so tests must not depend on runner credentials or external services.

For authenticated integration tests, build the selected venv first and execute pytest outside the Nix build, where the CI runner can supply credentials:

```sh
venv=$(uvloom venv --group integration)
SERVICE_TOKEN="$SERVICE_TOKEN" "$venv/bin/pytest" tests/integration
```

This still uses the Nix-built environment, but the test execution is intentionally non-hermetic. Keep credentials in the runner's secret store; never put them in Nix evaluation, derivation arguments, or the store.

## Scripts

`uvloom run script.py` runs a single-file script with [PEP 723 inline metadata](https://peps.python.org/pep-0723/):

```python
# /// script
# requires-python = ">=3.12"
# dependencies = ["requests"]
# ///
import requests
```

The script gets its own lock (`uv lock --script`, created automatically) and its own environment, separate from the project's `.venv`. The project-environment flags — `--group`, `--extra`, `--all-groups`, `--no-editable`, `--force` — are rejected for script targets; only `--no-hammer`, `-v`, and `-q`/`--quiet` apply.

## Graduating to a flake

When you need CI outputs, custom packages, or full control of the Nix side:

```sh
uvloom flakify
```

This writes a standard uvloom `flake.nix` wired to the same interpreter, source filtering, overrides, and pins the CLI was using — including your `uv.nix`. nixpkgs and the override collection are pinned to the CLI's vendored revisions, but the `uvloom` input itself tracks the default branch until you pin it. Nothing else changes: `pyproject.toml` and `uv.lock` carry over as-is, and from there the [library documentation](index.md) applies. It refuses to overwrite an existing `flake.nix`. The generated flake pins the interpreter from `.python-version` and the source preference from `pyproject.toml` only — a conflicting `UV_PYTHON` or `UV_NO_BINARY` in the environment is warned about and ignored.

Generated flakes use filtered source by default. If your backend needs package data, generated sources, tests, or other committed files uvloom cannot infer, edit `flake.nix` and add them with `extraSourcePaths = [ "path" ];`. For complex backend discovery, symlinks, generated files, or broad repo-as-source assumptions, edit the generated load block to `filterSource = false;`.

`flakify` translates uvloom's project environment; it does not reproduce bespoke CI pipelines, Docker images, NixOS modules, or operational shell tooling. Compose or migrate those separately in the generated flake and its surrounding repository.

Flakes only see git-tracked files, so `flakify` prints an explicit `git add` list covering everything the flake build reads — `flake.nix`, `pyproject.toml`, `uv.lock`, plus `uv.nix`, `.python-version`, the declared readme, and local source directories when present. Follow it before building:

```sh
git add flake.nix pyproject.toml uv.lock src   # flakify prints your project's exact list
nix build
```
