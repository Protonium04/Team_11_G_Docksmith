# docksmith/cache.py
# ============================================================
#  PREKSHA — Build Cache System
# ============================================================

import os
import json
import hashlib

CACHE_DIR   = os.path.expanduser("~/.docksmith/cache")
CACHE_INDEX = os.path.join(CACHE_DIR, "index.json")
LAYERS_DIR  = os.path.expanduser("~/.docksmith/layers")


def ensure_cache_dir():
    os.makedirs(CACHE_DIR, exist_ok=True)


def compute_cache_key(
    prev_digest: str,
    instruction_text: str,
    workdir: str,
    env_serialized: str,
    copy_hashes: list = None,
) -> str:
    """
    Deterministic SHA-256 cache key.
    Null-byte separators prevent collisions between fields.
    """
    parts = [
        prev_digest or "",
        instruction_text,
        workdir or "",
        env_serialized or "",
        "\x00".join(sorted(copy_hashes)) if copy_hashes else "",
    ]
    raw = "\x00".join(parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _load_index() -> dict:
    ensure_cache_dir()
    if not os.path.exists(CACHE_INDEX):
        return {}
    try:
        with open(CACHE_INDEX, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _save_index(index: dict):
    ensure_cache_dir()
    tmp = CACHE_INDEX + ".tmp"
    with open(tmp, "w") as f:
        json.dump(index, f, indent=2)
    os.rename(tmp, CACHE_INDEX)


def lookup(
    prev_digest: str,
    instruction_text: str,
    workdir: str,
    env_serialized: str,
    copy_hashes: list = None,
) -> str:
    """
    Returns cached layer digest if it exists on disk, else None.
    """
    key    = compute_cache_key(prev_digest, instruction_text, workdir, env_serialized, copy_hashes)
    index  = _load_index()
    digest = index.get(key)
    if digest is None:
        return None

    # Verify the layer file actually exists
    hex_hash   = digest.replace("sha256:", "")
    layer_path = os.path.join(LAYERS_DIR, hex_hash)
    if not os.path.exists(layer_path):
        return None

    return digest


def store(
    prev_digest: str,
    instruction_text: str,
    workdir: str,
    env_serialized: str,
    result_digest: str,
    copy_hashes: list = None,
):
    """Writes cache key → layer digest into the index."""
    key   = compute_cache_key(prev_digest, instruction_text, workdir, env_serialized, copy_hashes)
    index = _load_index()
    index[key] = result_digest
    _save_index(index)


class CacheManager:
    """
    Stateful cache manager for a single build.
    Tracks cascade: once a miss occurs, all subsequent steps are forced misses.
    """

    def __init__(self, no_cache: bool = False):
        self.no_cache    = no_cache
        self._force_miss = False  # cascade flag

    def lookup(
        self,
        prev_digest: str,
        instruction_text: str,
        workdir: str,
        env_serialized: str,
        copy_hashes: list = None,
    ):
        if self.no_cache or self._force_miss:
            return None
        result = lookup(prev_digest, instruction_text, workdir, env_serialized, copy_hashes)
        if result is None:
            self._force_miss = True  # cascade: all remaining steps are misses
        return result

    def store(
        self,
        prev_digest: str,
        instruction_text: str,
        workdir: str,
        env_serialized: str,
        result_digest: str,
        copy_hashes: list = None,
    ):
        if self.no_cache:
            return
        store(prev_digest, instruction_text, workdir, env_serialized, result_digest, copy_hashes)

    @property
    def cache_busted(self) -> bool:
        return self._force_miss
