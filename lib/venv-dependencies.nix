{
  lib,
  uv2nix,
  pyproject-nix,
  fail,
}:

let
  pep508ForInterpreter =
    interpreter: environ:
    pyproject-nix.lib.pep508.setEnviron (pyproject-nix.lib.pep508.mkEnviron interpreter) environ;

  addDependencyGroups =
    acc: name: groups:
    acc // { ${name} = lib.unique ((acc.${name} or [ ]) ++ groups); };

  dependencyNamesForVirtualPackage =
    pkg: groups:
    lib.unique (
      (map (dep: dep.name) pkg.dependencies)
      ++ lib.concatMap (
        group:
        (map (dep: dep.name) (pkg.optional-dependencies.${group} or [ ]))
        ++ (map (dep: dep.name) (pkg.dev-dependencies.${group} or [ ]))
      ) groups
    );

  activeVirtualPackages =
    {
      uvLock,
      interpreter,
      environ,
    }:
    if uvLock == null then
      [ ]
    else
      lib.pipe (uvLock.package or [ ]) [
        (map (uv2nix.lib.lock1.filterPackage (pep508ForInterpreter interpreter environ)))
        (lib.filter (pkg: pkg.source ? virtual))
      ];

  virtualPackagesByName = args: lib.groupBy (pkg: pkg.name) (activeVirtualPackages args);

  getVirtualPackage =
    byName: name:
    if !(byName ? ${name}) then
      null
    else if builtins.length byName.${name} == 1 then
      builtins.head byName.${name}
    else
      fail "venv" "virtual package ${name} has multiple active lock entries";
in
{
  # uv virtual roots (`source = { virtual = "."; }`) are dependency manifests,
  # not installable distributions. pyproject-nix's mkVirtualEnv installs every
  # key in the dependency attrset, so feeding it `{ root = [ ]; }` tries to build
  # root as a wheel. Rewrite virtual roots to their locked dependency names.
  resolve =
    {
      dependencies,
      uvLock ? null,
      interpreter,
      environ ? { },
    }:
    let
      virtualPackages = virtualPackagesByName {
        inherit uvLock interpreter environ;
      };
    in
    lib.foldlAttrs (
      acc: name: groups:
      let
        virtualPackage = getVirtualPackage virtualPackages name;
      in
      if virtualPackage != null then
        builtins.foldl' (acc': depName: addDependencyGroups acc' depName [ ]) acc (
          dependencyNamesForVirtualPackage virtualPackage groups
        )
      else
        addDependencyGroups acc name groups
    ) { } dependencies;
}
