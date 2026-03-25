# docksmith/layers.py
# ============================================================
#  PROTHAM — File 2: Layer Creation & Storage
#  Test: python3 -m pytest tests/test_layers.py -v
# ============================================================

import os
import io
import tarfile
import hashlib
from docksmith.paths import get_layers_dir


# ── Setup ─────────────────────────────────────────────────────────────────────

def ensure_layers_dir():
    os.makedirs(get_layers_dir(), exist_ok=True)


# ── SHA-256 helpers ───────────────────────────────────────────────────────────

def sha256_of_bytes(data: bytes) -> str:
    """Returns 'sha256:<hexdigest>' for given bytes."""
    return "sha256:" + hashlib.sha256(data).hexdigest()


def sha256_of_file(filepath: str) -> str:
    """
    Computes SHA-256 of a file's raw bytes.
    Reads in 64KB chunks to handle large files.
    Returns hex digest string (no 'sha256:' prefix).
    """
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


# ── Tar creation ──────────────────────────────────────────────────────────────

def create_delta_tar(base_dir: str, paths_to_include: list) -> bytes:
    """
    Creates a tar archive (as raw bytes) from a list of file/dir paths.

    ╔══════════════════════════════════════════════════════╗
    ║  CRITICAL REPRODUCIBILITY RULES — DO NOT CHANGE     ║
    ║  1. Entries added in LEXICOGRAPHICALLY SORTED order  ║
    ║  2. ALL timestamps set to ZERO (mtime = 0)           ║
    ║  3. uid, gid, uname, gname all zeroed                ║
    ║  Same inputs must ALWAYS → same digest               ║
    ╚══════════════════════════════════════════════════════╝

    Args:
        base_dir:          Root directory. Tar entry paths are relative to this.
        paths_to_include:  List of absolute paths to include in the tar.

    Returns:
        Raw tar bytes
    """
    buf = io.BytesIO()

    # RULE 1: Sort all paths lexicographically
    sorted_paths = sorted(set(paths_to_include))

    with tarfile.open(fileobj=buf, mode="w:") as tar:
        for abs_path in sorted_paths:
            if not os.path.exists(abs_path):
                continue

            rel_path = os.path.relpath(abs_path, base_dir)
            tarinfo = tar.gettarinfo(name=abs_path, arcname=rel_path)

            # RULE 2 & 3: Zero everything non-deterministic
            tarinfo.mtime  = 0
            tarinfo.uid    = 0
            tarinfo.gid    = 0
            tarinfo.uname  = ""
            tarinfo.gname  = ""

            if tarinfo.isreg():
                with open(abs_path, "rb") as f:
                    tar.addfile(tarinfo, f)
            else:
                tar.addfile(tarinfo)

    return buf.getvalue()


def collect_all_paths(directory: str) -> list:
    """
    Recursively collects ALL paths (files + dirs) under a directory.
    Visits subdirectories in sorted order for determinism.
    Returns list of absolute paths.
    """
    all_paths = []
    for root, dirs, files in os.walk(directory):
        dirs.sort()  # ensures consistent traversal order
        if root != directory:
            all_paths.append(root)
        for fname in sorted(files):
            all_paths.append(os.path.join(root, fname))
    return all_paths


# ── Layer storage & retrieval ─────────────────────────────────────────────────

def store_layer(tar_bytes: bytes) -> str:
    """
    Saves tar bytes to ~/.docksmith/layers/<sha256hex>.
    Filename IS the digest — content-addressed storage.
    Skips write if layer already exists (layers are immutable).

    Returns digest string 'sha256:<hex>'
    """
    ensure_layers_dir()

    digest = sha256_of_bytes(tar_bytes)
    hex_hash = digest.replace("sha256:", "")
    layer_path = os.path.join(get_layers_dir(), hex_hash)

    if not os.path.exists(layer_path):
        # Write atomically: temp file → rename
        tmp_path = layer_path + ".tmp"
        try:
            with open(tmp_path, "wb") as f:
                f.write(tar_bytes)
            os.rename(tmp_path, layer_path)
        except Exception:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            raise

    return digest


def layer_exists(layer_digest: str) -> bool:
    """Returns True if the layer tar file exists on disk."""
    hex_hash = layer_digest.replace("sha256:", "")
    return os.path.exists(os.path.join(get_layers_dir(), hex_hash))


def get_layer_size(layer_digest: str) -> int:
    """Returns byte size of a stored layer tar file."""
    hex_hash = layer_digest.replace("sha256:", "")
    layer_path = os.path.join(get_layers_dir(), hex_hash)
    if not os.path.exists(layer_path):
        raise FileNotFoundError(
            f"[LAYER ERROR] Layer not found: {layer_digest}\n"
            f"  Expected at: {layer_path}"
        )
    return os.path.getsize(layer_path)


def extract_layer(layer_digest: str, target_dir: str):
    """
    Extracts a stored layer tar into target_dir.
    Later layers overwrite earlier ones at the same path (correct overlay behaviour).
    """
    hex_hash = layer_digest.replace("sha256:", "")
    layer_path = os.path.join(get_layers_dir(), hex_hash)

    if not os.path.exists(layer_path):
        raise FileNotFoundError(
            f"[RUNTIME ERROR] Layer not found: {layer_digest}\n"
            f"  Try rebuilding with --no-cache."
        )

    with tarfile.open(layer_path, "r:") as tar:
        try:
            tar.extractall(path=target_dir, filter="data")
        except TypeError:
            tar.extractall(path=target_dir)


def delete_layer(layer_digest: str):
    """Deletes a layer file from disk. Called by 'docksmith rmi' (Piyush)."""
    hex_hash = layer_digest.replace("sha256:", "")
    layer_path = os.path.join(get_layers_dir(), hex_hash)
    if os.path.exists(layer_path):
        os.remove(layer_path)


# ── File hashing for COPY cache keys (used by Preksha's cache.py) ────────────

def hash_copy_sources(src_pattern: str, context_dir: str) -> list:
    """
    Computes SHA-256 of each source file matched by src_pattern.
    Returns sorted list of 'relative/path:hexdigest' strings.
    Sorted by path so result is deterministic regardless of filesystem order.

    This is fed into Preksha's cache key computation for COPY instructions.
    """
    import glob as glob_module

    if src_pattern == ".":
        matched = []
        for root, dirs, files in os.walk(context_dir):
            dirs.sort()
            for f in sorted(files):
                matched.append(os.path.join(root, f))
    else:
        full_pattern = os.path.join(context_dir, src_pattern)
        matched = sorted(glob_module.glob(full_pattern, recursive=True))

    result = []
    for abs_path in sorted(matched):
        if os.path.isfile(abs_path):
            rel = os.path.relpath(abs_path, context_dir)
            h = sha256_of_file(abs_path)
            result.append(f"{rel}:{h}")

    return sorted(result)


# ── Filesystem snapshot helpers (used by builder.py for RUN delta) ────────────

def snapshot_filesystem(directory: str) -> dict:
    """
    Snapshots a directory as {relative_path: sha256_hex}.
    Used to compute what changed after a RUN command executes.
    """
    snapshot = {}
    for root, dirs, files in os.walk(directory):
        dirs.sort()
        for fname in sorted(files):
            abs_path = os.path.join(root, fname)
            rel_path = os.path.relpath(abs_path, directory)
            try:
                snapshot[rel_path] = sha256_of_file(abs_path)
            except (PermissionError, OSError):
                pass  # skip sockets, device files, etc.
    return snapshot


def compute_delta_paths(before: dict, after: dict, base_dir: str) -> list:
    """
    Returns absolute paths of files that are new or changed in 'after'
    compared to 'before'. Used to create the RUN delta layer.
    """
    changed = []
    for rel_path, new_hash in after.items():
        if rel_path not in before or before[rel_path] != new_hash:
            changed.append(os.path.join(base_dir, rel_path))
    return sorted(changed)
