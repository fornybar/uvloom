{
  pkgs,
  uvloom,
}:

let
  project = uvloom.lib.loadProject {
    root = ./fixtures/smiley-plot;
  };

  scope = project.forPython {
    inherit pkgs;
    interpreter = pkgs.python312;
  };

  pkgsWithOverlay = pkgs.extend (
    project.nixpkgs.overlay {
      packages = [ "smiley-plot" ];
    }
  );

  script = uvloom.lib.loadScript {
    script = ./fixtures/scripts/example.py;
  };

  scriptScope = script.forPython {
    inherit pkgs;
    interpreter = pkgs.python312;
  };

  setuptoolsRequirement = {
    requirement = {
      conditions = [ ];
      extras = [ ];
      markers = null;
      name = "setuptools";
      url = null;
    };
  };

  sdistScript = uvloom.lib.loadScript {
    script = ./fixtures/scripts/example.py;
    config = {
      no-binary = true;
      extra-build-dependencies.tqdm = [ setuptoolsRequirement ];
    };
  };

  sdistScriptScope = sdistScript.forPython {
    inherit pkgs;
    interpreter = pkgs.python312;
  };
in
{
  venv = scope.mkVenv {
    name = "smiley-plot-env";
  };

  application = scope.mkApplication {
    package = "smiley-plot";
  };

  application-default = scope.mkApplication { };

  pytest = scope.mkPytestCheck {
    package = "smiley-plot";
  };

  pytest-default = scope.mkPytestCheck { };

  nixpkgs-package = scope.nixpkgs.package {
    package = "smiley-plot";
  };

  nixpkgs-with-packages = pkgsWithOverlay.python312.withPackages (ps: [
    ps."smiley-plot"
  ]);

  script-application = scriptScope.mkApplication { };

  script-sdist-application = sdistScriptScope.mkApplication { };
}
