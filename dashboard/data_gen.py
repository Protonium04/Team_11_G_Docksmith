# dashboard/data_gen.py
# ============================================================
#  PREKSHA — Dashboard Data Generator
#  Reads ~/.docksmith/ and writes dashboard/data.json
#  Run: python3 dashboard/data_gen.py
#  Then open dashboard/dashboard.html in browser
# ============================================================

import os
import json
import hashlib
import tarfile
import glob
from datetime import datetime, timezone

DOCKSMITH_DIR = os.path.expanduser("~/.docksmith")
IMAGES_DIR    = os.path.join(DOCKSMITH_DIR, "images")
LAYERS_DIR    = os.path.join(DOCKSMITH_DIR, "layers")
CACHE_DIR     = os.path.join(DOCKSMITH_DIR, "cache")
CACHE_INDEX   = os.path.join(CACHE_DIR, "index.json")
OUTPUT_FILE   = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data.json")


def get_dir_size_mb(path):
    """Returns total size of all files in a directory in MB."""
    total = 0
    if not os.path.exists(path):
        return 0.0
    for root, dirs, files in os.walk(path):
        for f in files:
            fp = os.path.join(root, f)
            try:
                total += os.path.getsize(fp)
            except OSError:
                pass
    return round(total / (1024 * 1024), 2)


def get_file_size_mb(path):
    try:
        return round(os.path.getsize(path) / (1024 * 1024), 2)
    except OSError:
        return 0.0


def load_manifest(manifest_path):
    try:
        with open(manifest_path, "r") as f:
            return json.load(f)
    except Exception:
        return None


def collect_images():
    """Reads all image manifests from ~/.docksmith/images/<name>/<tag>.json"""
    images = []
    if not os.path.exists(IMAGES_DIR):
        return images

    for name_dir in sorted(os.listdir(IMAGES_DIR)):
        name_path = os.path.join(IMAGES_DIR, name_dir)
        if not os.path.isdir(name_path):
            continue
        for fname in sorted(os.listdir(name_path)):
            if not fname.endswith(".json"):
                continue
            path = os.path.join(name_path, fname)
            m = load_manifest(path)
            if not m:
                continue

            # Compute total size from layers
            total_size = 0.0
            for layer in m.get("layers", []):
                digest = layer.get("digest", "")
                hex_hash = digest.replace("sha256:", "")
                lpath = os.path.join(LAYERS_DIR, hex_hash)
                total_size += get_file_size_mb(lpath)

            images.append({
                "name":       m.get("name", "unknown"),
                "tag":        m.get("tag", "latest"),
                "digest":     m.get("digest", "")[:19],
                "created":    m.get("created", ""),
                "size_mb":    round(total_size, 2),
                "layer_count": len(m.get("layers", [])),
                "cmd":        m.get("config", {}).get("Cmd", []),
                "workdir":    m.get("config", {}).get("WorkingDir", "/"),
                "env":        m.get("config", {}).get("Env", []),
            })

    return images


def collect_layers():
    """Reads all layer files from ~/.docksmith/layers/"""
    layers = []
    if not os.path.exists(LAYERS_DIR):
        return layers

    for fname in sorted(os.listdir(LAYERS_DIR)):
        fpath = os.path.join(LAYERS_DIR, fname)
        if not os.path.isfile(fpath):
            continue
        size_mb = get_file_size_mb(fpath)
        mtime   = os.path.getmtime(fpath)
        created = datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()
        layers.append({
            "digest":   "sha256:" + fname[:12],
            "size_mb":  size_mb,
            "created":  created,
        })

    # Sort by size descending
    layers.sort(key=lambda x: x["size_mb"], reverse=True)
    return layers


def collect_cache_stats():
    """Reads cache index and computes hit/miss/total stats."""
    stats = {
        "total_keys":  0,
        "hits":        0,
        "misses":      0,
        "hit_rate":    0.0,
        "index_size_kb": 0.0,
    }

    if not os.path.exists(CACHE_INDEX):
        return stats

    try:
        with open(CACHE_INDEX, "r") as f:
            index = json.load(f)
    except Exception:
        return stats

    total     = len(index)
    hit_count = 0

    for key, digest in index.items():
        hex_hash = digest.replace("sha256:", "")
        lpath    = os.path.join(LAYERS_DIR, hex_hash)
        if os.path.exists(lpath):
            hit_count += 1

    miss_count = total - hit_count
    hit_rate   = round((hit_count / total * 100), 1) if total > 0 else 0.0

    stats["total_keys"]    = total
    stats["hits"]          = hit_count
    stats["misses"]        = miss_count
    stats["hit_rate"]      = hit_rate
    stats["index_size_kb"] = round(get_file_size_mb(CACHE_INDEX) * 1024, 1)

    return stats


def collect_build_log():
    """
    Reads build log from ~/.docksmith/build_log.json if it exists.
    Falls back to scanning manifest created timestamps.
    """
    log_path = os.path.join(DOCKSMITH_DIR, "build_log.json")
    if os.path.exists(log_path):
        try:
            with open(log_path, "r") as f:
                return json.load(f)
        except Exception:
            pass

    # Fallback: synthesise log from manifest created times
    events = []
    if os.path.exists(IMAGES_DIR):
        for name_dir in os.listdir(IMAGES_DIR):
            name_path = os.path.join(IMAGES_DIR, name_dir)
            if not os.path.isdir(name_path):
                continue
            for fname in os.listdir(name_path):
                if not fname.endswith(".json"):
                    continue
                m = load_manifest(os.path.join(name_path, fname))
                if not m:
                    continue
                events.append({
                    "time":    m.get("created", ""),
                    "image":   f"{m.get('name','')}:{m.get('tag','')}",
                    "message": "built successfully",
                    "status":  "built",
                })

    events.sort(key=lambda x: x.get("time", ""), reverse=True)
    return events[:20]


def collect_storage_summary():
    """Overall storage breakdown."""
    return {
        "layers_mb": get_dir_size_mb(LAYERS_DIR),
        "cache_mb":  get_dir_size_mb(CACHE_DIR),
        "images_mb": get_dir_size_mb(IMAGES_DIR),
        "total_mb":  get_dir_size_mb(DOCKSMITH_DIR),
    }


def main():
    print("[ docksmith data_gen ] reading ~/.docksmith/ ...")

    data = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "images":        collect_images(),
        "layers":        collect_layers(),
        "cache":         collect_cache_stats(),
        "build_log":     collect_build_log(),
        "storage":       collect_storage_summary(),
    }

    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, "w") as f:
        json.dump(data, f, indent=2)

    print(f"[ docksmith data_gen ] wrote {OUTPUT_FILE}")
    print(f"  images  : {len(data['images'])}")
    print(f"  layers  : {len(data['layers'])}")
    print(f"  cache   : {data['cache']['hit_rate']}% hit rate")
    print(f"  storage : {data['storage']['total_mb']} MB total")
    print("[ docksmith data_gen ] done. open dashboard.html in browser.")


if __name__ == "__main__":
    main()