{
  lib,
  fail,
}:

let
  validateHTTPS =
    where: url:
    let
      authority =
        if builtins.isString url then
          builtins.head (lib.splitString "/" (lib.removePrefix "https://" url))
        else
          "";
    in
    if
      !builtins.isString url
      || !lib.hasPrefix "https://" url
      || authority == ""
      || lib.hasInfix "@" authority
    then
      fail where "URL must use HTTPS and contain no userinfo"
    else
      url;

  normalizeRegistry =
    where: url:
    let
      checkedURL = validateHTTPS where url;
    in
    if lib.hasInfix "?" checkedURL || lib.hasInfix "#" checkedURL then
      fail where "URL must not contain a query or fragment"
    else
      lib.removeSuffix "/" checkedURL;

  authenticatedRegistries =
    uvIndexes:
    map
      (
        index:
        if !builtins.isAttrs index || !builtins.isString (index.url or null) then
          fail "authenticated uv index" "url must be a string"
        else
          normalizeRegistry "authenticated uv index" index.url
      )
      (
        builtins.filter (
          index: builtins.isAttrs index && (index.authenticate or "auto") == "always"
        ) uvIndexes
      );

  mkArtifactURLs =
    {
      lock,
      registries,
      authenticatedOnly,
    }:
    let
      selectedPackage =
        package:
        package.source ? registry
        && builtins.isString package.source.registry
        && (
          !authenticatedOnly
          || builtins.elem (normalizeRegistry "uv lock registry" package.source.registry) registries
        );
      packages = builtins.filter selectedPackage lock.package;
      artifacts = lib.concatMap (
        package: (package.wheels or [ ]) ++ lib.optional ((package.sdist or { }) != { }) package.sdist
      ) packages;
      artifactURL =
        artifact:
        if !(artifact ? url) then
          null
        else if !(artifact ? hash) then
          fail "authenticatedIndexFetch" "selected registry artifact must provide a hash"
        else
          validateHTTPS "authenticatedIndexFetch" artifact.url;
    in
    lib.unique (builtins.filter (url: url != null) (map artifactURL artifacts));

  mkOverlay =
    {
      lock,
      uvIndexes ? [ ],
      authenticatedOnly ? true,
      evaluatorFetch ? builtins.fetchurl,
    }:
    let
      artifactURLs = mkArtifactURLs {
        inherit lock authenticatedOnly;
        registries = authenticatedRegistries uvIndexes;
      };
    in
    final: prev: {
      fetchurl =
        args:
        if builtins.isAttrs args && args ? url && builtins.elem args.url artifactURLs then
          evaluatorFetch (
            {
              url = args.url;
              sha256 =
                if args ? hash then
                  args.hash
                else
                  fail "authenticatedIndexFetch" "selected registry fetch must provide a hash";
            }
            // lib.optionalAttrs (args ? name) {
              name = args.name;
            }
          )
        else
          prev.fetchurl args;
    };
in
{
  inherit mkOverlay;
}
