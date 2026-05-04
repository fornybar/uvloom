{
  lib,
  pkgs,
  self,
  templateDirs,
}:
let
  templateDocs = pkgs.writeText "uvloom-template-docs.md" (
    ''
      ## Templates

      Bundled starter flakes.
    ''
    + lib.concatMapStringsSep "\n" (
      template:
      let
        path = ../../templates + "/${template}";
        templateFlake = import (path + "/flake.nix");
      in
      ''

        ### `${template}`

        ${templateFlake.description}

        Initialize it with:

        ```sh
        nix flake init -t github:fornybar/uvloom#${template}
        ```

        Template `flake.nix`:

        ```nix
        ${builtins.readFile (path + "/flake.nix")}
        ```
      ''
    ) templateDirs
    + ''

      ## API reference

      Full `uvloom.lib` API.
    ''
  );
in
{
  docs =
    pkgs.runCommand "uvloom-docs"
      {
        nativeBuildInputs = [
          pkgs.nixdoc
          pkgs.pandoc
        ];
      }
      ''
        mkdir -p $out

        nixdoc \
          --file ${../../lib/default.nix} \
          --category "" \
          --description "" \
          --prefix uvloom.lib \
          --anchor-prefix uvloom-lib- \
          > api.md

        sed -E 's/ \{#[^}]+\}$//' api.md > api-site.md

        cat > index.md <<'EOF'
        # uvloom

        uvloom is a small Nix library flake for Python projects that use `uv` and `uv2nix`.

        ## Start here

        - [Tutorial](tutorial.html): first working project.
        - [How-to guides](how-to.html): copyable recipes.
        - [Reference](reference.html): function names and arguments.
        - [Explanation](explanation.html): project/scope/editable model.
        - [Templates](templates.html): bundled starter flakes.
        - [API](api.html): full `uvloom.lib` API.

        ## Template start

        ```sh
        mkdir my-project
        cd my-project
        nix flake init -t github:fornybar/uvloom#simple
        uv lock
        nix flake check
        ```

        ## Main pattern

        ```nix
        project = uvloom.lib.loadProject { root = ./.; };
        scope = project.forPython { inherit pkgs; interpreter = pkgs.python312; };

        packages.''${system}.default = scope.mkApplication { package = "my-project"; };
        checks.''${system}.pytest = scope.mkPytestCheck { package = "my-project"; };
        ```
        EOF

        cp ${../../docs/tutorial.md} tutorial.md
        cp ${../../docs/how-to.md} how-to.md
        cp ${../../docs/reference.md} reference.md
        cp ${../../docs/explanation.md} explanation.md
        cp ${../../docs/intro.md} guide.md
        cp ${templateDocs} templates.md
        cp api.md $out/api.md
        cp api-site.md $out/api-site.md
        cp tutorial.md $out/tutorial.md
        cp how-to.md $out/how-to.md
        cp reference.md $out/reference.md
        cp explanation.md $out/explanation.md
        cp guide.md $out/guide.md
        cp templates.md $out/templates.md
        cp index.md $out/index.md

        cp ${../assets/docs-style.css} $out/style.css

        render() {
          page="$1"
          title="$2"
          outfile="$3"
          {
            echo '<!doctype html><html lang="en"><head><meta charset="utf-8">'
            echo '<meta name="viewport" content="width=device-width, initial-scale=1">'
            echo "<title>$title</title><link rel=\"stylesheet\" href=\"style.css?v=4\">"
            echo '</head><body>'
            echo '<nav><strong>uvloom</strong><a href="index.html">Home</a><a href="tutorial.html">Tutorial</a><a href="how-to.html">How-to</a><a href="reference.html">Reference</a><a href="explanation.html">Explanation</a><a href="templates.html">Templates</a><a href="api.html">API</a></nav>'
            pandoc --from gfm --to html --highlight-style=tango "$page"
            echo '</body></html>'
          } > "$outfile"
        }

        render index.md "uvloom docs" $out/index.html
        render tutorial.md "uvloom tutorial" $out/tutorial.html
        render how-to.md "uvloom how-to guides" $out/how-to.html
        render reference.md "uvloom reference" $out/reference.html
        render explanation.md "uvloom explanation" $out/explanation.html
        render guide.md "uvloom full guide" $out/guide.html
        render templates.md "uvloom templates" $out/templates.html
        render api-site.md "uvloom API" $out/api.html
      '';
}
