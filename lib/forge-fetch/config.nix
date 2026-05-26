{
  lib,
  fail,
  where,
  configTypeError,
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

  mkExplicitConfig = packages: {
    mode = "explicit";
    packages = validatePackages packages;
  };
in
{
  validateConfig =
    config:
    if config == null then
      null
    else if config == "auto" then
      {
        mode = "auto";
        packages = null;
      }
    else if isList config then
      mkExplicitConfig config
    else if isAttrs config then
      let
        unknownFields = attrNames (removeAttrs config [ "packages" ]);
      in
      if !(config ? packages) then
        fail where "packages is required"
      else if unknownFields != [ ] then
        fail where "unknown fields reserved for future versions: ${lib.concatStringsSep ", " unknownFields}"
      else
        mkExplicitConfig config.packages
    else if isString config then
      fail where "unknown string mode `${config}`; supported string mode: auto"
    else
      fail where configTypeError;
}
