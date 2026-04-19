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
