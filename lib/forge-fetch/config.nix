{
  lib,
  fail,
  where,
  configTypeError,
  builtInHosts,
}:

let
  inherit (builtins)
    all
    attrNames
    isAttrs
    isList
    isString
    removeAttrs
    ;

  validatePackages =
    packages:
    if !isList packages then
      fail where configTypeError
    else if packages == [ ] then
      fail where "packages must be non-empty"
    else if !(all isString packages) then
      fail where "packages entries must be strings"
    else
      packages;

  normalizeConfig =
    config:
    if config == null then
      null
    else if config == "auto" then
      {
        packages = "auto";
        hosts = { };
      }
    else if isList config then
      {
        packages = config;
        hosts = { };
      }
    else if isAttrs config then
      let
        unknownFields = attrNames (
          removeAttrs config [
            "packages"
            "hosts"
          ]
        );
      in
      if !(config ? packages) then
        fail where "packages is required"
      else if unknownFields != [ ] then
        fail where "unknown fields reserved for future versions: ${lib.concatStringsSep ", " unknownFields}"
      else
        {
          packages = config.packages;
          hosts = config.hosts or { };
        }
    else if isString config then
      fail where "unknown string mode `${config}`; supported string mode: auto"
    else
      fail where configTypeError;

  normalizeHosts =
    hosts:
    let
      names = attrNames hosts;
    in
    map (original: {
      inherit original;
      lower = lib.toLower original;
      value = hosts.${original};
    }) names;

  validateHosts =
    hosts:
    if !isAttrs hosts then
      fail where "hosts must be an attribute set"
    else
      let
        records = normalizeHosts hosts;
        normalizedNames = map (record: record.lower) records;
        malformed = lib.filter (
          record:
          builtins.match "[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?(\\.[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?)*" record.original
          == null
        ) records;
        invalidValues = lib.filter (
          record:
          !(isString record.value)
          || !(builtins.elem record.value [
            "github"
            "gitlab"
          ])
        ) records;
        conflictingBuiltIns = lib.filter (
          record: builtins.hasAttr record.lower builtInHosts && record.value != builtInHosts.${record.lower}
        ) records;
      in
      if malformed != [ ] then
        fail where "hosts contains malformed hostname `${(builtins.head malformed).original}`"
      else if builtins.length (lib.unique normalizedNames) != builtins.length normalizedNames then
        fail where "hosts contains case-colliding hostnames"
      else if invalidValues != [ ] then
        fail where "hosts values must be `github` or `gitlab`"
      else if conflictingBuiltIns != [ ] then
        fail where "hosts cannot reclassify built-in host `${(builtins.head conflictingBuiltIns).original}`"
      else
        builtins.listToAttrs (
          map (record: {
            name = record.lower;
            value = record.value;
          }) records
        );

  renderConfig =
    config:
    if config.packages == "auto" then
      {
        mode = "auto";
        packages = null;
        hosts = validateHosts config.hosts;
      }
    else
      {
        mode = "explicit";
        packages = validatePackages config.packages;
        hosts = validateHosts config.hosts;
      };
in
{
  validateConfig =
    config:
    let
      normalized = normalizeConfig config;
    in
    if normalized == null then null else renderConfig normalized;
}
