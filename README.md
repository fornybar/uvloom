# uvloom

[![docs](https://shieldcn.dev/badge/docs-76E691.svg?logo=lu%3ABook&color=124442)](https://fornybar.github.io/uvloom/)

uvloom is a small Nix library for Python projects that use [`uv`](https://docs.astral.sh/uv/) locks. It wraps [`uv2nix`](https://github.com/pyproject-nix/uv2nix) with helpers for common flake outputs: application wrappers, virtual environments, editable development shells, test checks, and nixpkgs-style package exports.

Use uvloom when you want less `uv2nix` boilerplate.

## Quick start

Start from a template:

```sh
mkdir my-project
cd my-project
nix flake init -t github:fornybar/uvloom#simple
uv lock
nix build
```

Core pattern:

```nix
project = uvloom.lib.project.load { root = ./.; };

scope = project.forPython {
  inherit pkgs;
  interpreter = pkgs.python312;
};

packages.${system}.default = scope.app { package = "my-project"; };
checks.${system}.pytest = scope.check.pytest { package = "my-project"; };

# Optional: select one executable from package venv
packages.${system}.my-project-cli = scope.app {
  package = "my-project";
  script = "my-project";
};
```

Non-package uv project (`[tool.uv] package = false`) can use command mode:

```nix
packages.${system}.default = scope.app {
  name = "my-app";
  command = [ "python" ./app.py ];
  pythonPath = [ ./. ];
};
```

Use list command only. Avoid shell string. Prefer narrow `pythonPath` like `./src` when possible to reduce module shadowing.

## Templates

| Template | Use when |
| --- | --- |
| `simple` | You need a minimal application package. |
| `editable` | You want a `nix develop` shell where imports see working-tree source. |
| `pytest` | You want pytest wired into `nix flake check`. |

Initialize one:

```sh
nix flake init -t github:fornybar/uvloom#pytest
```

## Documentation

- [Tutorial](https://fornybar.github.io/uvloom/tutorial.html): first project from a template.
- [How-to guides](https://fornybar.github.io/uvloom/how-to.html): focused recipes.
- [Reference](https://fornybar.github.io/uvloom/reference.html): arguments, defaults, and return values.
- [Explanation](https://fornybar.github.io/uvloom/explanation.html): project/scope model and escape hatches.
- [Templates](https://fornybar.github.io/uvloom/templates.html): bundled starters.
- [API](https://fornybar.github.io/uvloom/api.html): generated `uvloom.lib` API docs.

## License

[MIT](LICENSE)
