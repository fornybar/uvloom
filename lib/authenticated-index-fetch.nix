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

  normalizeHash =
    where: hash:
    let
      converted = builtins.tryEval (
        if !builtins.isString hash then
          throw "hash is not a string"
        else
          builtins.convertHash {
            inherit hash;
            toHashFormat = "sri";
          }
      );
    in
    if !converted.success || !lib.hasPrefix "sha256-" converted.value then
      fail where "selected registry artifact hash must be a valid SHA-256 hash"
    else
      converted.value;

  artifactFilename =
    where: url:
    let
      withoutFragment = builtins.head (lib.splitString "#" url);
      withoutQuery = builtins.head (lib.splitString "?" withoutFragment);
      filename = lib.last (lib.splitString "/" withoutQuery);
    in
    if filename == "" then fail where "selected registry artifact URL must name a file" else filename;

  selectedArtifacts =
    {
      lock,
      registries,
      authenticatedOnly,
    }:
    let
      selectedPackage =
        package:
        let
          source = package.source or { };
        in
        source ? registry
        && builtins.isString source.registry
        && (
          !authenticatedOnly
          || builtins.elem (normalizeRegistry "uv lock registry" source.registry) registries
        );
    in
    lib.pipe lock.package [
      (builtins.filter selectedPackage)
      (lib.concatMap (package: (package.wheels or [ ]) ++ lib.optional (package ? sdist) package.sdist))
    ];

  mkArtifactMetadata =
    {
      lock,
      registries,
      authenticatedOnly,
    }:
    let
      addArtifact =
        metadata: artifact:
        if !(builtins.isAttrs artifact) || !(artifact ? url) then
          metadata
        else if !(artifact ? hash) then
          fail "authenticatedIndexFetch" "selected registry artifact must provide a hash"
        else
          let
            url = validateHTTPS "authenticatedIndexFetch" artifact.url;
            hash = normalizeHash "authenticatedIndexFetch" artifact.hash;
            filename = artifactFilename "authenticatedIndexFetch" url;
            existing = metadata.${url} or null;
          in
          if existing == null then
            metadata
            // {
              ${url} = { inherit url hash filename; };
            }
          else if existing.hash != hash then
            fail "authenticatedIndexFetch" "selected registry URL `${url}` has conflicting locked hashes"
          else
            metadata;
    in
    lib.foldl' addArtifact { } (selectedArtifacts {
      inherit lock registries authenticatedOnly;
    });

  mkOverlay =
    {
      lock,
      uvIndexes ? [ ],
      authenticatedOnly ? true,
      evaluatorFetch ? builtins.fetchurl,
    }:
    let
      artifactMetadata = mkArtifactMetadata {
        inherit lock authenticatedOnly;
        registries = authenticatedRegistries uvIndexes;
      };
    in
    _final: prev: {
      fetchurl =
        args:
        let
          artifact =
            if builtins.isAttrs args && args ? url then artifactMetadata.${args.url} or null else null;
        in
        if artifact == null then
          prev.fetchurl args
        else
          evaluatorFetch {
            url = artifact.url;
            sha256 = artifact.hash;
            name = args.name or artifact.filename;
          };
    };
in
{
  inherit mkOverlay;
}
