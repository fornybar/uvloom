{
  lib,
  fail,
  fetch ? builtins.fetchurl,
}:

let
  defaultFetch = fetch;

  validateHTTPS =
    where: url:
    let
      authority = builtins.head (lib.splitString "/" (lib.removePrefix "https://" url));
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

  mkOverlay =
    {
      lock,
      uvIndexes ? [ ],
      authenticatedOnly ? true,
      fetch ? defaultFetch,
    }:
    let
      registries = authenticatedRegistries uvIndexes;
      selected =
        package:
        !authenticatedOnly
        || (
          package.source ? registry
          && builtins.isString package.source.registry
          && builtins.elem (normalizeRegistry "uv lock registry" package.source.registry) registries
        );
      packageNames = lib.unique (map (package: package.name) (builtins.filter selected lock.package));
    in
    final: prev:
    lib.genAttrs (builtins.filter (name: prev ? ${name}) packageNames) (
      name:
      let
        old = prev.${name};
        source = if old ? src && builtins.isAttrs old.src then old.src else null;
      in
      if source == null then
        old
      else if !(source ? url && source ? hash && source ? name) then
        fail "authenticatedIndexFetch.${name}" "selected registry source must provide URL, hash, and name"
      else
        old
        // {
          src = fetch {
            url = validateHTTPS "authenticatedIndexFetch.${name}" source.url;
            sha256 = source.hash;
            inherit (source) name;
          };
        }
    );
in
{
  inherit mkOverlay;
}
