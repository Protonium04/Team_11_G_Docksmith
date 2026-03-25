import os

_RESOLVED_STATE_DIR = None


def get_state_root() -> str:
    """
    Resolve Docksmith state root.
    Priority:
    1) DOCKSMITH_HOME environment variable
    2) ~/.docksmith
    3) ./.docksmith (workspace fallback)
    """
    global _RESOLVED_STATE_DIR
    if _RESOLVED_STATE_DIR is not None:
        return _RESOLVED_STATE_DIR

    candidates = []
    env_home = os.getenv("DOCKSMITH_HOME")
    if env_home:
        candidates.append(env_home)
    candidates.append(os.path.expanduser("~/.docksmith"))
    candidates.append(os.path.abspath(".docksmith"))

    for root in candidates:
        try:
            os.makedirs(root, exist_ok=True)
            _RESOLVED_STATE_DIR = root
            return root
        except OSError:
            continue

    raise PermissionError(
        "[STATE ERROR] Unable to create Docksmith state directory.\n"
        "  Tried DOCKSMITH_HOME, ~/.docksmith, and ./.docksmith"
    )


def get_images_dir() -> str:
    return os.path.join(get_state_root(), "images")


def get_layers_dir() -> str:
    return os.path.join(get_state_root(), "layers")


def get_cache_dir() -> str:
    return os.path.join(get_state_root(), "cache")


def ensure_state_dirs() -> None:
    os.makedirs(get_images_dir(), exist_ok=True)
    os.makedirs(get_layers_dir(), exist_ok=True)
    os.makedirs(get_cache_dir(), exist_ok=True)
