{ lib, fail }:

let
  showCandidates = candidates: lib.concatStringsSep ", " candidates;

  inferLocalPackage =
    where: candidates: requestedPackage:
    if requestedPackage != null then
      requestedPackage
    else if candidates == [ ] then
      fail where "could not infer package; no local packages found"
    else if builtins.length candidates == 1 then
      builtins.head candidates
    else
      fail where "could not infer package; candidates: ${showCandidates candidates}";

  requireLocalPackage =
    where: candidates: packageName:
    if builtins.elem packageName candidates then
      packageName
    else
      fail where "package ${packageName} not found; local packages: ${showCandidates candidates}";

  requirePythonSetPackage =
    where: candidates: pythonSet: packageName:
    if pythonSet ? ${packageName} then
      packageName
    else
      fail where "package ${packageName} not found in pythonSet; local packages: ${showCandidates candidates}";

  resolveLocalPackage =
    where: candidates: pythonSet: requestedPackage:
    requirePythonSetPackage where candidates pythonSet (
      requireLocalPackage where candidates (inferLocalPackage where candidates requestedPackage)
    );
in
{
  localNames = workspace: builtins.attrNames workspace.deps.default;

  inherit
    inferLocalPackage
    requireLocalPackage
    requirePythonSetPackage
    resolveLocalPackage
    ;

}
