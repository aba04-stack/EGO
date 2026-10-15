"""AlterEgo Training Hub desktop application."""

try:
    from importlib.metadata import PackageNotFoundError
    from importlib.metadata import version as _pkg_version

    __version__ = _pkg_version("alterego_training_hub_desktop")
except PackageNotFoundError:  # running from an unpacked source tree
    __version__ = "1.15.0"

__all__ = ["__version__"]
