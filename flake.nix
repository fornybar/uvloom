{
  description = "uvloom: thin wrapper around uv2nix";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

    pyproject-nix = {
      url = "github:pyproject-nix/pyproject.nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };

    uv2nix = {
      url = "github:pyproject-nix/uv2nix";
      inputs.nixpkgs.follows = "nixpkgs";
      inputs.pyproject-nix.follows = "pyproject-nix";
    };

    pyproject-build-systems = {
      url = "github:pyproject-nix/build-system-pkgs";
      inputs.nixpkgs.follows = "nixpkgs";
      inputs.pyproject-nix.follows = "pyproject-nix";
      inputs.uv2nix.follows = "uv2nix";
    };
  };

  outputs =
    {
      self,
      nixpkgs,
      pyproject-nix,
      uv2nix,
      pyproject-build-systems,
      ...
    }:
    let
      lib = nixpkgs.lib;

      uvloom = {
        lib = import ./lib {
          inherit lib;
          inherit
            uv2nix
            pyproject-nix
            pyproject-build-systems
            ;
        };
      };

      systems = [
        "x86_64-linux"
        "aarch64-linux"
        "x86_64-darwin"
        "aarch64-darwin"
      ];

      forAllSystems = lib.genAttrs systems;
    in
    {
      inherit (uvloom) lib;

      templates =
        let
          root = ./templates;
          dirs = lib.pipe (builtins.readDir root) [
            (lib.filterAttrs (_: type: type == "directory"))
            lib.attrNames
          ];
        in
        lib.listToAttrs (
          map (
            dir:
            let
              path = root + "/${dir}";
              template = import (path + "/flake.nix");
            in
            lib.nameValuePair dir {
              inherit path;
              inherit (template) description;
            }
          ) dirs
        );

      packages = forAllSystems (
        system:
        let
          pkgs = nixpkgs.legacyPackages.${system};

          templateDirs = lib.pipe (builtins.readDir ./templates) [
            (lib.filterAttrs (_: type: type == "directory"))
            lib.attrNames
          ];

          templateDocs = pkgs.writeText "uvloom-template-docs.md" (
            ''
              ## Templates

              Bundled starter flakes.
            ''
            + lib.concatMapStringsSep "\n" (
              template:
              let
                path = ./templates + "/${template}";
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
                  --file ${./lib/default.nix} \
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

                cp ${./docs/tutorial.md} tutorial.md
                cp ${./docs/how-to.md} how-to.md
                cp ${./docs/reference.md} reference.md
                cp ${./docs/explanation.md} explanation.md
                cp ${./docs/intro.md} guide.md
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

                cat > $out/style.css <<'EOF'
                :root {
                  color-scheme: light dark;
                  --bg: #ffffff;
                  --fg: #111827;
                  --muted: #4b5563;
                  --border: #d1d5db;
                  --code: #f3f4f6;
                  --link: #1d4ed8;
                }

                @media (prefers-color-scheme: dark) {
                  :root {
                    --bg: #111827;
                    --fg: #f9fafb;
                    --muted: #d1d5db;
                    --border: #4b5563;
                    --code: #1f2937;
                    --link: #93c5fd;
                  }
                }

                body {
                  max-width: 50rem;
                  margin: 0 auto;
                  padding: 2rem 1rem 4rem;
                  background: var(--bg);
                  color: var(--fg);
                  font: 16px/1.55 sans-serif;
                }

                nav {
                  margin-bottom: 2rem;
                  padding-bottom: 0.75rem;
                  border-bottom: 1px solid var(--border);
                }

                nav strong { margin-right: 1rem; }
                nav a { margin-right: 1rem; color: var(--link); }
                h1, h2, h3 { line-height: 1.25; }
                h1 { margin-top: 0; }
                h2 { margin-top: 2rem; padding-top: 0.5rem; border-top: 1px solid var(--border); }
                a { color: var(--link); }
                p, li, dd { color: var(--muted); }
                code, pre { background: var(--code); }
                code { padding: 0.1rem 0.25rem; }
                pre { padding: 1rem; overflow-x: auto; border: 1px solid var(--border); }
                pre code { padding: 0; }
                dt { font-weight: 700; }
                dd { margin: 0 0 1rem; }

                code span.al { color: #ef2929; }
                code span.an { color: #8f5902; font-weight: bold; font-style: italic; }
                code span.at { color: #204a87; }
                code span.bn { color: #0000cf; }
                code span.cf { color: #204a87; font-weight: bold; }
                code span.ch { color: #4e9a06; }
                code span.cn { color: #8f5902; }
                code span.co { color: #8f5902; font-style: italic; }
                code span.cv { color: #8f5902; font-weight: bold; font-style: italic; }
                code span.do { color: #8f5902; font-weight: bold; font-style: italic; }
                code span.dt { color: #204a87; }
                code span.dv { color: #0000cf; }
                code span.er { color: #a40000; font-weight: bold; }
                code span.fl { color: #0000cf; }
                code span.fu { color: #204a87; font-weight: bold; }
                code span.in { color: #8f5902; font-weight: bold; font-style: italic; }
                code span.kw { color: #204a87; font-weight: bold; }
                code span.op { color: #ce5c00; font-weight: bold; }
                code span.ot { color: #8f5902; }
                code span.pp { color: #8f5902; font-style: italic; }
                code span.sc { color: #ce5c00; font-weight: bold; }
                code span.ss { color: #4e9a06; }
                code span.st { color: #4e9a06; }
                code span.va { color: var(--fg); }
                code span.vs { color: #4e9a06; }
                code span.wa { color: #8f5902; font-weight: bold; font-style: italic; }
                EOF

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
      );

      devShells = forAllSystems (
        system:
        let
          pkgs = nixpkgs.legacyPackages.${system};
        in
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
      );

      checks = forAllSystems (
        system:
        let
          pkgs = nixpkgs.legacyPackages.${system};

          evalTest = import ./test/eval.nix {
            inherit pkgs uvloom;
          };

          negativeTest = import ./test/negative.nix {
            inherit pkgs uvloom;
          };

          buildChecks = import ./test/builds.nix {
            inherit pkgs uvloom;
          };

          templateFlakes =
            let
              templateDirs = lib.pipe (builtins.readDir ./templates) [
                (lib.filterAttrs (_: type: type == "directory"))
                lib.attrNames
              ];

              callTemplate =
                template:
                let
                  flakeFile = import (./templates + "/${template}/flake.nix");
                  flake = flakeFile.outputs args;
                  args = builtins.mapAttrs (name: _: inputs'.${name}) (builtins.functionArgs flakeFile.outputs);
                  inputs' = {
                    self = flake;
                    inherit nixpkgs uvloom;
                  };
                in
                flake;

              mkCheck = template: prefix: check: drv: {
                name = "template-${template}-${prefix}-${check}";
                value = drv;
              };

              mkTemplateChecks =
                template:
                let
                  flake = callTemplate template;
                  checksFor =
                    prefix: attr: lib.mapAttrsToList (mkCheck template prefix) (flake.${attr}.${system} or { });
                in
                checksFor "package" "packages" ++ checksFor "check" "checks" ++ checksFor "devShell" "devShells";
            in
            lib.pipe templateDirs [
              (lib.concatMap mkTemplateChecks)
              builtins.listToAttrs
            ];
        in
        buildChecks
        // templateFlakes
        // {
          docs = self.packages.${system}.docs;

          eval = pkgs.runCommand "uvloom-eval" { } ''
            ${if evalTest then "touch $out" else "false"}
          '';

          negative = pkgs.runCommand "uvloom-negative" { } ''
            ${if negativeTest then "touch $out" else "false"}
          '';
        }
      );

      formatter = forAllSystems (
        system:
        let
          pkgs = nixpkgs.legacyPackages.${system};
        in
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
      );
    };
}
