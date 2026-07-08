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
  tmp="$(mktemp cli/src/uvloom_cli/data/pins.json.XXXXXX)"; \
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
