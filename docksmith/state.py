import json
import hashlib
import os
from dataclasses import asdict

from docksmith.layers import delete_layer
from docksmith.models import ImageConfig, ImageManifest, LayerEntry
from docksmith.paths import ensure_state_dirs, get_images_dir


def _manifest_filename(name: str, tag: str) -> str:
    return f"{name}:{tag}.json"


def _manifest_path(name: str, tag: str) -> str:
    return os.path.join(get_images_dir(), _manifest_filename(name, tag))


def _compute_manifest_digest(data: dict) -> str:
    canonical = dict(data)
    canonical["digest"] = ""
    encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _manifest_from_dict(data: dict) -> ImageManifest:
    cfg = data.get("config") or {}
    config = ImageConfig(
        Env=list(cfg.get("Env") or []),
        Cmd=list(cfg.get("Cmd") or []),
        WorkingDir=cfg.get("WorkingDir") or "",
    )
    layers = [
        LayerEntry(
            digest=entry["digest"],
            size=int(entry["size"]),
            createdBy=entry["createdBy"],
        )
        for entry in (data.get("layers") or [])
    ]
    return ImageManifest(
        name=data["name"],
        tag=data["tag"],
        digest=data.get("digest", ""),
        created=data["created"],
        config=config,
        layers=layers,
    )


def save_manifest(manifest: ImageManifest) -> ImageManifest:
    ensure_state_dirs()
    payload = asdict(manifest)
    payload["digest"] = _compute_manifest_digest(payload)

    with open(_manifest_path(manifest.name, manifest.tag), "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, sort_keys=True)

    return _manifest_from_dict(payload)


def load_manifest(name: str, tag: str) -> ImageManifest | None:
    ensure_state_dirs()
    path = _manifest_path(name, tag)
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return _manifest_from_dict(json.load(f))


def list_manifests() -> list[ImageManifest]:
    ensure_state_dirs()
    manifests = []
    for fname in sorted(os.listdir(get_images_dir())):
        if not fname.endswith(".json"):
            continue
        path = os.path.join(get_images_dir(), fname)
        with open(path, "r", encoding="utf-8") as f:
            manifests.append(_manifest_from_dict(json.load(f)))
    return manifests


def remove_image(name: str, tag: str) -> bool:
    manifest = load_manifest(name, tag)
    if manifest is None:
        return False

    for layer in manifest.layers:
        delete_layer(layer.digest)

    path = _manifest_path(name, tag)
    if os.path.exists(path):
        os.remove(path)
    return True
