{
  lib,
  pyproject-nix,
  fail,
}:

let
  where = "forgeFetch";
  configTypeError = "must be null, `auto`, a package-name list, or an attribute set with `packages`";
  builtInHosts = {
    "github.com" = "github";
    "gitlab.com" = "gitlab";
  };

  failPackage = name: message: fail where "package `${name}`: ${message}";

  inherit (pyproject-nix.lib.pypa) normalizePackageName;

  configLib = import ./config.nix {
    inherit
      lib
      fail
      where
      configTypeError
      ;
    inherit builtInHosts;
  };

  gitSource = import ./git-source.nix {
    inherit lib fail where;
  };

  forgeUrl = import ./forge-url.nix {
    inherit lib fail where;
    inherit builtInHosts;
  };

  packages = import ./packages.nix {
    inherit
      lib
      fail
      where
      ;
    inherit failPackage normalizePackageName;
  };

  mkFetchTreeInput =
    entry:
    let
      parsedGit = gitSource.parseGitSource entry.sourceGit;
      forgeInput = forgeUrl.parseForgeUrl parsedGit.url (entry.forgeHosts or { });
      owner =
        if forgeInput.type == "gitlab" then
          lib.replaceStrings [ "/" ] [ "%2F" ] forgeInput.owner
        else
          forgeInput.owner;
    in
    {
      type = forgeInput.type;
      inherit owner;
      inherit (forgeInput) repo;
      inherit (parsedGit) rev;
    }
    // lib.optionalAttrs (!(forgeInput.host == "github.com" || forgeInput.host == "gitlab.com")) {
      host = forgeInput.host;
    };

  mkSourceEntry = fetchTree: hosts: entry: {
    name = entry.attrName;
    value = builtins.addErrorContext "while fetching forgeFetch package `${entry.attrName}`" (
      let
        parsedGit = gitSource.parseGitSource entry.sourceGit;
        fetched = fetchTree (mkFetchTreeInput (entry // { forgeHosts = hosts; }));
      in
      mkSourceValue parsedGit fetched
    );
  };

  mkSourceValue = _parsedGit: fetched: fetched;

  overridePackageSrc =
    prev: name: src:
    if builtins.hasAttr name prev then
      if prev.${name} ? overrideAttrs && builtins.isFunction prev.${name}.overrideAttrs then
        prev.${name}.overrideAttrs (_old: {
          inherit src;
        })
      else
        failPackage name "present in python set but cannot be overridden with overrideAttrs"
    else
      failPackage name "not present in python set";

  mkOverlay =
    {
      root,
      config,
      uvLock ? builtins.fromTOML (builtins.readFile (root + "/uv.lock")),
      fetchTree ? builtins.fetchTree,
    }:
    let
      forgeConfig = configLib.validateConfig config;
    in
    if forgeConfig == null then
      null
    else
      let
        selectedPackages = packages.selectPackagesForConfig {
          inherit uvLock;
          config = forgeConfig;
        };
        sources = builtins.listToAttrs (map (mkSourceEntry fetchTree forgeConfig.hosts) selectedPackages);
      in
      final: prev: lib.mapAttrs (overridePackageSrc prev) sources;
in
{
  inherit
    mkOverlay
    ;

  internal = {
    inherit
      failPackage
      mkFetchTreeInput
      mkSourceValue
      normalizePackageName
      ;
    inherit (configLib) validateConfig;
    inherit (forgeUrl) parseForgeUrl;
    inherit (gitSource) parseGitSource;
    inherit (packages) selectAutoPackages selectPackages;

    failPkg = failPackage;
    selectConfiguredPackages = packages.selectPackagesForConfig;
  };
}
