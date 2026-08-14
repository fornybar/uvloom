{
  pkgs,
  self,
  system,
}:
{
  default = pkgs.mkShell {
    packages = [
      self.formatter.${system}
      pkgs.git-cliff
      pkgs.just
      pkgs.nixdoc
      pkgs.pandoc
      pkgs.python3
    ];
  };

  release = pkgs.mkShell {
    packages = [
      pkgs.gitMinimal
      pkgs.git-cliff
    ];
  };
}
