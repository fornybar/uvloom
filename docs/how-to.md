# How-to guides

Recipes for existing uvloom projects.

## Add uvloom to an existing flake

Add input:

```nix
inputs = {
  nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
  uvloom.url = "github:fornybar/uvloom";
  uvloom.inputs.nixpkgs.follows = "nixpkgs";
};
```

Load project and create scope:

```nix
let
  system = "x86_64-linux";
  pkgs = nixpkgs.legacyPackages.${system};
  project = uvloom.lib.loadProject { root = ./.; };
  scope = project.forPython {
    inherit pkgs;
    interpreter = pkgs.python312;
  };
in
{
  packages.${system}.default = scope.mkApplication { package = "my-project"; };
}
```

## Build an application wrapper

Use this when `pyproject.toml` defines console scripts.

```nix
packages.${system}.default = scope.mkApplication {
  package = "my-project";
};
```

Single-package workspace can omit `package`:

```nix
packages.${system}.default = scope.mkApplication { };
```

## Build a virtual environment

```nix
packages.${system}.env = scope.mkVenv {
  name = "my-project-env";
};
```

Include every dependency group:

```nix
packages.${system}.dev = scope.mkVenv {
  name = "my-project-dev-env";
  dependencies = project.workspace.deps.all;
};
```

## Run pytest in `nix flake check`

```nix
checks.${system}.pytest = scope.mkPytestCheck {
  package = "my-project";
  groups = [ "test" ];
  paths = [ "tests" ];
  pytestFlags = [ "-q" ];
};
```

Run:

```sh
nix flake check
```

## Create editable development environment

Use editable mode when imports should see working-tree source without rebuilding the package.

Enable editable mode:

```nix
scope = project.forPython {
  inherit pkgs;
  interpreter = pkgs.python312;
  editable = {
    root = "$PWD";
    members = [ "my-project" ];
  };
};
```

Expose editable venv in a dev shell:

```nix
devShells.${system}.default = pkgs.mkShell {
  packages = [
    (scope.mkEditableVenv { name = "my-project-dev-env"; })
    pkgs.uv
  ];
};
```

Enter shell:

```sh
nix develop
```

For multi-package workspaces, list all editable local packages:

```nix
editable = {
  root = "$PWD";
  members = [ "my-app" "my-library" ];
};
```

## Add a package override

Use pyproject.nix package-set overlays when a Python package needs extra inputs or attribute changes. These are uv2nix-style `overrideScope` overlays, not nixpkgs flake overlays.

```nix
scope = project.forPython {
  inherit pkgs;
  interpreter = pkgs.python312;
  overlays = [
    (final: prev: {
      my-project = prev.my-project.overrideAttrs (old: {
        nativeBuildInputs = (old.nativeBuildInputs or [ ]) ++ [ pkgs.pkg-config ];
      });
    })
  ];
};
```

## Export packages to nixpkgs-style Python sets

Use this when consumers should use `python3.withPackages` or `python3Packages.my-project`.

```nix
let
  project = uvloom.lib.loadProject { root = ./.; };
in
{
  overlays.default = project.nixpkgs.overlay {
    packages = [ "my-project" ];
  };
}
```

If export-time customizations need nixpkgs `final`, write the nixpkgs overlay explicitly and call `project.nixpkgs.pythonPackagesExtension` inside it:

```nix
overlays.default = final: prev: {
  pythonPackagesExtensions = (prev.pythonPackagesExtensions or [ ]) ++ [
    (project.nixpkgs.pythonPackagesExtension {
      packages = [ "my-project" ];
      overlays = [
        (config.patches.my-project { pkgs = final; })
      ];
    })
  ];
};
```

If a customization must run after uvloom exports packages to nixpkgs style, append another Python package-set extension:

```nix
overlays.default = final: prev: {
  pythonPackagesExtensions = (prev.pythonPackagesExtensions or [ ]) ++ [
    (project.nixpkgs.pythonPackagesExtension {
      packages = [ "my-project" ];
    })
    (python-final: python-prev: {
      my-project = python-prev.my-project.overridePythonAttrs (old: {
        propagatedBuildInputs = (old.propagatedBuildInputs or [ ]) ++ [
          python-final.numpy
        ];
      });
    })
  ];
};
```

Consumer:

```nix
pkgs = import nixpkgs {
  inherit system;
  overlays = [ my-project.overlays.default ];
};

devShells.default = pkgs.mkShell {
  packages = [
    (pkgs.python3.withPackages (ps: [ ps.my-project ]))
  ];
};
```

## Use lower-level uv2nix APIs

Supported escape hatches:

- `project.workspace`: upstream `uv2nix` workspace.
- `scope.pythonSet`: final pyproject.nix package set.
- `scope.editablePythonSet`: editable package set when editable mode is enabled.

If your flake mostly needs custom `uv2nix` composition, use `uv2nix` and `pyproject-nix` directly.
