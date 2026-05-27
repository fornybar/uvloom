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
    context: raw:
    let
      params = map (parseQueryParam context) (lib.splitString "&" raw);
      names = map (param: param.name) params;
    in
    if builtins.length names != builtins.length (lib.unique names) then
      fail where "duplicate git source ${context} parameters are unsupported"
    else
      builtins.listToAttrs params;

  decodePercent =
    context: raw:
    let
      validPercentEncoded = builtins.match "([^%]|%[0-9A-Fa-f][0-9A-Fa-f])*" raw != null;

      decodeEscape =
        escape:
        let
          code = builtins.substring 1 2 escape;
        in
        builtins.fromJSON ''"\u00${code}"'';

      decodeChunk = chunk: if builtins.isList chunk then decodeEscape (builtins.head chunk) else chunk;
    in
    if validPercentEncoded then
      lib.concatMapStrings decodeChunk (builtins.split "(%[0-9A-Fa-f][0-9A-Fa-f])" raw)
    else
      fail where "malformed git source ${context}: invalid percent-encoding in `${raw}`";

  decodeParams = context: params: lib.mapAttrs (_name: value: decodePercent context value) params;

  parseParams =
    context: allowed: raw:
    ensureOnlyKeys context allowed (decodeParams context (parseQuery context raw));

  queryParamNames = [
    "rev"
    "branch"
    "tag"
    "subdirectory"
    "lfs"
    "submodules"
  ];

  fragmentParamNames = [
    "subdirectory"
    "lfs"
    "submodules"
    "egg"
  ];

  ensureOnlyKeys =
    context: allowed: params:
    let
      unknown = lib.filterAttrs (name: _value: !(builtins.elem name allowed)) params;
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
    else
      subdirectory;

  selectOptional =
    name: left: right:
    if left != null && right != null && left != right then
      fail where "git source has conflicting query and fragment ${name} values"
    else if left != null then
      left
    else
      right;

  isLockedRev = rev: builtins.match "[0-9a-fA-F]{7,40}" rev != null;

  requestedRefEntries = params: [
    {
      type = "rev";
      value = params.rev or null;
    }
    {
      type = "branch";
      value = params.branch or null;
    }
    {
      type = "tag";
      value = params.tag or null;
    }
  ];

  selectRequestedRef =
    params:
    let
      present = lib.filter (entry: entry.value != null) (requestedRefEntries params);
    in
    if builtins.length present > 1 then
      fail where "git source has multiple requested ref parameters; choose one of rev, branch, tag"
    else if present == [ ] then
      null
    else
      builtins.head present;

  selectLockedRev =
    fragmentRev: requestedRef:
    if fragmentRev != null then
      fragmentRev
    else if requestedRef != null && requestedRef.type == "rev" && isLockedRev requestedRef.value then
      requestedRef.value
    else
      null;
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
      queryRaw = if match == null then null else builtins.elemAt match 2;
      fragmentRaw = if match == null then null else builtins.elemAt match 4;

      queryParams = if queryRaw == null then { } else parseParams "query" queryParamNames queryRaw;

      fragmentParams =
        if fragmentRaw != null && lib.hasInfix "=" fragmentRaw then
          parseParams "fragment" fragmentParamNames fragmentRaw
        else
          { };

      requestedRef = selectRequestedRef queryParams;

      lockedRevFromFragment =
        if fragmentRaw != null && fragmentParams == { } then decodePercent "fragment" fragmentRaw else null;
      lockedRev = selectLockedRev lockedRevFromFragment requestedRef;

      subdirectory = selectOptional "subdirectory" (queryParams.subdirectory or null) (
        fragmentParams.subdirectory or null
      );
    in
    if match == null then
      if !(lib.hasInfix "#" sourceGit) && !(lib.hasInfix "rev=" sourceGit) then
        fail where "git source is missing locked rev"
      else
        fail where "malformed git source `${sourceGit}`"
    else if queryParams ? lfs || fragmentParams ? lfs then
      fail where "git source with lfs is unsupported in forgeFetch"
    else if queryParams ? submodules || fragmentParams ? submodules then
      fail where "git source with submodules is unsupported in forgeFetch"
    else if fragmentParams ? egg then
      fail where "git source fragment parameter `egg` is unsupported in forgeFetch"
    else if requestedRef != null && requestedRef.value == "" then
      fail where "git source requested ref must not be empty"
    else if lockedRev == null || lockedRev == "" then
      fail where "git source is missing locked rev"
    else if !isLockedRev lockedRev then
      fail where "git source locked rev must be a git commit hash"
    else
      {
        url = builtins.elemAt match 0;
        rev = lockedRev;
      }
      // lib.optionalAttrs (subdirectory != null) {
        subdirectory = validateSubdirectory subdirectory;
      };
}
