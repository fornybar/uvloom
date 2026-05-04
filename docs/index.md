# Documentation

uvloom is a small helper layer for `uv2nix`. Pick the page that matches what you need now.

| Need | Read |
| --- | --- |
| First working project | [Tutorial](tutorial.md) |
| Copy a task recipe | [How-to guides](how-to.md) |
| Check function names and arguments | [Reference](reference.md) |
| Understand project/scope/editable mode | [Explanation](explanation.md) |
| Read one complete guide | [Full guide](intro.md) |

## Short path

1. Start with [Tutorial](tutorial.md).
2. Copy recipes from [How-to guides](how-to.md).
3. Use [Reference](reference.md) when you need exact API shape.

## Main idea

Most projects use this pattern:

```nix
project = uvloom.lib.loadProject { root = ./.; };
scope = project.forPython { inherit pkgs; interpreter = pkgs.python312; };
```

Then expose helpers through your normal flake outputs:

```nix
packages.${system}.default = scope.mkApplication { package = "my-project"; };
checks.${system}.pytest = scope.mkPytestCheck { package = "my-project"; };
```
