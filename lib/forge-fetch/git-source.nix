{
  lib,
  fail,
  where,
}:

let
  parseQueryParam =
    context: part:
    let
      match = builtins.match "([^=]+)=(.*)" part;
    in
    if match != null then
      lib.nameValuePair (builtins.elemAt match 0) (builtins.elemAt match 1)
    else
      fail where "malformed git source ${context} `${part}`";

  parseQuery =
    context: query:
    let
      params = map (parseQueryParam context) (lib.splitString "&" query);
      names = map (param: param.name) params;
    in
    if builtins.length names != builtins.length (lib.unique names) then
      fail where "duplicate git source ${context} parameters are unsupported"
    else
      builtins.listToAttrs params;

  supportedParams = [
    "rev"
    "subdirectory"
  ];

  rejectUnknownParams =
    context: params:
    let
      unknown = lib.filterAttrs (name: _value: !(builtins.elem name supportedParams)) params;
    in
    if unknown != { } then
      fail where "unsupported git source ${context} parameters: ${lib.concatStringsSep ", " (builtins.attrNames unknown)}"
    else
      params;

  validateSubdirectory =
    subdirectory:
    let
      parts = lib.splitString "/" subdirectory;
      invalidPart = part: part == "" || part == "." || part == "..";
    in
    if subdirectory == "" then
      fail where "git source subdirectory must not be empty"
    else if lib.hasPrefix "/" subdirectory then
      fail where "git source subdirectory must be relative"
    else if lib.any invalidPart parts then
      fail where "git source subdirectory must not contain empty, `.`, or `..` path segments"
    else if lib.hasInfix "%" subdirectory then
      fail where "percent-encoded git source subdirectories are unsupported"
    else
      subdirectory;

  selectParam =
    name: queryValue: fragmentValue:
    if queryValue != null && fragmentValue != null && queryValue != fragmentValue then
      fail where "git source has conflicting query and fragment ${name} values"
    else if queryValue != null then
      queryValue
    else
      fragmentValue;
in
{
  parseGitSource =
    sourceGit:
    let
      # Python VCS direct references are specified by PEP 610 and pip's VCS URL fragments.
      # uv stores equivalent Git source fields and may encode them in uv.lock source.git.
      # https://peps.python.org/pep-0610/
      # https://pip.pypa.io/en/stable/topics/vcs-support/#url-fragments
      # https://docs.astral.sh/uv/concepts/projects/dependencies/#git
      match = builtins.match "([^#?]+)(\\?([^#?]+))?(#([^#]+))?" sourceGit;

      url = builtins.elemAt match 0;
      queryString = builtins.elemAt match 2;
      fragment = builtins.elemAt match 4;

      queryParams =
        if queryString == null then { } else rejectUnknownParams "query" (parseQuery "query" queryString);
      fragmentParams =
        if fragment != null && lib.hasInfix "=" fragment then
          rejectUnknownParams "fragment" (parseQuery "fragment" fragment)
        else
          { };

      queryRev = queryParams.rev or null;
      fragmentRev = if fragment != null && fragmentParams == { } then fragment else null;
      rev = selectParam "rev" queryRev fragmentRev;

      subdirectory = selectParam "subdirectory" (queryParams.subdirectory or null) (fragmentParams.subdirectory or null);
    in
    if match == null then
      if !(lib.hasInfix "#" sourceGit) && !(lib.hasInfix "rev=" sourceGit) then
        fail where "git source is missing locked rev"
      else
        fail where "malformed git source `${sourceGit}`"
    else if rev == null || rev == "" then
      fail where "git source is missing locked rev"
    else
      {
        inherit url rev;
      }
      // lib.optionalAttrs (subdirectory != null) {
        subdirectory = validateSubdirectory subdirectory;
      };
}
