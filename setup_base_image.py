#!/usr/bin/env python3
"""
One-time base image import utility for Docksmith.

Usage:
  python setup_base_image.py --image alpine:latest --rootfs-dir /path/to/rootfs
  python setup_base_image.py --image alpine:latest --rootfs-tar /path/to/rootfs.tar
  python setup_base_image.py --image alpine:latest --download-url https://.../rootfs.tar
"""

from __future__ import annotations

import argparse
import os
import shutil
import tarfile
import tempfile
import urllib.request
from datetime import datetime, timezone

from docksmith.layers import collect_all_paths, create_delta_tar, store_layer
from docksmith.models import ImageConfig, ImageManifest, LayerEntry
from docksmith.state import save_manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import base rootfs into Docksmith")
    parser.add_argument("--image", default="alpine:latest", help="Image ref: name:tag")
    parser.add_argument("--rootfs-dir", help="Path to unpacked rootfs directory")
    parser.add_argument("--rootfs-tar", help="Path to rootfs tar archive")
    parser.add_argument(
        "--download-url",
        help="Optional URL to download a rootfs tar first (used once during setup)",
    )
    args = parser.parse_args()

    sources = [bool(args.rootfs_dir), bool(args.rootfs_tar), bool(args.download_url)]
    if sum(sources) != 1:
        parser.error("Provide exactly one of --rootfs-dir, --rootfs-tar, or --download-url")
    return args


def split_image_ref(ref: str) -> tuple[str, str]:
    if ":" in ref:
        name, tag = ref.split(":", 1)
    else:
        name, tag = ref, "latest"
    return name.strip(), tag.strip()


def _extract_tar(tar_path: str, out_dir: str) -> None:
    with tarfile.open(tar_path, "r:*") as tar:
        try:
            tar.extractall(path=out_dir, filter="tar")
        except TypeError:
            tar.extractall(path=out_dir)


def _download(url: str, out_path: str) -> None:
    with urllib.request.urlopen(url) as response, open(out_path, "wb") as f:
        shutil.copyfileobj(response, f)


def import_rootfs(image_ref: str, rootfs_dir: str) -> ImageManifest:
    all_paths = collect_all_paths(rootfs_dir)
    tar_bytes = create_delta_tar(rootfs_dir, all_paths)
    digest = store_layer(tar_bytes)

    name, tag = split_image_ref(image_ref)
    manifest = ImageManifest(
        name=name,
        tag=tag,
        digest="",
        created=datetime.now(timezone.utc).isoformat(),
        config=ImageConfig(Env=[], Cmd=["cmd"] if os.name == "nt" else ["/bin/sh"], WorkingDir="/"),
        layers=[
            LayerEntry(
                digest=digest,
                size=len(tar_bytes),
                createdBy="base layer import",
            )
        ],
    )
    return save_manifest(manifest)


def main() -> int:
    args = parse_args()

    with tempfile.TemporaryDirectory(prefix="docksmith_base_") as tmp:
        if args.rootfs_dir:
            rootfs_dir = os.path.abspath(args.rootfs_dir)
        else:
            tar_path = os.path.join(tmp, "rootfs.tar")
            if args.rootfs_tar:
                tar_path = os.path.abspath(args.rootfs_tar)
            else:
                _download(args.download_url, tar_path)

            rootfs_dir = os.path.join(tmp, "rootfs")
            os.makedirs(rootfs_dir, exist_ok=True)
            _extract_tar(tar_path, rootfs_dir)

        saved = import_rootfs(args.image, rootfs_dir)
        short = saved.digest[:19] if saved.digest else "sha256:?"
        print(f"Imported base image {saved.name}:{saved.tag} ({short})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
