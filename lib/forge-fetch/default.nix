{
  lib,
  pyproject-nix,
  fail,
}:

let
  where = "forgeFetch";
  configTypeError = "must be null, `auto`, a package-name list, or an attribute set with `packages`";

  failPackage = name: message: fail where "package `${name}`: ${message}";

  inherit (pyproject-nix.lib.pypa) normalizePackageName;

  configLib = import ./config.nix {
    inherit
      lib
      fail
      where
      configTypeError
      ;
  };

  gitSource = import ./git-source.nix {
    inherit lib fail where;
  };

  forgeUrl = import ./forge-url.nix {
    inherit lib fail where;
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
      forgeInput = forgeUrl.parseForgeUrl parsedGit.url;
    in
    {
      inherit (forgeInput) type owner repo;
      inherit (parsedGit) rev;
    };

  mkSourceEntry = entry: {
    name = entry.attrName;
    value = builtins.addErrorContext "while fetching forgeFetch package `${entry.attrName}`" (
      let
        parsedGit = gitSource.parseGitSource entry.sourceGit;
        fetched = builtins.fetchTree (mkFetchTreeInput entry);
      in
      if parsedGit ? subdirectory then fetched + "/${parsedGit.subdirectory}" else fetched
    );
  };

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
        sources = builtins.listToAttrs (map mkSourceEntry selectedPackages);
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
