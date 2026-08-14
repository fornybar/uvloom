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

# Install the local commitlint hook
hooks-install:
  git config core.hooksPath .githooks
