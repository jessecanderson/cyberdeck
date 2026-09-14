"""Cyberdeck multi-agent TUI."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("cyberdeck-tui")
except PackageNotFoundError:
    __version__ = "0.4.1+local"

__all__ = ["__version__"]
