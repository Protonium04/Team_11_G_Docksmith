import argparse
import os
import tarfile
import tempfile
from datetime import datetime, timezone

from docksmith.layers import collect_all_paths, create_delta_tar, store_layer
from docksmith.models import ImageConfig, ImageManifest, LayerEntry
from docksmith.paths import ensure_state_dirs
from docksmith.state import save_manifest


def _import_rootfs_dir(image_name: str, rootfs_dir: str) -> None:
    all_paths = collect_all_paths(rootfs_dir)
    tar_bytes = create_delta_tar(rootfs_dir, all_paths)
    digest = store_layer(tar_bytes)

    manifest = ImageManifest(
        name=image_name.split(":", 1)[0],
        tag=image_name.split(":", 1)[1] if ":" in image_name else "latest",
        digest="",
        created=datetime.now(timezone.utc).isoformat(),
        config=ImageConfig(
            Env=[],
            Cmd=["/bin/sh"],
            WorkingDir="/",
        ),
        layers=[
            LayerEntry(
                digest=digest,
                size=len(tar_bytes),
                createdBy="base layer import",
            )
        ],
    )
    saved = save_manifest(manifest)
    print(f"Imported base image {saved.name}:{saved.tag} ({saved.digest[:19]})")


def _extract_tar_to_temp(tar_path: str) -> str:
    tmp = tempfile.mkdtemp(prefix="docksmith_base_")
    with tarfile.open(tar_path, "r:*") as tar:
        try:
            tar.extractall(path=tmp, filter="data")
        except TypeError:
            tar.extractall(path=tmp)
    return tmp


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Import a local rootfs into Docksmith as a base image."
    )
    parser.add_argument(
        "--image",
        default="alpine:latest",
        help="Image reference to create (default: alpine:latest)",
    )
    parser.add_argument(
        "--rootfs-dir",
        help="Path to unpacked root filesystem directory",
    )
    parser.add_argument(
        "--rootfs-tar",
        help="Path to root filesystem tar archive",
    )
    args = parser.parse_args()

    if bool(args.rootfs_dir) == bool(args.rootfs_tar):
        raise SystemExit("Provide exactly one of --rootfs-dir or --rootfs-tar")

    ensure_state_dirs()
    if args.rootfs_dir:
        _import_rootfs_dir(args.image, args.rootfs_dir)
        return 0

    extracted = _extract_tar_to_temp(args.rootfs_tar)
    _import_rootfs_dir(args.image, extracted)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
