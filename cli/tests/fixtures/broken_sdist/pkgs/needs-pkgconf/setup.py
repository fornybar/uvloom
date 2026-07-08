"""Deliberately broken sdist build (spec metric 4a fixture).

Mimics native packages (pyzmq, pycairo, python-snappy, ...) whose setup
probes for pkg-config at build time and aborts when it is absent.  The
nixpkgs Python build environment does not provide pkg-config, so building
this package fails until an uv.nix stanza adds it to nativeBuildInputs.
"""

import shutil
import sys

if shutil.which("pkg-config") is None:
    sys.stderr.write("error: pkg-config is required to build needs-pkgconf\n")
    sys.exit(1)

from setuptools import setup

setup()
