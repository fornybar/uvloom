{
  lib,
  fail,
  where,
}:

let
  inherit (builtins) elemAt length;

  parseQueryParam =
    query: part:
    let
      pieces = lib.splitString "=" part;
    in
    if length pieces == 2 then
      lib.nameValuePair (elemAt pieces 0) (elemAt pieces 1)
    else
      fail where "malformed git source query `${query}`";

  parseQuery = query: lib.listToAttrs (map (parseQueryParam query) (lib.splitString "&" query));
in
{
  parseGitSource =
    sourceGit:
    let
      match = builtins.match "([^#?]+)(\\?([^#?]+))?#([^#]+)" sourceGit;
      query = if match == null || elemAt match 2 == null then { } else parseQuery (elemAt match 2);
    in
    if match == null then
      if !(lib.hasInfix "#" sourceGit) || lib.hasSuffix "#" sourceGit then
        fail where "git source is missing locked rev fragment"
      else
        fail where "malformed git source `${sourceGit}`"
    else if query != { } then
      fail where "git source query parameters are unsupported in forgeFetch MVP"
    else
      {
        url = elemAt match 0;
        rev = elemAt match 3;
      };
}
