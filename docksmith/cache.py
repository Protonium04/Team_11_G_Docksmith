import hashlib
import json
import os

from docksmith.layers import layer_exists
from docksmith.paths import ensure_state_dirs, get_cache_dir


def compute_cache_key(
    prev_digest: str,
    instruction_text: str,
    workdir: str,
    env_serialized: str,
    copy_hashes: list[str] | None,
) -> str:
    payload = {
        "prev_digest": prev_digest or "",
        "instruction_text": instruction_text,
        "workdir": workdir or "",
        "env": env_serialized or "",
        "copy_hashes": sorted(copy_hashes or []),
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


class CacheManager:
    def __init__(self, no_cache: bool = False):
        self.no_cache = no_cache
        ensure_state_dirs()

    def _path_for_key(self, key: str) -> str:
        return os.path.join(get_cache_dir(), key)

    def lookup(
        self,
        prev_digest: str,
        instruction_text: str,
        workdir: str,
        env_serialized: str,
        copy_hashes: list[str] | None,
    ) -> str | None:
        if self.no_cache:
            return None

        key = compute_cache_key(
            prev_digest=prev_digest,
            instruction_text=instruction_text,
            workdir=workdir,
            env_serialized=env_serialized,
            copy_hashes=copy_hashes,
        )
        path = self._path_for_key(key)
        if not os.path.exists(path):
            return None

        with open(path, "r", encoding="utf-8") as f:
            digest = f.read().strip()
        if not digest or not layer_exists(digest):
            return None
        return digest

    def store(
        self,
        prev_digest: str,
        instruction_text: str,
        workdir: str,
        env_serialized: str,
        copy_hashes: list[str] | None,
        result_digest: str,
    ) -> None:
        if self.no_cache:
            return

        key = compute_cache_key(
            prev_digest=prev_digest,
            instruction_text=instruction_text,
            workdir=workdir,
            env_serialized=env_serialized,
            copy_hashes=copy_hashes,
        )
        with open(self._path_for_key(key), "w", encoding="utf-8") as f:
            f.write(result_digest)
