set shell := ["bash", "-eu", "-o", "pipefail", "-c"]

# List available recipes
_default:
  @just --list

# Update flake.lock files in all examples
# Usage: just examples-update-locks
examples-update-locks:
  find examples -mindepth 2 -maxdepth 2 -name flake.nix -print0 \
    | sort -z \
    | while IFS= read -r -d '' flake; do \
      dir="$(dirname "$flake")"; \
      echo "Updating $dir/flake.lock"; \
      nix flake update --flake "./$dir"; \
    done

# Build generated documentation into ./result-docs
# Usage: just docs-build
docs-build:
  nix build .#docs -o result-docs
  @echo "Docs built: file://$PWD/result-docs/index.html"

# Serve generated documentation locally
# Usage: just docs-preview [port]
docs-preview port="8000": docs-build
  @echo "Serving docs at http://127.0.0.1:{{port}}/"
  @echo "Press Ctrl-C to stop."
  cd result-docs && python -m http.server {{port}} --bind 127.0.0.1

# Remove local docs symlink
docs-clean:
  rm -f result-docs

# Regenerate cli/src/uvloom_cli/data/pins.json: copy the four flake.lock-tracked
# pins from flake.lock and re-prefetch flake-compat + uv2nix_hammer_overrides
# Usage: just pins-update
pins-update:
  tmp="$(mktemp)"; \
  { \
    for name in nixpkgs pyproject-nix uv2nix pyproject-build-systems; do \
      jq --arg n "$name" '{($n): (.nodes[$n].locked | {owner, repo, rev, narHash})}' flake.lock; \
    done; \
    for flake in edolstra/flake-compat TyberiusPrime/uv2nix_hammer_overrides; do \
      nix flake prefetch "github:$flake" --json \
        | jq '{(.locked.repo): {owner: .locked.owner, repo: .locked.repo, rev: .locked.rev, narHash: .hash}}'; \
    done; \
  } | jq -s 'add' > "$tmp" \
    && mv "$tmp" cli/src/uvloom_cli/data/pins.json \
    || { rm -f "$tmp"; exit 1; }
  @echo "Updated cli/src/uvloom_cli/data/pins.json"

# Run the CLI unit test suite exactly as CI does
# Usage: just cli-test
cli-test:
  nix shell --inputs-from . nixpkgs#uv nixpkgs#python312 -c uv run --locked --directory cli --group dev pytest tests/unit -q

# Run the CLI end-to-end test suite exactly as CI does: pre-build the CLI
# and point the suite at it via UVLOOM_E2E_BIN
# Usage: just cli-e2e
cli-e2e:
  nix build .#uvloom-cli -o result-cli
  UVLOOM_E2E_BIN="$PWD/result-cli/bin/uvloom" nix shell --inputs-from . nixpkgs#uv nixpkgs#python312 -c uv run --locked --directory cli --group dev pytest tests/e2e -q

# Run only the fast E2E tests (deselects the `slow` marker: cold Nix builds,
# full matrix) — same invocation shape as cli-e2e
# Usage: just cli-e2e-fast
cli-e2e-fast:
  nix build .#uvloom-cli -o result-cli
  UVLOOM_E2E_BIN="$PWD/result-cli/bin/uvloom" nix shell --inputs-from . nixpkgs#uv nixpkgs#python312 -c uv run --locked --directory cli --group dev pytest tests/e2e -q -m 'not slow'
