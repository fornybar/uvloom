# Whitelist-based source filtering for loadProject. Only explicitly
# whitelisted paths reach the store copy: project metadata
# (pyproject.toml, uv.lock, .python-version, uv.nix), README*/LICENSE*/
# LICENCE*/COPYING*/NOTICE*/AUTHORS* regular files at the root, the declared
# [project].readme, [project].license.file and [project].license-files
# entries, the source trees of every local package recorded in uv.lock
# (including the root package sources of a root `virtual = "."` package),
# the pyproject.toml of every non-root virtual workspace member, and any
# extraSourcePaths. See the loadProject doc comment in ./default.nix for
# the user-facing contract.
{
  lib,
  fail,
}:

let
  where = "project.load";

  fs = lib.fileset;

  # fileset.toSource cannot reach outside `root`; reject escapes loudly
  # instead of producing a store copy with dangling paths. Paths that
  # normalize to the root itself ("", ".", "./", ...) are rejected too:
  # `root + "/"` equals `root`, so they would silently whitelist the
  # entire root tree.
  checkInside =
    p:
    let
      segments = lib.splitString "/" p;
    in
    if lib.hasPrefix "/" p || lib.any (seg: seg == "..") segments then
      fail where (
        "filterSource cannot include local source '${p}' outside the project root — "
        + "use filterSource = false for this project"
      )
    else if builtins.all (seg: seg == "" || seg == ".") segments then
      fail where (
        "filterSource cannot whitelist the project root itself via '${p}' — "
        + "use filterSource = false for this project"
      )
    else
      p;

  unsupported =
    pattern:
    fail where (
      "unsupported [project].license-files pattern '${builtins.toJSON pattern}' — "
      + "use extraSourcePaths or filterSource = false for this project"
    );

  unsupportedDirChars = [
    "?"
    "["
    "]"
    "{"
    "}"
  ];
  unsupportedFileChars = [
    "?"
    "{"
    "}"
  ];
  hasChars = chars: value: lib.any (char: lib.hasInfix char value) chars;
  hasInvalidStar =
    value:
    let
      starParts = lib.splitString "*" value;
    in
    !(
      builtins.length starParts == 1
      || (builtins.length starParts == 2 && builtins.elemAt starParts 1 == "")
    );

  # Character classes in the file part: expand single-character `[...]`
  # groups (plain characters only — no ranges, no negation) into literal
  # alternatives, so `LICEN[CS]E*` works; any other glob form still fails
  # loudly.
  expandClasses =
    pattern: value:
    let
      splitClass =
        acc: rest:
        if rest == [ ] then
          unsupported pattern
        else
          let
            char = builtins.head rest;
          in
          if char == "]" then
            if acc == [ ] then
              unsupported pattern
            else
              {
                alternatives = acc;
                rest = builtins.tail rest;
              }
          else if
            builtins.elem char [
              "-"
              "!"
              "^"
              "["
              "*"
            ]
          then
            unsupported pattern
          else
            splitClass (acc ++ [ char ]) (builtins.tail rest);
      go =
        rest:
        if rest == [ ] then
          [ "" ]
        else
          let
            char = builtins.head rest;
          in
          if char == "[" then
            let
              class = splitClass [ ] (builtins.tail rest);
            in
            lib.concatMap (alt: map (suffix: alt + suffix) (go class.rest)) class.alternatives
          else if char == "]" then
            unsupported pattern
          else
            map (suffix: char + suffix) (go (builtins.tail rest));
    in
    go (lib.stringToCharacters value);

  # Parse a license-files glob into a checked directory part and literal
  # file-name alternatives (`*` only as a trailing suffix). The empty
  # dirPart means the pattern globs directly in the root.
  parsedPattern =
    pattern:
    if !builtins.isString pattern then
      unsupported pattern
    else if lib.hasInfix "**" pattern then
      unsupported pattern
    else
      let
        parts = lib.splitString "/" pattern;
        # Python backends glob these patterns relative to the project
        # root, where a leading `./` is a no-op (`./LICENSE*` matches the
        # same files as `LICENSE*`); strip leading `.` segments so such
        # patterns work instead of tripping the root-whitelist check in
        # checkInside with a misleading "cannot whitelist the project
        # root" error. Only leading segments are dropped — `..` and
        # interior oddities still fail via checkInside / the readDir walk.
        stripLeadingDots =
          segs:
          if segs != [ ] && builtins.head segs == "." then stripLeadingDots (builtins.tail segs) else segs;
        dirParts = stripLeadingDots (lib.init parts);
        rawDirPart = lib.concatStringsSep "/" dirParts;
        dirPart = if rawDirPart == "" then "" else checkInside rawDirPart;
        filePart = lib.last parts;
        alternatives = expandClasses pattern filePart;
      in
      if lib.any (part: lib.hasInfix "*" part || hasChars unsupportedDirChars part) dirParts then
        unsupported pattern
      else if hasChars unsupportedFileChars filePart || lib.any hasInvalidStar alternatives then
        unsupported pattern
      else
        {
          inherit dirPart dirParts;
          alternatives = map (alt: {
            literal = alt;
            prefix = lib.removeSuffix "*" alt;
            isPrefix = lib.hasSuffix "*" alt;
          }) alternatives;
        };

  filterRoot =
    {
      root,
      extraSourcePaths ? [ ],
    }:
    let
      checkedExtraSourcePaths =
        if builtins.isList extraSourcePaths && builtins.all builtins.isString extraSourcePaths then
          extraSourcePaths
        else
          fail where "extraSourcePaths must be a list of strings";

      # Root-relative directory path to a path value; "" is the root itself
      # (only produced internally for glob patterns without a directory part).
      entryPath = p: if p == "" then root else root + "/${p}";

      pathTypeOrNull =
        path:
        let
          result = builtins.tryEval (
            builtins.deepSeq (lib.filesystem.pathType path) (lib.filesystem.pathType path)
          );
        in
        if result.success then result.value else null;

      # pathExists follows symlinks and returns false for a dangling one.
      # Inspect its parent entry too so a selected dangling symlink is
      # rejected rather than silently omitted.
      entryExists =
        path:
        builtins.pathExists path
        || (
          builtins.pathExists (builtins.dirOf path)
          && (builtins.readDir (builtins.dirOf path)) ? ${baseNameOf path}
        );

      # fileset copies symlinks as dangling leaves in its store source. Every
      # selected path must therefore be a real file/tree, and selected trees
      # must not contain symlinks at any depth. Keep this check narrow: it
      # walks only paths already admitted to the whitelist.
      checkNoSymlinks =
        what: p:
        let
          path = root + "/${p}";
          walk =
            current:
            let
              type = pathTypeOrNull current;
            in
            if type == "symlink" then
              fail where (
                "${what} '${p}' contains a symlink — lib.fileset would copy it as a dangling link; "
                + "use filterSource = false for this project"
              )
            else if type == "directory" then
              builtins.foldl' (_: name: walk (current + "/${name}")) null (
                builtins.attrNames (builtins.readDir current)
              )
            else
              null;
        in
        builtins.seq (walk path) path;

      checkNoSymlinkPath =
        what: path:
        let
          walk =
            current:
            let
              type = pathTypeOrNull current;
            in
            if type == "symlink" then
              fail where (
                "${what} '${toString path}' contains a symlink — lib.fileset would copy it as a dangling link; "
                + "use filterSource = false for this project"
              )
            else if type == "directory" then
              builtins.foldl' (_: name: walk (current + "/${name}")) null (
                builtins.attrNames (builtins.readDir current)
              )
            else
              null;
        in
        builtins.seq (walk path) path;

      # A declared singleton is metadata, not a source tree. Directories and
      # symlinks must fail instead of quietly broadening or dangling it.
      optionalRegular =
        what: p:
        let
          checked = checkInside p;
          path = root + "/${checked}";
        in
        if !entryExists path then
          [ ]
        else if lib.filesystem.pathType path == "regular" then
          [ path ]
        else
          fail where "${what} '${p}' must be a regular non-symlink file";

      requiredRegular =
        what: p:
        let
          path = root + "/${p}";
        in
        if pathTypeOrNull path == "regular" then
          path
        else
          fail where "${what} '${p}' must be a regular non-symlink file";

      rootEntries = builtins.readDir root;
      exists = name: rootEntries ? ${name};
      optionalEntry = name: if exists name then optionalRegular "project metadata" name else [ ];
      # README*/LICENSE* scans keep regular files only: a directory whose
      # name happens to match (e.g. LICENSES/) is not a metadata file.
      regularNames = builtins.attrNames (lib.filterAttrs (_: type: type == "regular") rootEntries);
      readmes = builtins.filter (name: lib.hasPrefix "README" name) regularNames;
      # NOTICE*/AUTHORS* join the LICENSE spellings: PEP 639 backends scan
      # these default metadata names, so filtered wheels must not silently
      # diverge from an unfiltered build.
      rootLicenses = builtins.filter (
        name:
        lib.any (prefix: lib.hasPrefix prefix name) [
          "LICENSE"
          "LICENCE"
          "COPYING"
          "NOTICE"
          "AUTHORS"
        ]
      ) regularNames;
      pyproject = builtins.fromTOML (builtins.readFile (root + "/pyproject.toml"));

      # A readme declared in [project] may live outside the root README*
      # scan (e.g. `readme = "docs/README.md"` or `readme = { file = ... }`).
      declaredReadme =
        let
          readme = pyproject.project.readme or null;
          path =
            if builtins.isString readme then
              readme
            else if builtins.isAttrs readme then
              readme.file or null
            else
              null;
        in
        if path == null then [ ] else optionalRegular "[project].readme" path;

      declaredLicense =
        let
          license = pyproject.project.license or null;
          path = if builtins.isAttrs license then license.file or null else null;
        in
        if path == null then [ ] else optionalRegular "[project].license.file" path;

      declaredLicenseFiles =
        let
          rawPatterns = pyproject.project."license-files" or [ ];
          # PEP 639 requires an array of glob patterns; a bare string
          # would otherwise crash lib.concatMap with a raw type error.
          patterns =
            if builtins.isList rawPatterns then
              rawPatterns
            else
              fail where (
                "[project].license-files must be an array of glob patterns (PEP 639), "
                + "got '${builtins.toJSON rawPatterns}'"
              );
          pathType =
            prefix: parts:
            if parts == [ ] then
              "directory"
            else
              let
                entries = builtins.readDir (entryPath prefix);
                name = builtins.head parts;
                rest = builtins.tail parts;
                nextPrefix = if prefix == "" then name else "${prefix}/${name}";
              in
              if !(entries ? ${name}) then
                null
              else if rest == [ ] then
                entries.${name}
              else if entries.${name} == "directory" then
                pathType nextPrefix rest
              else
                null;
          dirEntries =
            dirPart: dirParts:
            if pathType "" dirParts == "directory" then builtins.readDir (entryPath dirPart) else { };
          matchedNames =
            pattern:
            let
              parsed = parsedPattern pattern;
              entries = dirEntries parsed.dirPart parsed.dirParts;
              # Python backends glob files only: a directory whose name
              # happens to match is silently skipped.
              names = builtins.attrNames (lib.filterAttrs (_: type: type == "regular") entries);
              matchesAlt = alt: name: if alt.isPrefix then lib.hasPrefix alt.prefix name else name == alt.literal;
              matches = builtins.filter (name: lib.any (alt: matchesAlt alt name) parsed.alternatives) names;
            in
            # PEP 639 build backends treat a non-matching pattern as an
            # error; dropping it silently would ship a package without its
            # declared license files.
            if matches == [ ] then
              fail where (
                "[project].license-files pattern '${pattern}' matched no files — "
                + "fix the pattern, or use filterSource = false for this project"
              )
            else
              map (name: if parsed.dirPart == "" then name else "${parsed.dirPart}/${name}") matches;
        in
        map (name: root + "/${name}") (lib.unique (lib.concatMap matchedNames patterns));

      # Local sources come from uv.lock — the authoritative list of
      # workspace members and local path dependencies. Editable and
      # directory sources contribute whole trees; `path` sources are
      # local wheel/sdist archives (a file, or an unpacked directory);
      # non-root `virtual` members carry no package sources, but their
      # manifests must survive because uv2nix folds member
      # `[tool.uv]` config into the workspace configuration. A root
      # `virtual = "."` package (`[tool.uv] package = false`) is handled
      # separately below: it builds no wheel, but its app code must still
      # reach the filtered source or `check` derivations lose it.
      rawLock = builtins.fromTOML (builtins.readFile (root + "/uv.lock"));
      localSourcePaths = lib.concatMap (
        pkg:
        let
          source = pkg.source or { };
        in
        lib.optional (source ? editable) source.editable
        ++ lib.optional (source ? directory) source.directory
        ++ lib.optional (source ? path) source.path
        ++ lib.optional (source ? virtual && source.virtual != ".") "${source.virtual}/pyproject.toml"
      ) (rawLock.package or [ ]);
      hasVirtualRoot = lib.any (pkg: (pkg.source or { }) ? virtual && pkg.source.virtual == ".") (
        rawLock.package or [ ]
      );

      # Name-derived module directories for flat layouts: package
      # directories named after [project].name (PEP 503 characters mapped
      # to underscores, with and without lowercasing).
      moduleDirNames =
        name:
        lib.unique [
          (lib.toLower (builtins.replaceStrings [ "-" "." ] [ "_" "_" ] name))
          (builtins.replaceStrings [ "-" "." ] [ "_" "_" ] name)
        ];
      flatModuleDirs =
        let
          name = pyproject.project.name or null;
        in
        lib.optionals (name != null) (
          map (dir: root + "/${dir}") (builtins.filter exists (moduleDirNames name))
        );

      # Explicit backend package configuration: hatchling wheel targets
      # list directories verbatim; setuptools (list form only) lists
      # package names, of which only the top-level segment maps to a
      # directory under root.
      configuredPackageDirs =
        let
          hatchWheel = lib.attrByPath [ "tool" "hatch" "build" "targets" "wheel" ] { } pyproject;
          normalizeHatchPath =
            p:
            let
              stripRoot = lib.removePrefix "/" p;
              stripDots =
                value: if lib.hasPrefix "./" value then stripDots (lib.removePrefix "./" value) else value;
            in
            stripDots stripRoot;
          hatchPatternFail =
            setting: pattern: reason:
            fail where (
              "unsupported Hatch filtered-source pattern '${pattern}' in ${setting} — ${reason}; "
              + "use extraSourcePaths/--include or filterSource=false/--no-filter-source"
            );
          requireHatchList =
            setting: value:
            if builtins.isList value && builtins.all builtins.isString value then
              value
            else
              fail where "${setting} must be a list of strings";
          requireHatchForceInclude =
            value:
            if builtins.isAttrs value && builtins.all builtins.isString (builtins.attrValues value) then
              value
            else
              fail where "tool.hatch.build.targets.wheel.force-include must be an attrset of strings";
          parseHatchPattern =
            setting: pattern:
            let
              normalized = normalizeHatchPath pattern;
              parts = lib.splitString "/" normalized;
              final = lib.last parts;
              parentParts = lib.init parts;
              starParts = lib.splitString "*" final;
              starCount = builtins.length starParts - 1;
              parent = lib.concatStringsSep "/" parentParts;
              derived = if lib.hasInfix "*" normalized then parent else normalized;
              rootLike = value: value == "" || value == "." || value == "/" || value == "./";
            in
            if !(builtins.isString pattern) then
              fail where "${setting} must be a list of strings"
            else if lib.hasPrefix "!" pattern then
              hatchPatternFail setting pattern "negation is not supported by whitelist source filtering"
            else if
              rootLike pattern
              || rootLike normalized
              || builtins.elem pattern [
                "*"
                "**"
                "/*"
                "/**"
              ]
            then
              hatchPatternFail setting pattern "pattern can select the project root"
            else if
              lib.hasPrefix "~" normalized || lib.hasInfix ":" normalized || lib.hasInfix "\\" normalized
            then
              hatchPatternFail setting pattern "pattern is not a portable project-relative path"
            else if lib.any (seg: seg == "..") parts then
              hatchPatternFail setting pattern "pattern escapes the project root"
            else if lib.hasInfix "**" normalized then
              hatchPatternFail setting pattern "recursive glob '**' is not supported"
            else if hasChars [ "{" "}" "[" "]" "?" ] normalized then
              hatchPatternFail setting pattern "glob metacharacter is not supported"
            else if lib.any (part: lib.hasInfix "*" part) parentParts then
              hatchPatternFail setting pattern "wildcards in directory components are not supported"
            else if lib.hasInfix "*" normalized && starCount != 1 then
              hatchPatternFail setting pattern "multiple wildcards in final component are not supported"
            else if derived == "" then
              hatchPatternFail setting pattern "pattern can select the project root"
            else
              checkInside derived;
          requiredHatchPatternDirs =
            lib.concatMap
              ({ setting, patterns }: map (parseHatchPattern setting) (requireHatchList setting patterns))
              [
                {
                  setting = "tool.hatch.build.targets.wheel.include";
                  patterns = hatchWheel.include or [ ];
                }
                {
                  setting = "tool.hatch.build.targets.wheel.artifacts";
                  patterns = hatchWheel.artifacts or [ ];
                }
              ];
          hatchPackages = map normalizeHatchPath (hatchWheel.packages or [ ]);
          hatchOnlyInclude = map normalizeHatchPath (hatchWheel."only-include" or [ ]);
          hatchForceIncludeAttrs = requireHatchForceInclude (hatchWheel."force-include" or { });
          hatchForceInclude = builtins.attrNames hatchForceIncludeAttrs;
          checkHatchForceInclude =
            p:
            let
              normalized = normalizeHatchPath p;
            in
            if
              p != normalized
              || lib.hasPrefix "~" p
              || lib.hasInfix ":" p
              || lib.hasInfix "\\" p
              || lib.any (seg: seg == "..") (lib.splitString "/" normalized)
            then
              fail where (
                "Hatch force-include source '${p}' is outside project root; filtered source cannot include it — "
                + "use filterSource=false/--no-filter-source or move/copy artifact under project root and include it"
              )
            else
              checkInside normalized;
          setuptoolsPackageDir = lib.attrByPath [ "tool" "setuptools" "package-dir" ] { } pyproject;
          setuptoolsFindWhere =
            lib.attrByPath [ "tool" "setuptools" "packages" "find" "where" ] [ ]
              pyproject;
          setuptoolsPackageDirPaths = builtins.attrValues setuptoolsPackageDir;
          setuptoolsPackages =
            let
              packages = lib.attrByPath [ "tool" "setuptools" "packages" ] null pyproject;
            in
            if builtins.isList packages then
              map (name: builtins.head (lib.splitString "." name)) packages
            else
              [ ];
          configured =
            hatchPackages
            ++ hatchOnlyInclude
            ++ setuptoolsPackageDirPaths
            ++ setuptoolsFindWhere
            ++ setuptoolsPackages;
          requiredConfigured = lib.unique requiredHatchPatternDirs;
          requiredForceInclude = lib.unique (map checkHatchForceInclude hatchForceInclude);
        in
        map (
          p:
          if entryExists (root + "/${p}") then
            checkNoSymlinks "Hatch include/artifacts source" p
          else
            fail where (
              "Hatch include/artifacts selected '${p}' but it does not exist — "
              + "use extraSourcePaths/--include, generate it before filtering, or use filterSource=false/--no-filter-source"
            )
        ) requiredConfigured
        ++ map (
          p:
          if entryExists (root + "/${p}") then
            checkNoSymlinks "Hatch force-include source" p
          else
            fail where (
              "Hatch force-include source '${p}' does not exist — "
              + "use filterSource=false/--no-filter-source or move/copy artifact under project root and include it"
            )
        ) requiredForceInclude
        ++ lib.concatMap (
          p:
          let
            checked = checkInside p;
          in
          lib.optional (builtins.pathExists (root + "/${checked}")) (root + "/${checked}")
        ) (lib.unique configured);

      # Sources of the root package: explicitly configured package dirs
      # always count; `src/` (when present) is included alongside them.
      # Flat fallbacks (top-level *.py plus name-derived module dirs)
      # apply when there is no src/ — and also when src/ exists but holds
      # no Python files at all: such a src/ cannot be a Python source
      # layout (setuptools/hatchling src-layout discovery requires
      # src/<pkg>/*.py), so its mere presence must not silently drop a
      # coexisting flat package. A src/ that does contain Python keeps
      # suppressing the fallback: pulling stray root *.py (conftest.py,
      # setup.py shims, ...) into a genuine src-layout project would
      # churn the filtered-source hash for files no backend packages.
      srcHasPython =
        let
          hasPy =
            path:
            let
              entries = builtins.readDir path;
            in
            lib.any (
              name: if entries.${name} == "directory" then hasPy (path + "/${name}") else lib.hasSuffix ".py" name
            ) (builtins.attrNames entries);
        in
        exists "src" && rootEntries."src" == "directory" && hasPy (root + "/src");
      rootPyFiles = map (name: root + "/${name}") (
        builtins.attrNames (
          lib.filterAttrs (name: type: type == "regular" && lib.hasSuffix ".py" name) rootEntries
        )
      );
      packageCandidates =
        includeFlat:
        lib.unique (
          configuredPackageDirs
          ++ lib.optional (exists "src") (root + "/src")
          ++ lib.optionals includeFlat (rootPyFiles ++ flatModuleDirs)
        );
      rootBuildPackageCandidates = packageCandidates (!srcHasPython);
      virtualRootCandidates = packageCandidates true;
      rootBackendFiles = lib.concatMap (name: optionalRegular "root build backend input" name) [
        "setup.py"
        "setup.cfg"
        "hatch.toml"
        "MANIFEST.in"
      ];
      rootPackageSources =
        if rootBuildPackageCandidates == [ ] then
          fail where (
            "could not locate any sources for the root package — "
            + "use extraSourcePaths or filterSource = false for this project"
          )
        else
          map (checkNoSymlinkPath "root package source") rootBuildPackageCandidates;

      # A root `virtual = "."` package gets the same root package sources
      # an editable "." does, but leniently: a virtual root may
      # legitimately carry no sources at all (the loud empty-sources
      # failure stays reserved for real editable/directory "." packages).
      # Arbitrary other directories remain an extraSourcePaths concern.
      virtualRootSources = lib.optionals hasVirtualRoot (
        map (checkNoSymlinkPath "root virtual package source") virtualRootCandidates
      );

      memberSources = lib.concatMap (
        p:
        if p == "." then
          rootPackageSources
        else if entryExists (root + "/${checkInside p}") then
          [ (checkNoSymlinks "local source from uv.lock" p) ]
        else
          fail where (
            "local source '${p}' from uv.lock does not exist under the project root — "
            + "use filterSource = false for this project"
          )
      ) localSourcePaths;

      extraSources = lib.concatMap (
        p:
        let
          checked = checkInside p;
        in
        lib.optional (entryExists (root + "/${checked}")) (checkNoSymlinks "extraSourcePaths entry" checked)
      ) checkedExtraSourcePaths;

      # Hidden directories must not leak: fs.fileFilter only sees leaf
      # file names, so a file like `.pytest_cache/README.md` inside a
      # member tree would survive a name-based filter. Walk each
      # whitelisted directory tree (eval cost proportional to the
      # whitelist, not the whole root) collecting hidden subdirectories
      # to subtract from the union.
      hiddenDirsUnder =
        path:
        let
          entries = builtins.readDir path;
        in
        lib.concatMap (
          name:
          if lib.hasPrefix "." name then
            lib.optional (entries.${name} == "directory") (path + "/${name}")
          else if entries.${name} == "directory" then
            hiddenDirsUnder (path + "/${name}")
          else
            [ ]
        ) (builtins.attrNames entries);
      hiddenDirs = lib.concatMap hiddenDirsUnder (
        lib.unique (
          builtins.filter (p: lib.filesystem.pathType p == "directory") (memberSources ++ virtualRootSources)
        )
      );

      filteredSource = fs.toSource {
        inherit root;
        # Member directories are included whole; intersect with a
        # filter dropping bytecode and hidden files, then subtract
        # hidden directories found by the walk above. Bytecode: editable
        # runs creating __pycache__/*.pyc never churn the filtered source
        # hash (empty directories are never part of a fileset, so this
        # drops __pycache__ entirely). Hidden entries: dotfiles inside
        # member trees are caught by the name filter, and everything
        # under a hidden directory falls to the difference — matching
        # the CLI's env-key walk, which skips hidden entries. The
        # root-level `.python-version` and the declared [project] readme/
        # license metadata are unioned back after the intersection: a
        # declared path with a hidden segment (e.g. `.github/README.md`)
        # passed the whitelist and its loud no-match checks, so the hidden
        # filter must not silently eat it. Only these explicit entries are
        # exempt — the root-level README*/LICENSE* scan results and a
        # `.python-version` inside a member tree stay subject to it.
        fileset =
          fs.union
            # Inferred paths remain conservative: prune hidden entries and
            # bytecode even inside a selected package tree.
            (fs.difference (fs.union
              (fs.intersection (fs.fileFilter (file: !file.hasExt "pyc" && !lib.hasPrefix "." file.name) root) (
                fs.unions (
                  [
                    (requiredRegular "project metadata" "pyproject.toml")
                    (requiredRegular "project metadata" "uv.lock")
                  ]
                  ++ optionalEntry "uv.nix"
                  ++ map (name: root + "/${name}") readmes
                  ++ map (name: root + "/${name}") rootLicenses
                  ++ rootBackendFiles
                  ++ memberSources
                  ++ virtualRootSources
                )
              ))
              (
                fs.unions (
                  optionalEntry ".python-version" ++ declaredReadme ++ declaredLicense ++ declaredLicenseFiles
                )
              )
            ) (fs.unions hiddenDirs))
            # Explicit extras are an opt-in escape hatch. Preserve hidden
            # entries beneath them; otherwise `extraSourcePaths = [ ".config" ]`
            # would silently do nothing.
            (fs.unions extraSources);
      };
    in
    filteredSource;
in
{
  inherit filterRoot;

  internal = {
    inherit
      checkInside
      expandClasses
      parsedPattern
      ;
  };
}
