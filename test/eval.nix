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

  fakeFetch =
    args:
    pkgs.runCommand "uvloom-evaluator-${builtins.hashString "sha256" args.url}" {
      passthru = {
        evaluatorFetch = true;
        evaluatorFetchArgs = args;
      };
    } "mkdir -p $out";
  evaluatorStorePath = builtins.toFile "private-wheel-1.0.0-py3-none-any.whl" "not a wheel";
  pathFetch = _args: evaluatorStorePath;
  localEvaluatorSource = builtins.toFile "private-registry-pyproject.toml" (
    builtins.readFile ./fixtures/private-registry/pyproject.toml
  );
  localEvaluatorFetch = builtins.fetchurl {
    url = "file://${builtins.unsafeDiscardStringContext (toString localEvaluatorSource)}";
    sha256 = "sha256-7Fr57ffRQQ7hHYhZ+Ns7d+NrjjcfAdPIOxQ/CNmGCDQ=";
    name = "private-registry-pyproject.toml";
  };
  privateRegistryProject = uvloom.lib.project.load {
    root = ./fixtures/private-registry;
  };
  realShapedFetchurl =
    args:
    let
      fetched = pkgs.fetchurl args;
    in
    fetched
    // {
      outputHash = builtins.convertHash {
        hash = fetched.outputHash;
        hashAlgo = fetched.outputHashAlgo or "sha256";
        toHashFormat = "sri";
      };
      outputHashAlgo = null;
    };
  privateRegistryPkgs = pkgs.extend (
    _: _: {
      fetchurl = realShapedFetchurl;
    }
  );
  privateRegistryScope = privateRegistryProject.forPython {
    pkgs = privateRegistryPkgs;
    interpreter = privateRegistryPkgs.python312;
    evaluatorFetch = fakeFetch;
  };
  privateRegistrySdistScope = privateRegistryProject.forPython {
    inherit pkgs;
    interpreter = pkgs.python312;
    sourcePreference = "sdist";
    evaluatorFetch = fakeFetch;
  };
  privateRegistryPathScope = privateRegistryProject.forPython {
    inherit pkgs;
    interpreter = pkgs.python312;
    evaluatorFetch = pathFetch;
  };
  privateRegistryExtension = privateRegistryProject.nixpkgs.pythonPackagesExtension {
    packages = [ "private-wheel" ];
    evaluatorFetch = pathFetch;
  };
  privateRegistryExtensionPython = pkgs.python312.override {
    self = privateRegistryExtensionPython;
    packageOverrides = privateRegistryExtension;
  };
  privateRegistryNixpkgsScope = privateRegistryProject.forPython {
    pkgs = privateRegistryPkgs;
    interpreter = privateRegistryPkgs.python312;
    fetcher = "nixpkgs";
  };
  authenticatedIndexFetchLib = import ../lib/authenticated-index-fetch.nix {
    inherit (pkgs) lib;
    fail = where: message: throw "uvloom.${where}: ${message}";
  };
  fetchLock = {
    package = [
      {
        name = "private-wheel";
        source.registry = "https://private.example/simple";
        wheels = [
          {
            url = "https://private.example/packages/private-wheel-1.0.0-py3-none-any.whl";
            hash = "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
          }
        ];
        sdist = {
          url = "https://private.example/packages/private-wheel-1.0.0.tar.gz";
          hash = "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb";
        };
      }
      {
        name = "public-wheel";
        source.registry = "https://pypi.org/simple";
        wheels = [
          {
            url = "https://files.pythonhosted.org/packages/public-wheel-1.0.0-py3-none-any.whl";
            hash = "sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc";
          }
        ];
      }
      {
        name = "query-wheel";
        source.registry = "https://private.example/simple";
        wheels = [
          {
            url = "https://private.example/packages/query-wheel-1.0.0-py3-none-any.whl?sig=abc#fragment";
            hash = "sha256:eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee";
          }
        ];
      }
    ];
  };
  authIndex = {
    url = "https://private.example/simple/";
    authenticate = "always";
  };
  privateWheelFetchOverlay = authenticatedIndexFetchLib.mkOverlay {
    lock = fetchLock;
    uvIndexes = [ authIndex ];
    evaluatorFetch = fakeFetch;
  };
  privateWheel =
    (privateWheelFetchOverlay { } {
      fetchurl = _: throw "base fetchurl should not be called";
    }).fetchurl
      {
        url = "https://private.example/packages/private-wheel-1.0.0-py3-none-any.whl";
        hash = "sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd";
        name = "caller-name.whl";
      };
  privateSdist =
    (privateWheelFetchOverlay { } {
      fetchurl = _: throw "base fetchurl should not be called";
    }).fetchurl
      {
        url = "https://private.example/packages/private-wheel-1.0.0.tar.gz";
        hash = "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb";
      };
  queryWheel =
    (privateWheelFetchOverlay { } {
      fetchurl = _: throw "base fetchurl should not be called";
    }).fetchurl
      {
        url = "https://private.example/packages/query-wheel-1.0.0-py3-none-any.whl?sig=abc#fragment";
      };
  duplicateFetch =
    let
      duplicatePackage = builtins.elemAt fetchLock.package 0;
      duplicateWheel = builtins.elemAt duplicatePackage.wheels 0;
    in
    (authenticatedIndexFetchLib.mkOverlay {
      lock = fetchLock // {
        package = fetchLock.package ++ [
          (
            duplicatePackage
            // {
              wheels = [
                (
                  duplicateWheel
                  // {
                    hash = "sha256-qqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqo=";
                  }
                )
              ];
            }
          )
        ];
      };
      uvIndexes = [ authIndex ];
      evaluatorFetch = fakeFetch;
    } { } { fetchurl = _: throw "base fetchurl should not be called"; }).fetchurl
      {
        url = "https://private.example/packages/private-wheel-1.0.0-py3-none-any.whl";
      };
  publicDelegation =
    (privateWheelFetchOverlay { } {
      fetchurl = args: {
        delegated = true;
        inherit args;
      };
    }).fetchurl
      {
        url = "https://files.pythonhosted.org/packages/public-wheel-1.0.0-py3-none-any.whl";
        hash = "sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc";
        name = "public-wheel-1.0.0-py3-none-any.whl";
      };
  evaluatorDirectURLDelegation =
    (authenticatedIndexFetchLib.mkOverlay
      {
        lock = fetchLock;
        uvIndexes = [ authIndex ];
        authenticatedOnly = false;
        evaluatorFetch = fakeFetch;
      }
      { }
      {
        fetchurl = args: {
          delegated = true;
          inherit args;
        };
      }
    ).fetchurl
      {
        url = "https://example.com/packages/direct.whl";
        hash = "sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd";
        name = "direct.whl";
      };
  evaluatorPublicFetch =
    (authenticatedIndexFetchLib.mkOverlay
      {
        lock = fetchLock;
        uvIndexes = [ authIndex ];
        authenticatedOnly = false;
        evaluatorFetch = fakeFetch;
      }
      { }
      {
        fetchurl = args: {
          delegated = true;
          inherit args;
        };
      }
    ).fetchurl
      {
        url = "https://files.pythonhosted.org/packages/public-wheel-1.0.0-py3-none-any.whl";
        hash = "sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc";
        name = "public-wheel-1.0.0-py3-none-any.whl";
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

  scriptEvaluatorScope = script.forPython {
    inherit pkgs;
    fetcher = "evaluator";
    evaluatorFetch = fakeFetch;
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
assert scope ? hook;
assert scope ? hooks;
assert scope.hooks ? repoRoot;
assert scope.hooks ? uv;
assert scope.hooks ? python;
assert scope.hooks ? default;
assert scope.hook == scope.hooks.default;
assert builtins.match ".*REPO_ROOT.*" scope.hook != null;
assert builtins.match ".*rev-parse --show-toplevel.*" scope.hooks.repoRoot != null;
assert builtins.match ".*UV_NO_SYNC.*" scope.hook != null;
assert
  builtins.match ".*${builtins.unsafeDiscardStringContext (pkgs.lib.getExe scope.interpreter)}.*" scope.hooks.uv
  != null;
assert builtins.match ".*UV_PYTHON_DOWNLOADS.*" scope.hook != null;
assert builtins.match ".*PYTHONPATH.*" scope.hook != null;
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
      members = [ "smiley-plot" ];
    };
  }
);
assert builtins.isAttrs (
  scope.venv {
    name = "smiley-plot-dev-env-true";
    editable = true;
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
assert scriptScope ? hook;
assert scriptScope ? hooks;
assert scriptScope ? interpreter;
assert scriptScope.hook == scriptScope.hooks.default;
assert
  builtins.match ".*${builtins.unsafeDiscardStringContext (pkgs.lib.getExe scriptScope.interpreter)}.*" scriptScope.hooks.uv
  != null;
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
assert privateWheel.evaluatorFetch;
assert
  privateWheel.evaluatorFetchArgs.sha256 == "sha256-qqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqo=";
assert privateWheel.evaluatorFetchArgs.name == "caller-name.whl";
assert privateSdist.evaluatorFetch;
assert
  privateSdist.evaluatorFetchArgs.sha256 == "sha256-u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7s=";
assert privateSdist.evaluatorFetchArgs.name == "private-wheel-1.0.0.tar.gz";
assert queryWheel.evaluatorFetch;
assert queryWheel.evaluatorFetchArgs.name == "query-wheel-1.0.0-py3-none-any.whl";
assert duplicateFetch.evaluatorFetch;
assert publicDelegation.delegated;
assert evaluatorPublicFetch.evaluatorFetch;
assert evaluatorDirectURLDelegation.delegated;
# Evaluator fetch must be part of package derivation, not only a replacement .src attribute.
assert
  privateRegistryScope.pythonSet.private-wheel.drvPath
  != privateRegistryNixpkgsScope.pythonSet.private-wheel.drvPath;
assert privateRegistryScope.pythonSet.private-wheel.src.evaluatorFetch;
assert
  privateRegistryScope.pythonSet.private-wheel.src.evaluatorFetchArgs.url
  == "https://private.example/packages/private-wheel-1.0.0-py3-none-any.whl";
assert
  privateRegistryScope.pythonSet.private-wheel.src.evaluatorFetchArgs.sha256
  == "sha256-qqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqo=";
# Evaluator fetch result must be usable as direct package source path, not only as a fetch derivation.
assert builtins.isString privateRegistryPathScope.pythonSet.private-wheel.src;
assert builtins.hasContext privateRegistryPathScope.pythonSet.private-wheel.src;
assert
  !(
    builtins.isAttrs privateRegistryPathScope.pythonSet.private-wheel.src
    && privateRegistryPathScope.pythonSet.private-wheel.src ? drvPath
  );
assert privateRegistryPathScope.pythonSet.private-wheel.src == evaluatorStorePath;
# nixpkgs export consumes direct evaluator store path without evaluating/building invalid wheel contents.
assert privateRegistryExtensionPython.pkgs.private-wheel.src.src == evaluatorStorePath;
# builtins.fetchurl returns same contextual string shape for deterministic local files.
assert builtins.isString localEvaluatorFetch;
assert builtins.hasContext localEvaluatorFetch;
assert !(builtins.isAttrs localEvaluatorFetch && localEvaluatorFetch ? drvPath);
assert
  localEvaluatorFetch == builtins.fetchurl {
    url = "file://${builtins.unsafeDiscardStringContext (toString localEvaluatorSource)}";
    sha256 = "sha256-7Fr57ffRQQ7hHYhZ+Ns7d+NrjjcfAdPIOxQ/CNmGCDQ=";
    name = "private-registry-pyproject.toml";
  };
assert privateRegistrySdistScope.pythonSet.private-wheel.src.evaluatorFetch;
assert
  privateRegistrySdistScope.pythonSet.private-wheel.src.evaluatorFetchArgs.url
  == "https://private.example/packages/private-wheel-1.0.0.tar.gz";
assert
  privateRegistrySdistScope.pythonSet.private-wheel.src.evaluatorFetchArgs.name
  == "private-wheel-1.0.0.tar.gz";
assert scriptEvaluatorScope.pythonSet.tqdm.src.evaluatorFetch;
assert
  privateRegistryNixpkgsScope.pythonSet.private-wheel.src.outputHash
  == "sha256-qqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqo=";
assert privateRegistryNixpkgsScope.pythonSet.private-wheel.src.outputHashAlgo == null;
true
