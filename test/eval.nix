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

  editableScope = project.forPython {
    inherit pkgs;
    interpreter = pkgs.python312;
    editable = {
      root = "$REPO_ROOT";
      members = [ "smiley-plot" ];
    };
  };

  environScope = project.forPython {
    inherit pkgs;
    interpreter = pkgs.python312;
    environ = {
      platform_release = "5.10.65";
    };
  };

  projectPythonPackagesExtension = project.nixpkgs.pythonPackagesExtension {
    packages = [ "smiley-plot" ];
  };

  pythonWithProjectExtension = pkgs.python312.override {
    self = pythonWithProjectExtension;
    packageOverrides = projectPythonPackagesExtension;
  };

  pkgsWithOverlay = pkgs.extend (
    project.nixpkgs.overlay {
      packages = [ "smiley-plot" ];
    }
  );

  markerSrc = pkgs.runCommand "uvloom-marker-src" { } ''
    mkdir -p $out
    cat > $out/pyproject.toml <<'EOF'
    [project]
    name = "uvloom-marker"
    version = "1.0.0"

    [build-system]
    requires = ["setuptools"]
    build-backend = "setuptools.build_meta"
    EOF
  '';

  customPython = pkgs.python312.override {
    self = customPython;
    packageOverrides = final: prev: {
      uvloom-marker = prev.buildPythonPackage {
        pname = "uvloom-marker";
        version = "1.0.0";
        src = markerSrc;
        pyproject = true;
        build-system = [ final.setuptools ];
      };
    };
  };

  customScope = project.forPython {
    inherit pkgs;
    interpreter = customPython;
  };

  customScopePackage = customScope.nixpkgs.package {
    package = "smiley-plot";
    exportPackages = [ "smiley-plot" ];
  };

  script = uvloom.lib.loadScript {
    script = ./fixtures/scripts/example.py;
  };

  scriptScope = script.forPython {
    inherit pkgs;
    interpreter = pkgs.python312;
  };

  inferredScriptScope = script.forPython {
    inherit pkgs;
  };

  sdistScript = uvloom.lib.loadScript {
    script = ./fixtures/scripts/example.py;
    config.no-binary = true;
  };

  sdistScriptScope = sdistScript.forPython {
    inherit pkgs;
    interpreter = pkgs.python312;
  };

  sdistRenderedScript = sdistScriptScope.renderScript { };

  defaultApplication = scope.mkApplication { };

  customApplication = scope.mkApplication {
    pname = "custom-smiley-plot";
    version = "1.2.3";
  };

  defaultPytestCheck = scope.mkPytestCheck { };

  customPytestCheck = scope.mkPytestCheck {
    name = "custom-smiley-pytest";
  };

  scripts = uvloom.lib.loadScripts {
    root = ./fixtures/scripts;
  };
in
assert uvloom.lib ? loadScript;
assert uvloom.lib ? loadScripts;
assert project ? workspace;
assert project.workspace ? deps;
assert project.workspace ? mkPyprojectOverlay;
assert project ? forPython;
assert project ? nixpkgs;
assert project.nixpkgs ? pythonPackagesExtension;
assert project.nixpkgs ? overlay;
assert scope ? interpreter;
assert pkgs.lib.getExe scope.interpreter == pkgs.python312.interpreter;
assert scope ? pythonSet;
assert scope ? nixpkgs;
assert !(scope.nixpkgs ? pythonPackagesExtension);
assert scope.nixpkgs ? package;
assert scope ? mkVenv;
assert scope ? mkApplication;
assert scope ? mkPytestCheck;
assert !(project ? mkPythonPackagesExtension);
assert !(project ? mkNixpkgsOverlay);
assert !(scope ? mkPythonPackagesExtension);
assert !(scope ? mkNixpkgsPackage);
assert !(scope ? editablePythonSet);
assert !(scope ? mkEditableVenv);
assert editableScope ? editablePythonSet;
assert editableScope ? mkEditableVenv;
assert environScope ? pythonSet;
assert builtins.isAttrs (editableScope.mkEditableVenv { name = "smiley-plot-dev-env"; });
assert builtins.isAttrs (scope.mkVenv { name = "smiley-plot-env"; });
assert builtins.isAttrs (scope.mkApplication { package = "smiley-plot"; });
assert builtins.isAttrs defaultApplication;
assert defaultApplication.pname == "smiley-plot";
assert defaultApplication.version == "0.1.0";
assert builtins.isAttrs customApplication;
assert customApplication.pname == "custom-smiley-plot";
assert customApplication.version == "1.2.3";
assert builtins.isAttrs (scope.mkPytestCheck { package = "smiley-plot"; });
assert builtins.isAttrs defaultPytestCheck;
assert defaultPytestCheck.name == "smiley-plot-pytest";
assert builtins.isAttrs customPytestCheck;
assert customPytestCheck.name == "custom-smiley-pytest";
assert pythonWithProjectExtension.pkgs."smiley-plot".version == "0.1.0";
assert pkgsWithOverlay.python312Packages."smiley-plot".version == "0.1.0";
assert (scope.nixpkgs.package { package = "smiley-plot"; }).version == "0.1.0";
assert (scope.nixpkgs.package { }).version == "0.1.0";
assert customScopePackage.pythonModule.pkgs ? uvloom-marker;
assert customScopePackage.pythonModule.pkgs."smiley-plot".version == "0.1.0";
assert script.name == "example";
assert script.metadata.metadata.requires-python == ">=3.12";
assert script ? raw;
assert script ? forPython;
assert scriptScope ? pythonSet;
assert builtins.compareVersions inferredScriptScope.pythonSet.python.pythonVersion "3.12" >= 0;
assert sdistScript.config.no-binary == true;
assert sdistScriptScope ? pythonSet;
assert sdistScriptScope.pythonSet.tqdm.format == "pyproject";
assert pkgs.lib.hasSuffix ".tar.gz" sdistScriptScope.pythonSet.tqdm.src.name;
assert builtins.isString sdistRenderedScript;
assert scriptScope ? mkVenv;
assert scriptScope ? renderScript;
assert scriptScope ? mkApplication;
assert scriptScope ? mkEditableApplication;
assert builtins.isAttrs (scriptScope.mkVenv { });
assert builtins.isString (scriptScope.renderScript { });
assert builtins.isAttrs (scriptScope.mkApplication { });
assert builtins.isAttrs (
  scriptScope.mkEditableApplication { path = "test/fixtures/scripts/example.py"; }
);
assert scripts ? example;
assert scripts.example.name == "example";
true
