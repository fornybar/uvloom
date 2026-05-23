{
  pkgs,
  uvloom,
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
    overlays = { };
  }).pythonSet
);
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
assert fails (
  scope.venv {
    name = "bad-editable-kind-env";
    editable = true;
  }
);
assert fails (
  scope.venv {
    name = "missing-editable-root-env";
    editable = { };
  }
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
