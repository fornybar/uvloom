{
  lib,
  fail,
  where,
  builtInHosts,
}:

let
  parseForgePath =
    hosts: host: path:
    let
      lowerHost = lib.toLower host;
      type =
        builtInHosts.${lowerHost} or hosts.${lowerHost}
          or (fail where "unsupported git host `${host}`; configure it with forgeFetch.hosts.\"${lowerHost}\" = \"github\" or \"gitlab\"");
      parts = lib.splitString "/" path;
      repo = lib.last parts;
      owner = lib.concatStringsSep "/" (lib.init parts);
    in
    if builtins.length parts < 2 then
      fail where "git forge URL must include owner and repo"
    else if lib.any (part: part == "") parts then
      fail where "git forge path must not contain empty segments"
    else if type == "github" && builtins.length parts != 2 then
      fail where "nested github forge paths are unsupported"
    else if lib.removeSuffix ".git" repo == "" then
      fail where "git forge repo must not be empty"
    else
      {
        inherit type owner;
        host = lowerHost;
        repo = lib.removeSuffix ".git" repo;
      };
in
{
  parseForgeUrl =
    rawUrl: hosts:
    let
      url = lib.removePrefix "git+" rawUrl;
      https = builtins.match "https?://([^/]+)/([^?#]+)" url;
      ssh = builtins.match "ssh://git@([^/]+)/([^?#]+)" url;
      scp = builtins.match "git@([^:]+):([^?#]+)" url;
    in
    if https != null then
      parseForgePath hosts (builtins.elemAt https 0) (builtins.elemAt https 1)
    else if ssh != null then
      parseForgePath hosts (builtins.elemAt ssh 0) (builtins.elemAt ssh 1)
    else if scp != null then
      parseForgePath hosts (builtins.elemAt scp 0) (builtins.elemAt scp 1)
    else
      fail where "malformed or unsupported git URL `${rawUrl}`";
}
