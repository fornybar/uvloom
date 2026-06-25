{
  pkgs,
  uvloom,
  pyproject-nix,
}:

let
  project = uvloom.lib.project.load {
    root = ./fixtures/smiley-plot;
  };

  multiScriptProject = uvloom.lib.project.load {
    root = ./fixtures/multi-script-app;
  };

  projectWithForgeFetchSources = uvloom.lib.project.load {
    root = ./fixtures/smiley-plot;
    forgeFetch = null;
  };

  scope = project.forPython {
    inherit pkgs;
    interpreter = pkgs.python312;
  };

  multiScriptScope = multiScriptProject.forPython {
    inherit pkgs;
    interpreter = pkgs.python312;
  };

  nullForgeFetchScope = project.forPython {
    inherit pkgs;
    interpreter = pkgs.python312;
    forgeFetch = null;
  };

  projectForgeFetchScope = projectWithForgeFetchSources.forPython {
    inherit pkgs;
    interpreter = pkgs.python312;
  };

  omittedForgeFetchExtension = project.nixpkgs.pythonPackagesExtension {
    packages = [ "smiley-plot" ];
  };

  nullForgeFetchExtension = project.nixpkgs.pythonPackagesExtension {
    packages = [ "smiley-plot" ];
    forgeFetch = null;
  };

  forgeFetchLib = import ../lib/forge-fetch {
    inherit pyproject-nix;
    inherit (pkgs) lib;
    fail = where: message: throw "uvloom.${where}: ${message}";
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

  script = uvloom.lib.inline.load {
    path = ./fixtures/scripts/example.py;
  };

  scriptScope = script.forPython {
    inherit pkgs;
    interpreter = pkgs.python312;
  };

  inferredScriptScope = script.forPython {
    inherit pkgs;
  };

  sdistScript = uvloom.lib.inline.load {
    path = ./fixtures/scripts/example.py;
    config.no-binary = true;
  };

  sdistScriptScope = sdistScript.forPython {
    inherit pkgs;
    interpreter = pkgs.python312;
  };

  sdistRenderedScript = sdistScriptScope.render { };

  defaultApplication = scope.app { };

  packageApplication = scope.app {
    package = "smiley-plot";
  };

  customApplication = scope.app {
    pname = "custom-smiley-plot";
    version = "1.2.3";
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

  commandApplication = scope.app {
    name = "smiley-command";
    command = [
      "python"
      "-c"
      "print('ok')"
    ];
  };

  defaultPytestCheck = scope.check.pytest { };

  customPytestCheck = scope.check.pytest {
    name = "custom-smiley-pytest";
  };

  scripts = uvloom.lib.inline.fromDir {
    root = ./fixtures/scripts;
  };

  lockedRev = "0123456789abcdef0123456789abcdef01234567";
in
assert uvloom.lib.apiVersion == 2;
assert uvloom.lib ? project;
assert uvloom.lib.project ? load;
assert uvloom.lib ? inline;
assert uvloom.lib.inline ? load;
assert uvloom.lib.inline ? fromDir;
assert !(uvloom.lib.inline ? dir);
assert !(uvloom.lib ? loadProject);
assert !(uvloom.lib ? loadScript);
assert !(uvloom.lib ? loadScripts);
assert project ? root;
assert project.root == ./fixtures/smiley-plot;
assert project ? workspace;
assert project.workspace ? deps;
assert project.workspace ? mkPyprojectOverlay;
assert project ? forPython;
assert project ? nixpkgs;
assert project.nixpkgs ? pythonPackagesExtension;
assert project.nixpkgs ? overlay;
assert scope ? interpreter;
assert nullForgeFetchScope.pythonSet."smiley-plot".version == scope.pythonSet."smiley-plot".version;
assert
  projectForgeFetchScope.pythonSet."smiley-plot".version == scope.pythonSet."smiley-plot".version;
assert builtins.isFunction omittedForgeFetchExtension;
assert builtins.isFunction nullForgeFetchExtension;
assert
  forgeFetchLib.internal.validateConfig "auto" == {
    mode = "auto";
    packages = null;
  };
assert
  forgeFetchLib.internal.validateConfig [ "demo" ] == {
    mode = "explicit";
    packages = [ "demo" ];
  };
assert
  forgeFetchLib.internal.validateConfig { packages = [ "demo" ]; } == {
    mode = "explicit";
    packages = [ "demo" ];
  };
assert forgeFetchLib.internal.normalizePackageName "My_Pkg.Name" == "my-pkg-name";
assert
  forgeFetchLib.internal.parseGitSource "git+https://github.com/OWNER/REPO.git#${lockedRev}" == {
    url = "git+https://github.com/OWNER/REPO.git";
    rev = lockedRev;
  };
assert
  forgeFetchLib.internal.parseGitSource "git+https://github.com/OWNER/REPO.git?subdirectory=packages/demo&rev=main#${lockedRev}"
  == {
    url = "git+https://github.com/OWNER/REPO.git";
    rev = lockedRev;
    subdirectory = "packages/demo";
  };
assert
  forgeFetchLib.internal.parseGitSource "git+https://github.com/OWNER/REPO.git?subdirectory=packages/demo#${lockedRev}"
  == {
    url = "git+https://github.com/OWNER/REPO.git";
    rev = lockedRev;
    subdirectory = "packages/demo";
  };
assert
  forgeFetchLib.internal.parseGitSource "git+https://github.com/OWNER/REPO.git?tag=pyshop-binaries%2Fv17.14.0#${lockedRev}"
  == {
    url = "git+https://github.com/OWNER/REPO.git";
    rev = lockedRev;
  };
assert
  forgeFetchLib.internal.parseGitSource "git+https://github.com/OWNER/REPO.git?branch=main#${lockedRev}"
  == {
    url = "git+https://github.com/OWNER/REPO.git";
    rev = lockedRev;
  };
assert
  forgeFetchLib.internal.parseGitSource "git+https://github.com/OWNER/REPO.git?subdirectory=packages%2Fdemo&tag=v1.2.3#${lockedRev}"
  == {
    url = "git+https://github.com/OWNER/REPO.git";
    rev = lockedRev;
    subdirectory = "packages/demo";
  };
assert
  forgeFetchLib.internal.parseGitSource "git+https://github.com/OWNER/REPO.git?rev=${lockedRev}" == {
    url = "git+https://github.com/OWNER/REPO.git";
    rev = lockedRev;
  };
assert
  forgeFetchLib.internal.parseForgeUrl "https://github.com/OWNER/REPO.git" == {
    type = "github";
    owner = "OWNER";
    repo = "REPO";
  };
assert
  forgeFetchLib.internal.parseForgeUrl "git@gitlab.com:OWNER/REPO.git" == {
    type = "gitlab";
    owner = "OWNER";
    repo = "REPO";
  };
assert
  forgeFetchLib.internal.parseForgeUrl "https://gitlab.com/GROUP/SUBGROUP/REPO.git" == {
    type = "gitlab";
    owner = "GROUP/SUBGROUP";
    repo = "REPO";
  };
assert
  forgeFetchLib.internal.mkFetchTreeInput {
    attrName = "demo";
    sourceGit = "git+https://github.com/OWNER/REPO.git#${lockedRev}";
  } == {
    type = "github";
    owner = "OWNER";
    repo = "REPO";
    rev = lockedRev;
  };
assert
  forgeFetchLib.internal.mkFetchTreeInput {
    attrName = "demo";
    sourceGit = "git+https://github.com/OWNER/REPO.git?subdirectory=packages/demo&tag=v1.0.0#${lockedRev}";
  } == {
    type = "github";
    owner = "OWNER";
    repo = "REPO";
    rev = lockedRev;
  };
assert
  forgeFetchLib.internal.mkSourceValue {
    url = "git+https://github.com/OWNER/REPO.git";
    rev = lockedRev;
    subdirectory = "packages/demo";
  } "/nix/store/eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee-source"
  == "/nix/store/eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee-source";
assert
  forgeFetchLib.internal.selectPackages {
    packages = [ "My_Pkg" ];
    uvLock.package = [
      {
        name = "my-pkg";
        source.git = "https://github.com/o/r.git#abcdef";
      }
    ];
  } == [
    {
      attrName = "my-pkg";
      requestedName = "My_Pkg";
      sourceGit = "https://github.com/o/r.git#abcdef";
    }
  ];
assert
  forgeFetchLib.internal.selectAutoPackages {
    package = [
      {
        name = "git-pkg";
        source.git = "https://github.com/o/r.git#abcdef";
      }
      {
        name = "registry-pkg";
        source.registry = "https://pypi.org/simple";
      }
    ];
  } == [
    {
      attrName = "git-pkg";
      requestedName = "git-pkg";
      sourceGit = "https://github.com/o/r.git#abcdef";
    }
  ];
assert pkgs.lib.getExe scope.interpreter == pkgs.python312.interpreter;
assert scope ? pythonSet;
assert scope ? nixpkgs;
assert !(scope.nixpkgs ? pythonPackagesExtension);
assert scope.nixpkgs ? package;
assert scope ? venv;
assert !(scope ? mkVenv);
assert scope ? app;
assert !(scope ? mkApplication);
assert scope ? check;
assert scope.check ? pytest;
assert !(scope ? mkPytestCheck);
assert !(project ? mkPythonPackagesExtension);
assert !(project ? mkNixpkgsOverlay);
assert !(scope ? mkPythonPackagesExtension);
assert !(scope ? mkNixpkgsPackage);
assert !(scope ? editablePythonSet);
assert !(scope ? mkEditableVenv);
assert environScope ? pythonSet;
assert builtins.isAttrs (scope.venv { name = "smiley-plot-env"; });
assert builtins.isAttrs (
  scope.venv {
    name = "smiley-plot-dev-env";
    editable = {
      root = "$REPO_ROOT";
      members = [ "smiley-plot" ];
    };
  }
);
assert builtins.isAttrs packageApplication;
assert packageApplication.pname == "smiley-plot";
assert packageApplication.version == "0.1.0";
assert builtins.isAttrs defaultApplication;
assert defaultApplication.pname == "smiley-plot";
assert defaultApplication.version == "0.1.0";
assert builtins.isAttrs customApplication;
assert customApplication.pname == "custom-smiley-plot";
assert customApplication.version == "1.2.3";
assert builtins.isAttrs scriptApplication;
assert scriptApplication.pname == "smiley-plot";
assert scriptApplication.version == "0.1.0";
assert builtins.isAttrs scriptApplicationWithVenv;
assert scriptApplicationWithVenv.pname == "smiley-plot";
assert scriptApplicationWithVenv.version == "0.1.0";
assert builtins.isAttrs scriptPnameApplication;
assert scriptPnameApplication.pname == "custom-smiley-plot";
assert scriptPnameApplication.version == "0.1.0";
assert builtins.isAttrs multiScriptApplication;
assert multiScriptApplication.pname == "first-tool";
assert multiScriptApplication.version == "0.1.0";
assert builtins.isAttrs commandApplication;
assert commandApplication.name == "smiley-command";
assert builtins.isAttrs (scope.check.pytest { package = "smiley-plot"; });
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
assert scriptScope ? venv;
assert !(scriptScope ? mkVenv);
assert scriptScope ? render;
assert !(scriptScope ? renderScript);
assert scriptScope ? app;
assert !(scriptScope ? mkApplication);
assert scriptScope.app ? editable;
assert !(scriptScope ? editable);
assert !(scriptScope ? mkEditableApplication);
assert builtins.isAttrs (scriptScope.venv { });
assert builtins.isString (scriptScope.render { });
assert builtins.isAttrs (scriptScope.app { });
assert builtins.isAttrs (scriptScope.app.editable { path = "test/fixtures/scripts/example.py"; });
assert scripts ? example;
assert scripts.example.name == "example";
true
