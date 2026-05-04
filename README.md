# uvloom

[![badge](https://shieldcn.dev/badge/docs-76E691.svg?logo=lu%3ABook&color=124442)](https://fornybar.github.io/uvloom/)

uvloom is a Nix library for weaving [`uv`](https://docs.astral.sh/uv/) projects into Nix, in the form of a small wrapper around [`uv2nix`](https://github.com/pyproject-nix/uv2nix) that reduces common boilerplate.

## Docs

Read docs site for tutorials, how-to guides, API reference, and explanation:

<https://fornybar.github.io/uvloom/>

## Templates

Bundled templates:

- `simple`: minimal application package.
- `editable`: editable development environment.
- `pytest`: pytest check integration.

Initialize one:

```sh
nix flake init -t github:fornybar/uvloom#pytest
```

## License

[MIT](LICENSE)
