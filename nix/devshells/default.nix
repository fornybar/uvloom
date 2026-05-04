{
  pkgs,
  self,
  system,
}:
{
  default = pkgs.mkShell {
    packages = [
      self.formatter.${system}
      pkgs.just
      pkgs.nixdoc
      pkgs.pandoc
      pkgs.python3
    ];
  };
}
