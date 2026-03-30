# # docksmith/state.py
# # ============================================================
# #  PIYUSH — File 2: State Management
# #  Manages ~/.docksmith/ directory layout
# #  Manifest read/write + digest computation
# # ============================================================

# import os
# import json
# import hashlib
# from docksmith.models import ImageManifest, LayerEntry, ImageConfig
# from docksmith.paths import get_docksmith_dir

# # ── Directory layout ──────────────────────────────────────────────────────────
# DOCKSMITH_DIR = get_docksmith_dir()
# IMAGES_DIR    = os.path.join(DOCKSMITH_DIR, "images")
# LAYERS_DIR    = os.path.join(DOCKSMITH_DIR, "layers")
# CACHE_DIR     = os.path.join(DOCKSMITH_DIR, "cache")


# def ensure_dirs():
#     """Creates all required ~/.docksmith subdirectories."""
#     os.makedirs(IMAGES_DIR, exist_ok=True)
#     os.makedirs(LAYERS_DIR, exist_ok=True)
#     os.makedirs(CACHE_DIR,  exist_ok=True)


# # ── Manifest serialization ────────────────────────────────────────────────────

# def _manifest_to_dict(manifest: ImageManifest) -> dict:
#     """Converts ImageManifest to a plain dict for JSON serialization."""
#     return {
#         "name":    manifest.name,
#         "tag":     manifest.tag,
#         "digest":  manifest.digest,
#         "created": manifest.created,
#         "config": {
#             "Env":        manifest.config.Env,
#             "Cmd":        manifest.config.Cmd,
#             "WorkingDir": manifest.config.WorkingDir,
#         },
#         "layers": [
#             {
#                 "digest":    layer.digest,
#                 "size":      layer.size,
#                 "createdBy": layer.createdBy,
#             }
#             for layer in manifest.layers
#         ],
#     }


# def _dict_to_manifest(data: dict) -> ImageManifest:
#     """Converts a plain dict (loaded from JSON) back to an ImageManifest."""
#     config = ImageConfig(
#         Env        = data["config"].get("Env", []),
#         Cmd        = data["config"].get("Cmd", []),
#         WorkingDir = data["config"].get("WorkingDir", ""),
#     )
#     layers = [
#         LayerEntry(
#             digest    = l["digest"],
#             size      = l["size"],
#             createdBy = l.get("createdBy", ""),
#         )
#         for l in data.get("layers", [])
#     ]
#     return ImageManifest(
#         name    = data["name"],
#         tag     = data["tag"],
#         digest  = data["digest"],
#         created = data["created"],
#         config  = config,
#         layers  = layers,
#     )


# def _compute_manifest_digest(manifest: ImageManifest) -> str:
#     """
#     Computes the SHA-256 digest of a manifest.

#     HOW IT WORKS:
#     1. Serialize manifest to JSON with digest field set to ""
#     2. Hash the resulting bytes
#     3. That hash becomes the manifest's digest

#     This means the digest is content-addressed — same image = same digest.
#     """
#     data = _manifest_to_dict(manifest)
#     data["digest"] = ""   # zero out digest field before hashing
#     serialized = json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")
#     return "sha256:" + hashlib.sha256(serialized).hexdigest()


# # ── Manifest file path ────────────────────────────────────────────────────────

# def _manifest_path(name: str, tag: str) -> str:
#     """Returns the file path for a manifest: ~/.docksmith/images/<name>/<tag>.json"""
#     return os.path.join(IMAGES_DIR, name, f"{tag}.json")


# # ── Core operations ───────────────────────────────────────────────────────────

# def save_manifest(manifest: ImageManifest) -> ImageManifest:
#     """
#     Saves a manifest to disk after computing its digest.
#     Creates directory if it doesn't exist.
#     Returns the manifest with digest field filled in.
#     """
#     ensure_dirs()

#     # Compute the real digest
#     manifest.digest = _compute_manifest_digest(manifest)

#     path = _manifest_path(manifest.name, manifest.tag)
#     os.makedirs(os.path.dirname(path), exist_ok=True)

#     data = _manifest_to_dict(manifest)
#     with open(path, "w") as f:
#         json.dump(data, f, indent=2)

#     return manifest


# def load_manifest(name: str, tag: str) -> ImageManifest | None:
#     """
#     Loads a manifest from disk.
#     Returns None if not found (instead of raising — callers handle missing images).
#     """
#     path = _manifest_path(name, tag)
#     if not os.path.exists(path):
#         return None
#     with open(path, "r") as f:
#         data = json.load(f)
#     return _dict_to_manifest(data)


# def list_manifests() -> list[ImageManifest]:
#     """
#     Lists all stored images by scanning ~/.docksmith/images/.
#     Returns list of ImageManifest objects, sorted by name+tag.
#     """
#     ensure_dirs()
#     results = []

#     if not os.path.exists(IMAGES_DIR):
#         return results

#     for name in sorted(os.listdir(IMAGES_DIR)):
#         name_dir = os.path.join(IMAGES_DIR, name)
#         if not os.path.isdir(name_dir):
#             continue
#         for fname in sorted(os.listdir(name_dir)):
#             if fname.endswith(".json"):
#                 tag = fname[:-5]   # strip .json
#                 manifest = load_manifest(name, tag)
#                 if manifest:
#                     results.append(manifest)

#     return results


# def delete_manifest(name: str, tag: str) -> list[str]:
#     """
#     Deletes a manifest file from disk.
#     Returns the list of layer digests that WERE in this image,
#     so the caller can decide whether to delete the layer files too.
#     Raises FileNotFoundError if image not found.
#     """
#     manifest = load_manifest(name, tag)
#     if manifest is None:
#         raise FileNotFoundError(
#             f"[ERROR] Image '{name}:{tag}' not found.\n"
#             f"  Run 'docksmith images' to see available images."
#         )

#     layer_digests = [layer.digest for layer in manifest.layers]

#     path = _manifest_path(name, tag)
#     os.remove(path)

#     # Clean up empty directory
#     name_dir = os.path.dirname(path)
#     if os.path.exists(name_dir) and not os.listdir(name_dir):
#         os.rmdir(name_dir)

#     return layer_digests


# def image_exists(name: str, tag: str) -> bool:
#     """Returns True if the image manifest exists on disk."""
#     return os.path.exists(_manifest_path(name, tag))


# docksmith/state.py
# ============================================================
#  PIYUSH — ~/.docksmith/ directory helpers, manifest I/O
# ============================================================

import os
import json
import hashlib
from docksmith.models import ImageManifest, ImageConfig, LayerEntry

DOCKSMITH_DIR = os.path.expanduser("~/.docksmith")
IMAGES_DIR    = os.path.join(DOCKSMITH_DIR, "images")
LAYERS_DIR    = os.path.join(DOCKSMITH_DIR, "layers")
CACHE_DIR     = os.path.join(DOCKSMITH_DIR, "cache")


def ensure_dirs():
    for d in [IMAGES_DIR, LAYERS_DIR, CACHE_DIR]:
        os.makedirs(d, exist_ok=True)


def _manifest_filename(name: str, tag: str) -> str:
    safe_name = name.replace("/", "_").replace(":", "_")
    return os.path.join(IMAGES_DIR, f"{safe_name}_{tag}.json")


def _manifest_to_dict(m: ImageManifest) -> dict:
    return {
        "name":    m.name,
        "tag":     m.tag,
        "digest":  m.digest,
        "created": m.created,
        "config": {
            "Env":        m.config.Env,
            "Cmd":        m.config.Cmd,
            "WorkingDir": m.config.WorkingDir,
        },
        "layers": [
            {"digest": l.digest, "size": l.size, "createdBy": l.createdBy}
            for l in m.layers
        ],
    }


def _dict_to_manifest(d: dict) -> ImageManifest:
    cfg = d.get("config", {})
    return ImageManifest(
        name    = d["name"],
        tag     = d["tag"],
        digest  = d.get("digest", ""),
        created = d.get("created", ""),
        config  = ImageConfig(
            Env       = cfg.get("Env", []),
            Cmd       = cfg.get("Cmd", []),
            WorkingDir= cfg.get("WorkingDir", ""),
        ),
        layers  = [
            LayerEntry(
                digest    = l["digest"],
                size      = l.get("size", 0),
                createdBy = l.get("createdBy", ""),
            )
            for l in d.get("layers", [])
        ],
    )


def _compute_manifest_digest(d: dict) -> str:
    """SHA-256 of the manifest JSON with digest field set to empty string."""
    tmp = dict(d)
    tmp["digest"] = ""
    serialised = json.dumps(tmp, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(serialised.encode()).hexdigest()


def save_manifest(m: ImageManifest) -> ImageManifest:
    ensure_dirs()
    d = _manifest_to_dict(m)
    d["digest"] = _compute_manifest_digest(d)
    m.digest = d["digest"]

    path = _manifest_filename(m.name, m.tag)
    with open(path, "w") as f:
        json.dump(d, f, indent=2)
    return m


def load_manifest(name: str, tag: str):
    ensure_dirs()
    path = _manifest_filename(name, tag)
    if not os.path.exists(path):
        return None
    try:
        with open(path) as f:
            return _dict_to_manifest(json.load(f))
    except Exception:
        return None


def list_manifests():
    ensure_dirs()
    manifests = []
    for fname in sorted(os.listdir(IMAGES_DIR)):
        if fname.endswith(".json"):
            try:
                with open(os.path.join(IMAGES_DIR, fname)) as f:
                    manifests.append(_dict_to_manifest(json.load(f)))
            except Exception:
                pass
    return manifests


def delete_manifest(name: str, tag: str) -> bool:
    path = _manifest_filename(name, tag)
    if not os.path.exists(path):
        return False
    os.remove(path)
    return True
