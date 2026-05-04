{
  pkgs,
}:
pkgs.writeShellApplication {
  name = "nixfmt";
  runtimeInputs = [
    pkgs.git
    pkgs.nixfmt
  ];
  text = ''
    if [ "$#" -eq 0 ]; then
      mapfile -t nix_files < <(git ls-files '*.nix')
      set -- "''${nix_files[@]}"
    fi

    exec nixfmt "$@"
  '';
}
