"""AlphaSwarm: Multi-agent financial simulation engine."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

try:
    __version__: str = version("alphaswarm")
except PackageNotFoundError:  # source tree without an installed distribution (no `uv sync`)
    __version__ = "0.0.0+unknown"
