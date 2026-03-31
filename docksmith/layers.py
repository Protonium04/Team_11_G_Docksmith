# docksmith/layers.py
# ============================================================
#  PROTHAM — File 2: Layer Creation & Storage
# ============================================================

import os
import io
import tarfile
import hashlib
import shutil
import tempfile

LAYERS_DIR = os.path.expanduser("~/.docksmith/layers")


def ensure_layers_dir():
    os.makedirs(LAYERS_DIR, exist_ok=True)


def sha256_of_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def sha256_of_file(filepath: str) -> str:
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def create_delta_tar(base_dir: str, paths_to_include: list) -> bytes:
    """
    Creates a reproducible tar archive.
    CRITICAL: sorted entries + zeroed timestamps.
    """
    buf = io.BytesIO()
    sorted_paths = sorted(set(paths_to_include))

    with tarfile.open(fileobj=buf, mode="w:") as tar:
        for abs_path in sorted_paths:
            if not os.path.exists(abs_path):
                continue
            rel_path = os.path.relpath(abs_path, base_dir)
            tarinfo  = tar.gettarinfo(name=abs_path, arcname=rel_path)
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
    all_paths = []
    for root, dirs, files in os.walk(directory):
        dirs.sort()
        if root != directory:
            all_paths.append(root)
        for fname in sorted(files):
            all_paths.append(os.path.join(root, fname))
    return all_paths


def store_layer(tar_bytes: bytes) -> str:
    ensure_layers_dir()
    digest   = sha256_of_bytes(tar_bytes)
    hex_hash = digest.replace("sha256:", "")
    layer_path = os.path.join(LAYERS_DIR, hex_hash)

    if not os.path.exists(layer_path):
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
    hex_hash = layer_digest.replace("sha256:", "")
    return os.path.exists(os.path.join(LAYERS_DIR, hex_hash))


def get_layer_size(layer_digest: str) -> int:
    hex_hash   = layer_digest.replace("sha256:", "")
    layer_path = os.path.join(LAYERS_DIR, hex_hash)
    if not os.path.exists(layer_path):
        raise FileNotFoundError(f"[LAYER ERROR] Layer not found: {layer_digest}")
    return os.path.getsize(layer_path)


def extract_layer(layer_digest: str, target_dir: str):
    hex_hash   = layer_digest.replace("sha256:", "")
    layer_path = os.path.join(LAYERS_DIR, hex_hash)
    if not os.path.exists(layer_path):
        raise FileNotFoundError(f"[RUNTIME ERROR] Layer not found: {layer_digest}")
    with tarfile.open(layer_path, "r:") as tar:
        try:
            tar.extractall(path=target_dir, filter="data")
        except TypeError:
            tar.extractall(path=target_dir)


def delete_layer(layer_digest: str):
    hex_hash   = layer_digest.replace("sha256:", "")
    layer_path = os.path.join(LAYERS_DIR, hex_hash)
    if os.path.exists(layer_path):
        os.remove(layer_path)


def hash_copy_sources(src_pattern: str, context_dir: str) -> list:
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
            h   = sha256_of_file(abs_path)
            result.append(f"{rel}:{h}")
    return sorted(result)


def snapshot_filesystem(directory: str) -> dict:
    snapshot = {}
    for root, dirs, files in os.walk(directory):
        dirs.sort()
        for fname in sorted(files):
            abs_path = os.path.join(root, fname)
            rel_path = os.path.relpath(abs_path, directory)
            try:
                snapshot[rel_path] = sha256_of_file(abs_path)
            except (PermissionError, OSError):
                pass
    return snapshot


def compute_delta_paths(before: dict, after: dict, base_dir: str) -> list:
    changed = []
    for rel_path, new_hash in after.items():
        if rel_path not in before or before[rel_path] != new_hash:
            changed.append(os.path.join(base_dir, rel_path))
    return sorted(changed)
