# Contributing

## Commit messages

Use [Conventional Commits](https://www.conventionalcommits.org/):

```text
feat(scope): add a capability
fix(scope): correct a failure
refactor(scope): simplify an implementation
```

Pull requests are checked with commitlint. The check evaluates every commit in
the pull request, not only the latest commit.

Enter the development shell, install the dependencies, and enable the local
hook with:

```sh
nix develop
npm ci
just hooks-install
```

## Releases

The release version is stored in `VERSION` as a stable semantic version, for
example `0.1.0`. Change it in a pull request when preparing a release.

After the change reaches `main`, the release workflow will:

1. run `nix flake check`;
2. generate release notes with `git-cliff`;
3. create the corresponding `vX.Y.Z` tag; and
4. create a GitHub release.

Do not reuse an existing version. Breaking API changes require a major
semantic-version change once the project reaches `1.0.0`; while the project is
below `1.0.0`, document and review such changes explicitly.
