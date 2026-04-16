#!/usr/bin/env python3
# dashboard/data_gen.py
# ============================================================
#  PREKSHA - Dashboard Data Generator
#  Reads ~/.docksmith/ and writes dashboard/data.json
#
#  USAGE:
#    Single run:  python3 dashboard/data_gen.py
#    Watch mode:  python3 dashboard/data_gen.py --watch
#
#  The HTML dashboard polls data.json every 5 s automatically.
#  In --watch mode this script re-generates data.json whenever
#  a new image is built or a container is run (no manual step).
# ============================================================

import os
import sys
import json
import time
import hashlib
import argparse
from datetime import datetime, timezone

DOCKSMITH_DIR = os.path.expanduser("~/.docksmith")
IMAGES_DIR    = os.path.join(DOCKSMITH_DIR, "images")
LAYERS_DIR    = os.path.join(DOCKSMITH_DIR, "layers")
CACHE_DIR     = os.path.join(DOCKSMITH_DIR, "cache")
CACHE_INDEX   = os.path.join(CACHE_DIR, "index.json")
OUTPUT_FILE   = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data.json")

# How often the watcher polls for changes (seconds)
WATCH_INTERVAL = 2


# ── Helpers ──────────────────────────────────────────────────────────────────

def get_dir_size_mb(path):
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


# ── Collectors ───────────────────────────────────────────────────────────────

def collect_images():
    images = []
    if not os.path.exists(IMAGES_DIR):
        return images

    for fname in sorted(os.listdir(IMAGES_DIR)):
        if not fname.endswith(".json"):
            continue
        m = load_manifest(os.path.join(IMAGES_DIR, fname))
        if not m:
            continue

        total_size = 0.0
        for layer in m.get("layers", []):
            digest   = layer.get("digest", "")
            hex_hash = digest.replace("sha256:", "")
            lpath    = os.path.join(LAYERS_DIR, hex_hash)
            total_size += get_file_size_mb(lpath)

        images.append({
            "name":        m.get("name", "unknown"),
            "tag":         m.get("tag", "latest"),
            "digest":      m.get("digest", "")[:19],
            "created":     m.get("created", ""),
            "size_mb":     round(total_size, 2),
            "layer_count": len(m.get("layers", [])),
            "cmd":         m.get("config", {}).get("Cmd", []),
            "workdir":     m.get("config", {}).get("WorkingDir", "/"),
            "env":         m.get("config", {}).get("Env", []),
        })

    return images


def collect_layers():
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
            "digest":  "sha256:" + fname[:12],
            "size_mb": size_mb,
            "created": created,
        })

    layers.sort(key=lambda x: x["size_mb"], reverse=True)
    return layers


def collect_cache_stats():
    stats = {
        "total_keys":    0,
        "hits":          0,
        "misses":        0,
        "hit_rate":      0.0,
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
    stats["index_size_kb"] = round(os.path.getsize(CACHE_INDEX) / 1024, 1) if os.path.exists(CACHE_INDEX) else 0.0

    return stats


def collect_build_log():
    log_path = os.path.join(DOCKSMITH_DIR, "build_log.json")
    if os.path.exists(log_path):
        try:
            with open(log_path, "r") as f:
                return json.load(f)
        except Exception:
            pass

    events = []
    if os.path.exists(IMAGES_DIR):
        for fname in os.listdir(IMAGES_DIR):
            if not fname.endswith(".json"):
                continue
            m = load_manifest(os.path.join(IMAGES_DIR, fname))
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
    return {
        "layers_mb": get_dir_size_mb(LAYERS_DIR),
        "cache_mb":  get_dir_size_mb(CACHE_DIR),
        "images_mb": get_dir_size_mb(IMAGES_DIR),
        "total_mb":  get_dir_size_mb(DOCKSMITH_DIR),
    }


# ── Core generate function ────────────────────────────────────────────────────

def generate():
    """Read ~/.docksmith/ and write dashboard/data.json."""
    data = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "images":       collect_images(),
        "layers":       collect_layers(),
        "cache":        collect_cache_stats(),
        "build_log":    collect_build_log(),
        "storage":      collect_storage_summary(),
    }

    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, "w") as f:
        json.dump(data, f, indent=2)

    return data


# ── Watcher: detect changes in ~/.docksmith/ ─────────────────────────────────

def _snapshot_docksmith():
    """
    Return a dict of {filepath: mtime} for every file under ~/.docksmith/.
    Used to detect when images or layers are added/removed.
    """
    snapshot = {}
    if not os.path.exists(DOCKSMITH_DIR):
        return snapshot
    for root, dirs, files in os.walk(DOCKSMITH_DIR):
        for f in files:
            fp = os.path.join(root, f)
            try:
                snapshot[fp] = os.path.getmtime(fp)
            except OSError:
                pass
    return snapshot


def watch():
    """
    Poll ~/.docksmith/ every WATCH_INTERVAL seconds.
    Re-generate data.json whenever any file changes (new image, new layer, etc.).
    The dashboard HTML polls data.json every 5 s, so changes appear automatically.
    """
    print(f"[ data_gen --watch ] watching {DOCKSMITH_DIR} for changes ...")
    print(f"  dashboard will auto-refresh from {OUTPUT_FILE}")
    print("  Press Ctrl+C to stop.\n")

    last_snapshot = {}

    while True:
        current_snapshot = _snapshot_docksmith()

        if current_snapshot != last_snapshot:
            ts = datetime.now().strftime("%H:%M:%S")
            print(f"[{ts}] change detected — regenerating data.json ...", end=" ", flush=True)
            try:
                data = generate()
                print(f"ok  ({len(data['images'])} images, {len(data['layers'])} layers)")
            except Exception as e:
                print(f"ERROR: {e}")
            last_snapshot = current_snapshot

        time.sleep(WATCH_INTERVAL)


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Generate dashboard/data.json from ~/.docksmith/"
    )
    parser.add_argument(
        "--watch", "-w",
        action="store_true",
        help="Stay running and re-generate whenever ~/.docksmith/ changes",
    )
    args = parser.parse_args()

    if args.watch:
        try:
            watch()
        except KeyboardInterrupt:
            print("\n[ data_gen ] stopped.")
    else:
        # Single-shot mode (original behaviour)
        print("[ docksmith data_gen ] reading ~/.docksmith/ ...")
        data = generate()
        print(f"[ docksmith data_gen ] wrote {OUTPUT_FILE}")
        print(f"  images  : {len(data['images'])}")
        print(f"  layers  : {len(data['layers'])}")
        print(f"  cache   : {data['cache']['hit_rate']}% hit rate")
        print(f"  storage : {data['storage']['total_mb']} MB total")
        print("[ docksmith data_gen ] done. Open dashboard/dashboard.html in your browser.")


if __name__ == "__main__":
    main()