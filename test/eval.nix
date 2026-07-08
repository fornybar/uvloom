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

  # filterSource = true must produce a store source containing only the
  # whitelisted files and workspace member sources (whitelist-based source
  # filtering: nothing outside the whitelist reaches the store copy).
  filteredProject = uvloom.lib.project.load {
    root = ../templates/simple;
    filterSource = true;
  };

  # Common root build-backend configuration files survive source filtering.
  filteredBackendProject = uvloom.lib.project.load {
    root = ./fixtures/smiley-plot;
    filterSource = true;
  };

  # extraSourcePaths whitelists additional trees into the filtered source: a
  # filtered project can still carry its test suite into the store copy.
  filteredProjectWithTests = uvloom.lib.project.load {
    root = ../templates/simple;
    filterSource = true;
    extraSourcePaths = [
      "tests"
      "does-not-exist"
    ];
  };

  # Explicit extras are an escape hatch: unlike inferred package trees,
  # hidden paths selected here must survive the filtered source.
  filteredProjectWithHiddenExtra = uvloom.lib.project.load {
    root = ./fixtures/flat-package;
    filterSource = true;
    extraSourcePaths = [ "flat_pkg/.hidden" ];
  };

  # Flat-layout package: local sources derive from uv.lock, and the
  # top-level module directory named after [project].name survives filtering.
  filteredFlatProject = uvloom.lib.project.load {
    root = ./fixtures/flat-package;
    filterSource = true;
  };

  # Flat layout coexisting with a non-Python src/ directory: src/ holds
  # assets only, so the flat fallbacks (name-derived module dir plus
  # top-level *.py) must still apply alongside it instead of being
  # suppressed by the mere presence of src/.
  filteredFlatAssetsProject = uvloom.lib.project.load {
    root = ./fixtures/flat-with-assets;
    filterSource = true;
  };

  # filterSource = false must not force any of the filter machinery: even a
  # throwing extraSourcePaths value passes through untouched.
  unfilteredLazyProject = uvloom.lib.project.load {
    root = ./fixtures/flat-package;
    extraSourcePaths = throw "extraSourcePaths forced despite filterSource = false";
  };

  # Declared readme + backend-configured package dirs survive filtering:
  # [project].readme points outside the root README* scan, and the hatch
  # wheel target names a directory that differs from the name-derived module.
  filteredReadmeProject = uvloom.lib.project.load {
    root = ./fixtures/readme-package;
    filterSource = true;
  };

  # Declared license files and mixed-case flat package dirs survive filtering.
  filteredLicenseProject = uvloom.lib.project.load {
    root = ./fixtures/license-package;
    filterSource = true;
  };

  # tool.setuptools.packages (plain list form): only the top-level segment
  # before the first dot maps to a directory under root.
  filteredSetuptoolsProject = uvloom.lib.project.load {
    root = ./fixtures/setuptools-flat;
    filterSource = true;
  };

  # uv.lock `directory` sources, additive package dirs, and hidden-directory
  # pruning: the vendored local dependency's tree survives filtering, the
  # hatch-configured extra_pkg is included alongside src/, and nothing under
  # a hidden directory (src/.../.pytest_cache/) reaches the store copy.
  filteredDirSourceProject = uvloom.lib.project.load {
    root = ./fixtures/dir-source;
    filterSource = true;
  };

  # uv.lock `path` sources are local wheel/sdist archives: the referenced
  # file survives filtering alongside the root package sources.
  filteredPathSourceProject = uvloom.lib.project.load {
    root = ./fixtures/path-source;
    filterSource = true;
  };

  # Non-root `virtual` workspace members carry no package sources, but their
  # pyproject.toml must survive filtering (uv2nix folds member manifests'
  # [tool.uv] config into the workspace configuration).
  filteredVirtualMemberProject = uvloom.lib.project.load {
    root = ./fixtures/virtual-member;
    filterSource = true;
  };

  # A root `virtual = "."` package ([tool.uv] package = false) builds no
  # wheel, but its app code must still reach the filtered source: the root
  # package sources (top-level *.py here) are included, while arbitrary
  # other directories remain an extraSourcePaths concern.
  filteredVirtualRootProject = uvloom.lib.project.load {
    root = ./fixtures/non-package-root;
    filterSource = true;
  };

  filteredVirtualRootProjectWithUtils = uvloom.lib.project.load {
    root = ./fixtures/non-package-root;
    filterSource = true;
    extraSourcePaths = [ "utils" ];
  };

  # Declared [project] metadata with a hidden path segment survives the
  # hidden-leaf filter: the declared readme is unioned back after the
  # intersection (root-level scan results stay subject to the filter).
  filteredDotfileReadmeProject = uvloom.lib.project.load {
    root = ./fixtures/dotfile-readme;
    filterSource = true;
  };

  filteredHatchPatternsProject = uvloom.lib.project.load {
    root = ./fixtures/hatch-patterns;
    filterSource = true;
  };

  filteredScope = filteredProject.forPython {
    inherit pkgs;
    interpreter = pkgs.python312;
  };

  filteredPytestCheck = filteredScope.check.pytest {
    package = "smiley-plot";
  };

  filteredDirSourceScope = filteredDirSourceProject.forPython {
    inherit pkgs;
    interpreter = pkgs.python312;
  };

  filteredPathSourceScope = filteredPathSourceProject.forPython {
    inherit pkgs;
    interpreter = pkgs.python312;
  };

  # Editable installs resolve member subpaths against the workspace root via
  # lib.path.splitRoot, which requires filteredProject.root to be a path.
  filteredEditableVenv = filteredScope.venv {
    name = "filtered-editable-env";
    editable = true;
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

  filterSourceLib = import ../lib/filter-source.nix {
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
assert project ? sourceRoot;
assert project.sourceRoot == ./fixtures/smiley-plot;
assert filteredProject.root == ../templates/simple;
assert filteredProject ? sourceRoot;
assert builtins.pathExists (filteredProject.sourceRoot + "/pyproject.toml");
assert builtins.pathExists (filteredProject.sourceRoot + "/uv.lock");
assert builtins.pathExists (filteredProject.sourceRoot + "/src/smiley_plot");
assert !builtins.pathExists (filteredProject.sourceRoot + "/flake.nix");
assert !builtins.pathExists (filteredProject.sourceRoot + "/tests");
assert builtins.pathExists (filteredBackendProject.sourceRoot + "/setup.py");
assert builtins.pathExists (filteredBackendProject.sourceRoot + "/setup.cfg");
assert builtins.pathExists (filteredBackendProject.sourceRoot + "/hatch.toml");
assert builtins.pathExists (filteredBackendProject.sourceRoot + "/MANIFEST.in");
assert filteredProject.workspace ? deps;
assert builtins.typeOf filteredProject.root == "path";
# project.root stays a genuine path for uv2nix workspace/editable path math;
# project.sourceRoot carries the SourceLike filtered source used for package
# src values when source filtering is enabled.
assert builtins.pathExists filteredProject.root;
assert builtins.pathExists filteredProject.sourceRoot;
assert builtins.typeOf (filteredProject.root + "/pyproject.toml") == "path";
assert builtins.typeOf (filteredProject.sourceRoot + "/pyproject.toml") == "string";
assert builtins.pathExists (filteredProjectWithTests.sourceRoot + "/tests");
assert builtins.pathExists (filteredProjectWithTests.sourceRoot + "/pyproject.toml");
assert !builtins.pathExists (filteredProjectWithTests.sourceRoot + "/flake.nix");
assert filteredFlatProject.sourceRoot ? outPath;
assert builtins.pathExists (filteredFlatProject.sourceRoot + "/flat_pkg/__init__.py");
assert builtins.pathExists (filteredFlatProject.sourceRoot + "/uv.lock");
assert !builtins.pathExists (filteredFlatProject.sourceRoot + "/flat_pkg/.hidden");
assert builtins.pathExists (filteredProjectWithHiddenExtra.sourceRoot + "/flat_pkg/.hidden");
# The `.python-version` exemption is scoped to the root-level file: the
# whitelisted root entry survives, but a `.python-version` inside a member
# tree is a dotfile and stays dropped.
assert builtins.pathExists (filteredFlatProject.sourceRoot + "/.python-version");
assert !builtins.pathExists (filteredFlatProject.sourceRoot + "/flat_pkg/.python-version");
# Non-Python src/ must not suppress the flat fallbacks: the name-derived
# module dir and the top-level *.py survive filtering next to the asset
# directory (which is included as-is).
assert filteredFlatAssetsProject.sourceRoot ? outPath;
assert builtins.pathExists (filteredFlatAssetsProject.sourceRoot + "/flat_assets/__init__.py");
assert builtins.pathExists (filteredFlatAssetsProject.sourceRoot + "/cli.py");
assert builtins.pathExists (filteredFlatAssetsProject.sourceRoot + "/src/logo.txt");
assert unfilteredLazyProject.root == ./fixtures/flat-package;
assert filteredReadmeProject.sourceRoot ? outPath;
assert builtins.pathExists (filteredReadmeProject.sourceRoot + "/docs/README.md");
assert builtins.pathExists (filteredReadmeProject.sourceRoot + "/readme_mod/__init__.py");
assert filteredLicenseProject.sourceRoot ? outPath;
assert builtins.pathExists (filteredLicenseProject.sourceRoot + "/LICENSE");
assert builtins.pathExists (filteredLicenseProject.sourceRoot + "/COPYING.md");
assert builtins.pathExists (filteredLicenseProject.sourceRoot + "/licenses/NOTICE");
# NOTICE*/AUTHORS* are PEP 639 default metadata names: the root scan must
# carry them into the filtered source alongside the LICENSE spellings.
assert builtins.pathExists (filteredLicenseProject.sourceRoot + "/NOTICE.txt");
assert builtins.pathExists (filteredLicenseProject.sourceRoot + "/AUTHORS");
# `LICEN[CS]E*` character class expands to both spellings; non-matching
# names and directory entries matched by name stay out.
assert builtins.pathExists (filteredLicenseProject.sourceRoot + "/legal/LICENSE.a");
assert builtins.pathExists (filteredLicenseProject.sourceRoot + "/legal/LICENCE.b");
assert !builtins.pathExists (filteredLicenseProject.sourceRoot + "/legal/OTHER");
assert !builtins.pathExists (filteredLicenseProject.sourceRoot + "/legal/LICENSE.dir");
assert !builtins.pathExists (filteredLicenseProject.sourceRoot + "/COPYING.d");
assert builtins.pathExists (filteredLicenseProject.sourceRoot + "/Foo_Pkg/__init__.py");
assert !builtins.pathExists (filteredLicenseProject.sourceRoot + "/flake.nix");
assert builtins.pathExists (filteredSetuptoolsProject.sourceRoot + "/my_app/__init__.py");
assert builtins.pathExists (filteredSetuptoolsProject.sourceRoot + "/my_app/sub/__init__.py");
assert filteredDirSourceProject.sourceRoot ? outPath;
assert filteredDirSourceProject.root == ./fixtures/dir-source;
assert builtins.pathExists (
  filteredDirSourceProject.sourceRoot + "/src/dir_source_app/__init__.py"
);
assert builtins.pathExists (filteredDirSourceProject.sourceRoot + "/extra_pkg/__init__.py");
assert builtins.pathExists (
  filteredDirSourceProject.sourceRoot + "/vendored/localdep/localdep/__init__.py"
);
assert
  !builtins.pathExists (filteredDirSourceProject.sourceRoot + "/src/dir_source_app/.pytest_cache");
assert
  !builtins.pathExists (
    filteredDirSourceProject.sourceRoot + "/src/dir_source_app/.pytest_cache/marker.txt"
  );
assert filteredPathSourceProject.sourceRoot ? outPath;
assert filteredPathSourceProject.root == ./fixtures/path-source;
assert builtins.pathExists (
  filteredPathSourceProject.sourceRoot + "/vendored/localwheel-0.1.0-py3-none-any.whl"
);
assert builtins.pathExists (
  filteredPathSourceProject.sourceRoot + "/src/path_source_app/__init__.py"
);
assert filteredVirtualMemberProject.sourceRoot ? outPath;
assert builtins.pathExists (
  filteredVirtualMemberProject.sourceRoot + "/tools/helper/pyproject.toml"
);
assert !builtins.pathExists (filteredVirtualMemberProject.sourceRoot + "/tools/helper/notes.txt");
assert builtins.pathExists (
  filteredVirtualMemberProject.sourceRoot + "/src/virtual_member_root/__init__.py"
);
assert filteredVirtualRootProject.sourceRoot ? outPath;
assert builtins.pathExists (filteredVirtualRootProject.sourceRoot + "/app.py");
assert builtins.pathExists (filteredVirtualRootProject.sourceRoot + "/pyproject.toml");
assert builtins.pathExists (filteredVirtualRootProject.sourceRoot + "/uv.lock");
assert !builtins.pathExists (filteredVirtualRootProject.sourceRoot + "/utils");
assert !builtins.pathExists (filteredVirtualRootProject.sourceRoot + "/tests");
assert builtins.pathExists (filteredVirtualRootProjectWithUtils.sourceRoot + "/utils/helpers.py");
assert builtins.pathExists (filteredVirtualRootProjectWithUtils.sourceRoot + "/app.py");
assert !builtins.pathExists (filteredVirtualRootProjectWithUtils.sourceRoot + "/tests");
assert builtins.pathExists (filteredDotfileReadmeProject.sourceRoot + "/.github/README.md");
assert builtins.pathExists (
  filteredDotfileReadmeProject.sourceRoot + "/src/dotfile_readme/__init__.py"
);
assert builtins.pathExists (filteredHatchPatternsProject.sourceRoot + "/pkg/mod.py");
assert builtins.pathExists (filteredHatchPatternsProject.sourceRoot + "/src/pkg/data/a.json");
assert builtins.pathExists (filteredHatchPatternsProject.sourceRoot + "/tests/test_ok.py");
assert builtins.pathExists (filteredHatchPatternsProject.sourceRoot + "/assets/schema.json");
assert !builtins.pathExists (filteredHatchPatternsProject.sourceRoot + "/flake.nix");
assert filteredScope.pythonSet."smiley-plot".src == filteredProject.sourceRoot;
assert filteredPytestCheck.src == filteredProject.sourceRoot;
assert !builtins.pathExists (filteredPytestCheck.src + "/flake.nix");
assert filteredDirSourceScope.pythonSet."dir-source-app".src == filteredDirSourceProject.sourceRoot;
assert
  filteredDirSourceScope.pythonSet.localdep.src
  == filteredDirSourceProject.sourceRoot + "/vendored/localdep";
assert
  filteredPathSourceScope.pythonSet."path-source-app".src == filteredPathSourceProject.sourceRoot;
assert
  filteredPathSourceScope.pythonSet.localwheel.src.outPath
  == "${filteredPathSourceProject.sourceRoot + "/vendored/localwheel-0.1.0-py3-none-any.whl"}";
assert
  filteredPathSourceScope.pythonSet.localwheel.src.passthru.url
  == "vendored/localwheel-0.1.0-py3-none-any.whl";
assert builtins.isString filteredEditableVenv.drvPath;
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
  filterSourceLib.internal.expandClasses "LICEN[CS]E*" "LICEN[CS]E*" == [
    "LICENCE*"
    "LICENSE*"
  ];
assert
  (filterSourceLib.internal.parsedPattern "legal/LICEN[CS]E*") // { alternatives = null; } == {
    dirPart = "legal";
    dirParts = [ "legal" ];
    alternatives = null;
  };
assert
  map (alt: alt.prefix) (filterSourceLib.internal.parsedPattern "LICEN[CS]E*").alternatives == [
    "LICENCE"
    "LICENSE"
  ];
# A leading `./` in a license-files pattern is a no-op relative to the
# project root: it normalizes away instead of tripping the root-whitelist
# check with a misleading error.
assert
  (filterSourceLib.internal.parsedPattern "./LICENSE*") // { alternatives = null; } == {
    dirPart = "";
    dirParts = [ ];
    alternatives = null;
  };
assert
  (filterSourceLib.internal.parsedPattern "./legal/LICENSE*") // { alternatives = null; } == {
    dirPart = "legal";
    dirParts = [ "legal" ];
    alternatives = null;
  };
assert filterSourceLib.internal.checkInside "docs/README.md" == "docs/README.md";
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
true
