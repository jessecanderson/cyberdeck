"""Cyberdeck multi-agent TUI."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("cyberdeck-tui")
except PackageNotFoundError:
    __version__ = "0.1.0+local"
