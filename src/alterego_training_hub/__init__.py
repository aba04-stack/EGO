"""EGO desktop application."""

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version

try:
    __version__ = _pkg_version("ego-desktop")
except PackageNotFoundError:
    try:
        # Support an already-installed package from before the EGO rename.
        __version__ = _pkg_version("alterego-training-hub-desktop")
    except PackageNotFoundError:  # running from an unpacked source tree
        __version__ = "1.15.2"

__all__ = ["__version__"]
