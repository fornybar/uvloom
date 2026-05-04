set shell := ["bash", "-eu", "-o", "pipefail", "-c"]

# List available recipes
_default:
  @just --list

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
