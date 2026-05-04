{
  pkgs,
  uvloom,
}:

let
  fails = expr: !(builtins.tryEval (builtins.deepSeq expr true)).success;

  project = uvloom.lib.loadProject {
    root = ./fixtures/smiley-plot;
  };

  multiProject = uvloom.lib.loadProject {
    root = ./fixtures/multi-package;
  };

  badPythonProject = uvloom.lib.loadProject {
    root = ./fixtures/bad-python;
  };

  scope = project.forPython {
    inherit pkgs;
    interpreter = pkgs.python312;
  };

  multiScope = multiProject.forPython {
    inherit pkgs;
    interpreter = pkgs.python312;
  };

  script = uvloom.lib.loadScript {
    script = ./fixtures/scripts/example.py;
  };
in
assert fails (
  project.forPython {
    inherit pkgs;
    interpreter = pkgs.python312;
    sourcePreference = "bad";
  }
);
assert fails (
  project.forPython {
    inherit pkgs;
    interpreter = pkgs.python312;
    overlays = { };
  }
);
assert fails (
  project.forPython {
    inherit pkgs;
    interpreter = pkgs.python312;
    editable.root = ./fixtures/smiley-plot;
  }
);
assert fails (
  badPythonProject.forPython {
    inherit pkgs;
  }
);
assert fails (scope.mkApplication { package = "missing"; });
assert fails (scope.mkPytestCheck { package = "missing"; });
assert fails (
  scope.mkPytestCheck {
    package = "smiley-plot";
    dependencies = { };
  }
);
assert fails (multiScope.mkApplication { });
assert fails (multiScope.mkPytestCheck { });
assert fails (
  script.forPython {
    inherit pkgs;
    interpreter = pkgs.python312;
    sourcePreference = "bad";
  }
);
assert fails (
  script.forPython {
    inherit pkgs;
    interpreter = pkgs.python312;
    overlays = { };
  }
);
true
