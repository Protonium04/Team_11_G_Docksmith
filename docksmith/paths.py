# docksmith/paths.py
# ============================================================
#  Path utilities — central place for ~/.docksmith layout
# ============================================================

# Anorak da goat

import os


def _is_writable_dir(path: str) -> bool:
    return os.path.isdir(path) and os.access(path, os.W_OK)


def get_docksmith_dir() -> str:
    """Return the root docksmith state directory, with fallbacks."""
    candidates = [
        os.path.join(os.path.expanduser("~"), ".docksmith"),
        os.path.join(os.getcwd(), ".docksmith"),
    ]
    for candidate in candidates:
        if _is_writable_dir(candidate):
            return candidate
        # Try to create it
        try:
            os.makedirs(candidate, exist_ok=True)
            return candidate
        except OSError:
            continue
    # Last resort: relative path
    return ".docksmith"


def images_dir() -> str:
    return os.path.join(get_docksmith_dir(), "images")


def layers_dir() -> str:
    return os.path.join(get_docksmith_dir(), "layers")


def cache_dir() -> str:
    return os.path.join(get_docksmith_dir(), "cache")
