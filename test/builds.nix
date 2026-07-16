{
  pkgs,
  uvloom,
}:

let
  project = uvloom.lib.project.load {
    root = ./fixtures/smiley-plot;
  };

  multiScriptProject = uvloom.lib.project.load {
    root = ./fixtures/multi-script-app;
  };

  scope = project.forPython {
    inherit pkgs;
    interpreter = pkgs.python312;
  };

  scopeWithAllDependencies = project.forPython {
    inherit pkgs;
    interpreter = pkgs.python312;
    dependencies = project.workspace.deps.all;
  };

  multiScriptScope = multiScriptProject.forPython {
    inherit pkgs;
    interpreter = pkgs.python312;
  };

  pkgsWithOverlay = pkgs.extend (
    project.nixpkgs.overlay {
      packages = [ "smiley-plot" ];
    }
  );

  script = uvloom.lib.inline.load {
    path = ./fixtures/scripts/example.py;
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

  sdistScript = uvloom.lib.inline.load {
    path = ./fixtures/scripts/example.py;
    config = {
      no-binary = true;
      extra-build-dependencies.tqdm = [ setuptoolsRequirement ];
    };
  };

  sdistScriptScope = sdistScript.forPython {
    inherit pkgs;
    interpreter = pkgs.python312;
  };

  nonPackageProject = uvloom.lib.project.load {
    root = ../examples/non_package_app;
  };

  nonPackageScope = nonPackageProject.forPython {
    inherit pkgs;
    interpreter = pkgs.python312;
  };

  virtualFlatAppProject = uvloom.lib.project.load {
    root = ./fixtures/virtual-flat-app;
  };

  virtualFlatAppScope = virtualFlatAppProject.forPython {
    inherit pkgs;
    interpreter = pkgs.python312;
  };

  virtualFlatAppVenv = virtualFlatAppScope.venv {
    name = "virtual-flat-app-env";
  };

  virtualFlatAppDevVenv = virtualFlatAppScope.venv {
    name = "virtual-flat-app-dev-env";
    dependencies.virtual-flat-app = [ "dev" ];
  };

  nonPackageApplication = nonPackageScope.app {
    name = "non-package-app";
    command = [
      "python"
      ../examples/non_package_app/app.py
    ];
    pythonPath = [ ../examples/non_package_app ];
  };

  nonPackageOverrideCwdApplication = nonPackageScope.app {
    name = "non-package-app-utils-cwd";
    command = [
      "python"
      "-c"
      "from pathlib import Path; print(Path.cwd().name)"
    ];
    workingDirectory = ../examples/non_package_app/utils;
  };

  explicitScriptVenv = scope.venv {
    name = "smiley-plot-script-env";
  };

  scriptApplication = scope.app {
    package = "smiley-plot";
    script = "smiley-plot";
  };

  scriptApplicationWithVenv = scope.app {
    package = "smiley-plot";
    script = "smiley-plot";
    venv = explicitScriptVenv;
  };

  scriptPnameApplication = scope.app {
    package = "smiley-plot";
    script = "smiley-plot";
    pname = "custom-smiley-plot";
  };

  multiScriptApplication = multiScriptScope.app {
    package = "multi-script-app";
    script = "first-tool";
  };
in
{
  venv = scope.venv {
    name = "smiley-plot-env";
  };

  venv-inherits-scope-dependencies = pkgs.runCommand "venv-inherits-scope-dependencies" { } ''
    ${scopeWithAllDependencies.venv { name = "smiley-plot-all-env"; }}/bin/python -c "import pytest"
    touch $out
  '';

  application = scope.app {
    package = "smiley-plot";
  };

  application-default = scope.app { };

  application-command = scope.app {
    name = "smiley-command";
    command = [
      "python"
      "-c"
      "print('ok')"
    ];
  };

  application-script = scriptApplication;

  application-script-bin = pkgs.runCommand "application-script-bin" { } ''
    test -x ${scriptApplication}/bin/smiley-plot
    touch $out
  '';

  application-script-with-venv = scriptApplicationWithVenv;

  application-script-with-venv-bin = pkgs.runCommand "application-script-with-venv-bin" { } ''
    test -x ${scriptApplicationWithVenv}/bin/smiley-plot
    touch $out
  '';

  application-script-pname = scriptPnameApplication;

  application-script-pname-metadata = pkgs.runCommand "application-script-pname-metadata" { } ''
    test -x ${scriptPnameApplication}/bin/smiley-plot
    test ! -e ${scriptPnameApplication}/bin/custom-smiley-plot
    touch $out
  '';

  application-multi-script = multiScriptApplication;

  application-multi-script-selected-only =
    pkgs.runCommand "application-multi-script-selected-only" { }
      ''
        test -x ${multiScriptApplication}/bin/first-tool
        test ! -e ${multiScriptApplication}/bin/second-tool
        touch $out
      '';

  application-multi-script-runs = pkgs.runCommand "application-multi-script-runs" { } ''
    output="$(${multiScriptApplication}/bin/first-tool)"
    echo "$output"
    echo "$output" | grep -x "first-tool output"
    touch $out
  '';

  pytest = scope.check.pytest {
    package = "smiley-plot";
  };

  pytest-default = scope.check.pytest { };

  nixpkgs-package = scope.nixpkgs.package {
    package = "smiley-plot";
  };

  nixpkgs-with-packages = pkgsWithOverlay.python312.withPackages (ps: [
    ps."smiley-plot"
  ]);

  script-application = scriptScope.app { };

  script-editable-application = scriptScope.app.editable {
    path = "test/fixtures/scripts/example.py";
  };

  script-sdist-application = sdistScriptScope.app { };

  non-package-application = nonPackageApplication;

  virtual-flat-app-venv = virtualFlatAppVenv;

  virtual-flat-app-venv-has-dependency =
    pkgs.runCommand "virtual-flat-app-venv-has-dependency"
      {
        nativeBuildInputs = [ virtualFlatAppVenv ];
      }
      ''
        python -c "import colorama; print(colorama.__version__)" | grep '^0.4.6$'
        ! python -c "import importlib.metadata; importlib.metadata.version('virtual-flat-app')"
        touch $out
      '';

  virtual-flat-app-venv-has-dependency-group =
    pkgs.runCommand "virtual-flat-app-venv-has-dependency-group"
      {
        nativeBuildInputs = [ virtualFlatAppDevVenv ];
      }
      ''
        python -c "import colorama, typing_extensions"
        touch $out
      '';

  non-package-run =
    pkgs.runCommand "non-package-run"
      {
        nativeBuildInputs = [ nonPackageApplication ];
      }
      ''
        output="$(${pkgs.lib.getExe nonPackageApplication})"
        echo "$output"
        echo "$output" | grep -x "ok"
        echo "$output" | grep -E "^cwd=.*non_package_app$"
        touch $out
      '';

  non-package-working-directory-override =
    pkgs.runCommand "non-package-working-directory-override"
      {
        nativeBuildInputs = [ nonPackageOverrideCwdApplication ];
      }
      ''
        output="$(${pkgs.lib.getExe nonPackageOverrideCwdApplication})"
        echo "$output"
        echo "$output" | grep -E ".*utils$"
        touch $out
      '';
}
