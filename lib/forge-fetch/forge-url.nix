{
  lib,
  fail,
  where,
}:

let
  inherit (builtins) attrNames elemAt;

  forgeTypeByHost = {
    "github.com" = "github";
    "gitlab.com" = "gitlab";
  };

  mkForgeInput =
    host: owner: repo:
    let
      lowerHost = lib.toLower host;
      supportedHosts = attrNames forgeTypeByHost;
    in
    {
      type =
        forgeTypeByHost.${lowerHost}
          or (fail where "unsupported git host `${host}`; supported hosts: ${lib.concatStringsSep ", " supportedHosts}");
      inherit owner;
      repo = lib.removeSuffix ".git" repo;
    };

  forgeInputFromCapture = match: mkForgeInput (elemAt match 0) (elemAt match 1) (elemAt match 2);
in
{
  parseForgeUrl =
    rawUrl:
    let
      url = lib.removePrefix "git+" rawUrl;
      https = builtins.match "https?://([^/]+)/([^/]+)/([^/?#]+)(/.*)?" url;
      ssh = builtins.match "ssh://git@([^/]+)/([^/]+)/([^/?#]+)" url;
      scp = builtins.match "git@([^:]+):([^/]+)/([^/?#]+)" url;
    in
    if https != null then
      if elemAt https 3 != null then
        fail where "nested git forge paths are unsupported in MVP"
      else
        forgeInputFromCapture https
    else if ssh != null then
      forgeInputFromCapture ssh
    else if scp != null then
      forgeInputFromCapture scp
    else
      fail where "malformed or unsupported git URL `${rawUrl}`";
}
