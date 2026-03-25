# docksmith/cache.py
# ============================================================
#  PREKSHA — File 1: Build Cache System
#  Test: python3 -m pytest tests/test_cache.py -v
# ============================================================

import os
import json
import hashlib

CACHE_DIR   = os.path.expanduser("~/.docksmith/cache")
CACHE_INDEX = os.path.join(CACHE_DIR, "index.json")


# ── Setup ─────────────────────

def ensure_cache_dir():
    os.makedirs(CACHE_DIR, exist_ok=True)


# ── Cache key computation ───────────────
def compute_cache_key(
    prev_digest:      str,
    instruction_text: str,
    workdir:          str,
    env_serialized:   str,
    copy_hashes:      list = None,
) -> str:
    """
    Computes a deterministic SHA-256 cache key from all inputs.
    Inputs joined with null bytes to prevent collisions.
    """
    parts = [
        prev_digest      or "",
        instruction_text or "",
        workdir          or "",
        env_serialized   or "",
    ]

    if copy_hashes:
        parts.append("|".join(sorted(copy_hashes)))
    else:
        parts.append("")

    raw = "\x00".join(parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# ── Cache index read/write ────────

def _load_index() -> dict:
    if not os.path.exists(CACHE_INDEX):
        return {}
    try:
        with open(CACHE_INDEX, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _save_index(index: dict):
    ensure_cache_dir()
    tmp_path = CACHE_INDEX + ".tmp"
    try:
        with open(tmp_path, "w") as f:
            json.dump(index, f, indent=2)
        os.rename(tmp_path, CACHE_INDEX)
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise


# ── CacheManager class ───────

class CacheManager:
    """
    Main cache interface used by Protham's builder.py.
    """

    def __init__(self, no_cache: bool = False):
        self.no_cache    = no_cache
        self._force_miss = False

    def lookup(
        self,
        prev_digest:      str,
        instruction_text: str,
        workdir:          str,
        env_serialized:   str,
        copy_hashes:      list = None,
    ):
        """
        Returns layer digest string if HIT, None if MISS.
        """
        if self.no_cache:
            return None

        if self._force_miss:
            return None

        key   = compute_cache_key(
            prev_digest, instruction_text, workdir,
            env_serialized, copy_hashes
        )
        index = _load_index()

        if key not in index:
            return None

        cached_digest = index[key]

        # Verify layer file actually exists on disk
        try:
            from docksmith.layers import layer_exists
            if not layer_exists(cached_digest):
                return None
        except ImportError:
            pass  # layers.py not ready yet — skip disk check during solo testing

        return cached_digest

    def store(
        self,
        prev_digest:      str,
        instruction_text: str,
        workdir:          str,
        env_serialized:   str,
        copy_hashes:      list = None,
        result_digest:    str  = "",
    ):
        """
        Stores a cache entry. Also sets cascade flag.
        """
        if self.no_cache:
            return

        self._force_miss = True

        key   = compute_cache_key(
            prev_digest, instruction_text, workdir,
            env_serialized, copy_hashes
        )
        index = _load_index()
        index[key] = result_digest
        _save_index(index)

    def bust(self):
        self._force_miss = True

    def clear_index(self):
        _save_index({})