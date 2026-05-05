{
  lib,
  pkgs,
  self,
  templateDirs,
}:
let
  preferredTemplateOrder = [
    "simple"
    "editable"
    "pytest"
  ];

  orderedTemplateDirs =
    builtins.filter (template: builtins.elem template templateDirs) preferredTemplateOrder
    ++ builtins.filter (template: !(builtins.elem template preferredTemplateOrder)) templateDirs;

  templateDocs = pkgs.writeText "uvloom-template-docs.md" (
    ''
      # Templates

      Bundled starter flakes for common uvloom projects.

      ## Choose a template

      | Template | Best for | Output |
      | --- | --- | --- |
      | `simple` | Minimal CLI or application package. | `packages.default` |
      | `editable` | Local development with working-tree imports. | `devShells.default` |
      | `pytest` | CI/test setup with pytest. | `checks.pytest` |

      ## Initialize

      ```sh
      mkdir my-project
      cd my-project
      nix flake init -t github:fornybar/uvloom#simple
      uv lock
      nix flake check
      ```

      After initialization, rename `[project].name`, module names, script names, and `package = "..."` values to match your project.
    ''
    + lib.concatMapStringsSep "\n" (
      template:
      let
        path = ../../templates + "/${template}";
        templateFlake = import (path + "/flake.nix");
        output =
          if template == "simple" then
            "`packages.default = scope.mkApplication { ...; }`"
          else if template == "editable" then
            "`devShells.default` with `scope.mkVenv { editable = ...; }`"
          else if template == "pytest" then
            "`checks.pytest = scope.mkPytestCheck { ...; }`"
          else
            "see generated `flake.nix`";
        nextStep =
          if template == "simple" then
            "Add `mkPytestCheck` or switch to the `pytest` template when tests should run in `nix flake check`."
          else if template == "editable" then
            "Use `nix develop`, keep `UV_PYTHON_DOWNLOADS = \"never\"`, and add dependency groups through `mkVenv { editable = { ...; }; dependencies = ...; }` when needed."
          else if template == "pytest" then
            "Add package outputs with `scope.mkApplication` when you also need a runnable CLI."
          else
            "Open `flake.nix` and adapt outputs to your project.";
      in
      ''

        ## `${template}`

        ${templateFlake.description}

        ```sh
        nix flake init -t github:fornybar/uvloom#${template}
        ```

        Main output: ${output}

        Next: ${nextStep}
      ''
    ) orderedTemplateDirs
    + ''

      ## Related docs

      - [Tutorial](tutorial.md) walks through the `simple` template.
      - [How-to guides](how-to.md) show how to combine application, pytest, editable shell, and export outputs.
      - [Reference](reference.md) lists helper arguments and defaults.
    ''
  );
in
{
  docs =
    pkgs.runCommand "uvloom-docs"
      {
        nativeBuildInputs = [
          pkgs.mdbook
          pkgs.nixdoc
        ];
      }
      ''
        mkdir -p src

        cp ${../../docs/index.md} src/index.md
        cp ${../../docs/tutorial.md} src/tutorial.md
        cp ${../../docs/how-to.md} src/how-to.md
        cp ${../../docs/reference.md} src/reference.md
        cp ${../../docs/explanation.md} src/explanation.md
        cp ${../../docs/intro.md} src/intro.md
        cp ${templateDocs} src/templates.md

        nixdoc \
          --file ${../../lib/default.nix} \
          --category "" \
          --description "" \
          --prefix uvloom.lib \
          --anchor-prefix uvloom-lib- \
          > src/api.md

        cat > src/SUMMARY.md <<'EOF'
        # Summary

        [Home](index.md)

        # Start

        - [Tutorial](tutorial.md)
        - [How-to guides](how-to.md)

        # Reference

        - [Reference](reference.md)
        - [Explanation](explanation.md)

        # More

        - [Full guide](intro.md)
        - [Templates](templates.md)
        - [API](api.md)
        EOF

        cat > book.toml <<'EOF'
        [book]
        title = "uvloom"
        description = "Nix helpers for uv2nix projects"
        language = "en"
        src = "src"

        [output.html]
        default-theme = "navy"
        preferred-dark-theme = "navy"
        git-repository-url = "https://github.com/fornybar/uvloom"
        EOF

        mdbook build --dest-dir $out
      '';
}
