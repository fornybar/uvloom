{
  pkgs,
  uvloom,
  pyproject-nix,
}:

let
  fails = expr: !(builtins.tryEval (builtins.deepSeq expr true)).success;

  project = uvloom.lib.project.load {
    root = ./fixtures/smiley-plot;
  };

  multiProject = uvloom.lib.project.load {
    root = ./fixtures/multi-package;
  };

  badPythonProject = uvloom.lib.project.load {
    root = ./fixtures/bad-python;
  };

  scope = project.forPython {
    inherit pkgs;
    interpreter = pkgs.python312;
  };

  forgeFetchLib = import ../lib/forge-fetch {
    inherit pyproject-nix;
    inherit (pkgs) lib;
    fail = where: message: throw "uvloom.${where}: ${message}";
  };

  multiScope = multiProject.forPython {
    inherit pkgs;
    interpreter = pkgs.python312;
  };

  script = uvloom.lib.inline.load {
    path = ./fixtures/scripts/example.py;
  };
in
assert fails (
  (project.forPython {
    inherit pkgs;
    interpreter = pkgs.python312;
    sourcePreference = "bad";
  }).pythonSet
);
assert fails (
  (project.forPython {
    inherit pkgs;
    interpreter = pkgs.python312;
    fetcher = "bad";
  }).pythonSet
);
assert fails (
  (project.forPython {
    inherit pkgs;
    interpreter = pkgs.python312;
    overlays = { };
  }).pythonSet
);
assert fails (
  (project.forPython {
    inherit pkgs;
    interpreter = pkgs.python312;
    forgeFetch = true;
  }).pythonSet
);
assert fails (
  (project.forPython {
    inherit pkgs;
    interpreter = pkgs.python312;
    forgeFetch = "all";
  }).pythonSet
);
assert fails (
  (project.forPython {
    inherit pkgs;
    interpreter = pkgs.python312;
    forgeFetch = { };
  }).pythonSet
);
assert fails (
  (
    (uvloom.lib.project.load {
      root = ./fixtures/smiley-plot;
      forgeFetch = [ ];
    }).forPython
    {
      inherit pkgs;
      interpreter = pkgs.python312;
    }
  ).pythonSet
);
assert fails (
  (project.forPython {
    inherit pkgs;
    interpreter = pkgs.python312;
    forgeFetch.packages = [ ];
  }).pythonSet
);
assert fails (
  (project.forPython {
    inherit pkgs;
    interpreter = pkgs.python312;
    forgeFetch.packages = [ 1 ];
  }).pythonSet
);
assert fails (
  (project.forPython {
    inherit pkgs;
    interpreter = pkgs.python312;
    forgeFetch = {
      packages = [ "demo" ];
      extra = true;
    };
  }).pythonSet
);
assert fails (
  forgeFetchLib.internal.selectAutoPackages {
    package = [
      {
        name = "dup";
        source.git = "https://github.com/o/r.git#1";
      }
      {
        name = "Dup";
        source.git = "https://github.com/o/r.git#2";
      }
    ];
  }
);
assert fails (
  forgeFetchLib.internal.selectPackages {
    packages = [ "missing" ];
    uvLock.package = [ ];
  }
);
assert fails (
  forgeFetchLib.internal.selectPackages {
    packages = [ "dup" ];
    uvLock.package = [
      {
        name = "dup";
        source.git = "https://github.com/o/r.git#1";
      }
      {
        name = "dup";
        source.git = "https://github.com/o/r.git#2";
      }
    ];
  }
);
assert fails (
  forgeFetchLib.internal.selectPackages {
    packages = [ "plain" ];
    uvLock.package = [
      {
        name = "plain";
        source.registry = "https://pypi.org/simple";
      }
    ];
  }
);
assert fails (forgeFetchLib.internal.parseGitSource "https://github.com/o/r.git");
assert fails (forgeFetchLib.internal.parseGitSource "https://github.com/o/r.git?branch=main");
assert fails (forgeFetchLib.internal.parseGitSource "https://github.com/o/r.git?tag=v1.2.3");
assert fails (forgeFetchLib.internal.parseGitSource "https://github.com/o/r.git?rev=main");
assert fails (
  forgeFetchLib.internal.parseGitSource "https://github.com/o/r.git?rev=main&tag=v1.0.0#0123456789abcdef0123456789abcdef01234567"
);
assert fails (forgeFetchLib.internal.parseGitSource "https://github.com/o/r.git?rev=one#two");
assert fails (forgeFetchLib.internal.parseGitSource "https://github.com/o/r.git?rev=one&rev=one");
assert fails (
  forgeFetchLib.internal.parseGitSource "https://github.com/o/r.git?foo=bar#0123456789abcdef0123456789abcdef01234567"
);
assert fails (
  forgeFetchLib.internal.parseGitSource "https://github.com/o/r.git?tag=pyshop-binaries%2"
);
assert fails (
  forgeFetchLib.internal.parseGitSource "https://github.com/o/r.git?subdirectory=#0123456789abcdef0123456789abcdef01234567"
);
assert fails (
  forgeFetchLib.internal.parseGitSource "https://github.com/o/r.git?subdirectory=/pkg#0123456789abcdef0123456789abcdef01234567"
);
assert fails (
  forgeFetchLib.internal.parseGitSource "https://github.com/o/r.git?subdirectory=../pkg#0123456789abcdef0123456789abcdef01234567"
);
assert fails (
  forgeFetchLib.internal.parseGitSource "https://github.com/o/r.git?subdirectory=pkg//inner#0123456789abcdef0123456789abcdef01234567"
);
assert fails (
  forgeFetchLib.internal.parseGitSource "https://github.com/o/r.git?subdirectory=pkg%2F..%2Finner#0123456789abcdef0123456789abcdef01234567"
);
assert fails (
  forgeFetchLib.internal.parseGitSource "https://github.com/o/r.git?lfs=true#0123456789abcdef0123456789abcdef01234567"
);
assert fails (
  forgeFetchLib.internal.parseGitSource "https://github.com/o/r.git?submodules=true#0123456789abcdef0123456789abcdef01234567"
);
assert fails (
  forgeFetchLib.internal.parseGitSource "https://github.com/o/r.git?rev=0123456789abcdef0123456789abcdef01234567#egg=pkg&subdirectory=pkg"
);
assert fails (
  forgeFetchLib.internal.parseGitSource "https://github.com/o/r.git?subdirectory=one&rev=0123456789abcdef0123456789abcdef01234567#subdirectory=two"
);
assert fails (forgeFetchLib.internal.parseForgeUrl "https://example.com/o/r.git");
assert fails (forgeFetchLib.internal.parseForgeUrl "https://github.com/group/subgroup/repo.git");
assert fails (forgeFetchLib.internal.parseForgeUrl "https://gitlab.com/group//repo.git");
assert fails (
  scope.venv {
    name = "bad-editable-env";
    editable.root = ./fixtures/smiley-plot;
  }
);
assert fails (
  (badPythonProject.forPython {
    inherit pkgs;
  }).pythonSet
);
assert fails (scope.app { package = "missing"; });
assert fails (
  scope.app {
    package = "smiley-plot";
    name = "bad";
    command = [
      "python"
      "-c"
      "print(1)"
    ];
  }
);
assert fails (
  scope.app {
    name = "bad";
    command = [
      "python"
      "-c"
      "print(1)"
    ];
    script = "smiley-plot";
  }
);
assert fails (
  scope.app {
    command = [
      "python"
      "-c"
      "print(1)"
    ];
  }
);
assert fails (
  scope.app {
    name = "bad";
    command = [ ];
  }
);
assert fails (
  scope.app {
    name = "bad";
    command = "python app.py";
  }
);
assert fails (
  scope.app {
    name = "bad";
    command = [
      "python"
      { bad = true; }
    ];
  }
);
assert fails (
  scope.app {
    name = "";
    command = [
      "python"
      "-c"
      "print(1)"
    ];
  }
);
assert fails (
  scope.app {
    name = "bad";
    command = [
      "python"
      "-c"
      "print(1)"
    ];
    pythonPath = [
      "src"
      { bad = true; }
    ];
  }
);
assert fails (
  scope.app {
    package = "smiley-plot";
    script = "";
  }
);
assert fails (
  scope.app {
    package = "smiley-plot";
    script = 123;
  }
);
assert fails (
  scope.app {
    package = "smiley-plot";
    script = [ "smiley-plot" ];
  }
);
assert fails (
  scope.app {
    package = "smiley-plot";
    script = "nested/tool";
  }
);
assert fails (
  scope.app {
    package = "smiley-plot";
    script = "smiley-plot";
    name = "renamed";
  }
);
assert fails (
  scope.app {
    package = "smiley-plot";
    script = "smiley-plot";
    pname = "";
  }
);
assert fails (
  scope.app {
    package = "smiley-plot";
    script = "smiley-plot";
    pname = 123;
  }
);
assert fails (
  scope.app {
    package = "smiley-plot";
    script = "smiley-plot";
    pname = "nested/tool";
  }
);
assert fails (scope.check.pytest { package = "missing"; });
assert fails (
  scope.check.pytest {
    package = "smiley-plot";
    dependencies = { };
  }
);
assert fails (multiScope.app { });
assert fails (multiScope.check.pytest { });
assert fails (
  (script.forPython {
    inherit pkgs;
    interpreter = pkgs.python312;
    sourcePreference = "bad";
  }).pythonSet
);
assert fails (
  (script.forPython {
    inherit pkgs;
    interpreter = pkgs.python312;
    overlays = { };
  }).pythonSet
);
assert fails (uvloom.lib.inline.load { path = ./fixtures/scripts/plain.py; });
true
