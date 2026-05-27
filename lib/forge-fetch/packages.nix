{
  lib,
  fail,
  where,
  failPackage,
  normalizePackageName,
}:

let
  inherit (builtins) filter head length;

  mkSelectedPackageEntry =
    requested: pkg:
    let
      sourceGit = pkg.source.git or null;
    in
    if sourceGit == null then
      failPackage requested "locked source is not git"
    else if sourceGit == "" then
      failPackage requested "locked git source is empty"
    else
      {
        attrName = pkg.name;
        requestedName = requested;
        inherit sourceGit;
      };

  selectRequestedPackage =
    uvLock: requested:
    let
      wanted = normalizePackageName requested;
      matches = filter (pkg: normalizePackageName (pkg.name or "") == wanted) (uvLock.package or [ ]);
    in
    if matches == [ ] then
      failPackage requested "not found in uv.lock"
    else if length matches > 1 then
      failPackage requested "multiple matching entries in uv.lock"
    else
      mkSelectedPackageEntry requested (head matches);

  mkAutoPackageEntry =
    pkg:
    if !(pkg ? name) || pkg.name == "" then
      fail where "auto found Git package without name in uv.lock"
    else
      mkSelectedPackageEntry pkg.name pkg;

  ensureUniqueSelectedAttrNames =
    selected:
    let
      names = map (entry: normalizePackageName entry.attrName) selected;
    in
    if length (lib.unique names) != length names then
      fail where "auto found multiple Git package entries with same normalized name"
    else
      selected;

  selectPackages = { uvLock, packages }: map (selectRequestedPackage uvLock) packages;

  selectAutoPackages =
    uvLock:
    lib.pipe (uvLock.package or [ ]) [
      (filter (pkg: pkg ? source && pkg.source ? git))
      (map mkAutoPackageEntry)
      ensureUniqueSelectedAttrNames
    ];

  selectPackagesForConfig =
    { uvLock, config }:
    if config.mode == "auto" then
      selectAutoPackages uvLock
    else
      selectPackages {
        inherit uvLock;
        packages = config.packages;
      };
in
{
  inherit
    selectAutoPackages
    selectPackages
    selectPackagesForConfig
    ;
}
