"""Sauron — Personal Voice Intelligence System."""

from importlib.metadata import version, PackageNotFoundError

try:
    __version__ = version("sauron")
except PackageNotFoundError:
    __version__ = "0.3.1"  # fallback when not installed via pip
