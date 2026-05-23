# uvloom documentation

uvloom turns a `uv`-locked Python project into Nix outputs with less boilerplate. You still own the flake: choose nixpkgs, Python, dependency groups, overlays, packages, checks, shells, and exports.

## Quick path

```sh
mkdir my-project
cd my-project
nix flake init -t github:fornybar/uvloom#simple
uv lock
nix build
```

Then open `flake.nix`. Most uvloom flakes use this shape:

```nix
project = uvloom.lib.project.load { root = ./.; };

scope = project.forPython {
  inherit pkgs;
  interpreter = pkgs.python312;
};
```

Use scope helpers in normal flake outputs:

```nix
packages.${system}.default = scope.app { package = "my-project"; };
checks.${system}.pytest = scope.check.pytest { package = "my-project"; };
```

## Mental model

1. `uv.lock` records Python dependencies.
2. `project.load` reads `pyproject.toml` and `uv.lock` once.
3. `forPython` binds that project to one nixpkgs package set and interpreter.
4. `scope.*` helpers build packages, environments, checks, and exports.
