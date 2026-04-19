#!/usr/bin/env python3
# setup_base_image.py
# ============================================================
#  PRANAV — One-time base image import script
#  Imports a minimal Python base image into ~/.docksmith/
#  Run ONCE before any builds: python3 setup_base_image.py
# ============================================================

import os
import sys
import json
import tarfile
import io
import hashlib
import subprocess
import tempfile
import shutil
from datetime import datetime, timezone

DOCKSMITH_DIR = os.path.expanduser("~/.docksmith")
IMAGES_DIR    = os.path.join(DOCKSMITH_DIR, "images")
LAYERS_DIR    = os.path.join(DOCKSMITH_DIR, "layers")


def ensure_dirs():
    for d in [IMAGES_DIR, LAYERS_DIR]:
        os.makedirs(d, exist_ok=True)


def sha256_of_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def sha256_of_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return "sha256:" + h.hexdigest()


def create_minimal_layer(files: dict) -> bytes:
    """
    Creates a tar layer from a {arcname: bytes} dict.
    Sorted entries, zeroed timestamps — reproducible.
    """
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:") as tar:
        for arcname in sorted(files.keys()):
            data     = files[arcname]
            tarinfo  = tarfile.TarInfo(name=arcname)
            tarinfo.size   = len(data)
            tarinfo.mtime  = 0
            tarinfo.uid    = 0
            tarinfo.gid    = 0
            tarinfo.uname  = ""
            tarinfo.gname  = ""
            tarinfo.mode   = 0o755 if arcname.startswith("bin/") or arcname.startswith("usr/bin/") else 0o644
            tar.addfile(tarinfo, io.BytesIO(data))
    return buf.getvalue()


def store_layer(tar_bytes: bytes) -> str:
    ensure_dirs()
    digest   = sha256_of_bytes(tar_bytes)
    hex_hash = digest.replace("sha256:", "")
    path     = os.path.join(LAYERS_DIR, hex_hash)
    if not os.path.exists(path):
        with open(path, "wb") as f:
            f.write(tar_bytes)
    return digest


def save_manifest(name: str, tag: str, layers_info: list, config: dict):
    """Writes a manifest JSON to ~/.docksmith/images/"""
    ensure_dirs()
    manifest = {
        "name":    name,
        "tag":     tag,
        "digest":  "",
        "created": datetime.now(timezone.utc).isoformat(),
        "config":  config,
        "layers":  layers_info,
    }
    # compute digest
    tmp = dict(manifest)
    tmp["digest"] = ""
    serialised = json.dumps(tmp, sort_keys=True, separators=(",", ":"))
    manifest["digest"] = "sha256:" + hashlib.sha256(serialised.encode()).hexdigest()

    safe = name.replace("/", "_").replace(":", "_")
    path = os.path.join(IMAGES_DIR, f"{safe}_{tag}.json")
    with open(path, "w") as f:
        json.dump(manifest, f, indent=2)
    print(f"  ✓ Saved manifest: {path}")
    print(f"  ✓ Digest: {manifest['digest'][:32]}...")
    return manifest


def _find_host_binaries(names: list) -> dict:
    """
    Locate real binaries on the host system.
    Returns {arcname: host_path} e.g. {"bin/sh": "/usr/bin/dash", "usr/bin/python3": "/usr/bin/python3.12"}
    """
    found = {}
    for name in names:
        path = shutil.which(name)
        if path is None:
            # Try common locations
            for prefix in ["/bin", "/usr/bin", "/usr/local/bin", "/sbin", "/usr/sbin"]:
                candidate = os.path.join(prefix, name)
                if os.path.exists(candidate):
                    path = os.path.realpath(candidate)
                    break
        if path:
            path = os.path.realpath(path)  # resolve symlinks
            # Determine arcname: keep standard FHS location
            if name in ("sh", "bash", "dash", "echo", "cat", "ls", "mkdir",
                        "rm", "cp", "mv", "chmod"):
                found[f"bin/{name}"] = path
            elif name == "env":
                found["usr/bin/env"] = path
            else:
                found[f"usr/bin/{name}"] = path
            # Also ensure /bin/sh exists (map dash/bash to bin/sh)
            if name in ("dash", "bash", "sh") and "bin/sh" not in found:
                found["bin/sh"] = path
    return found


def _get_shared_libs(binary_path: str) -> list:
    """Use ldd to find shared libraries needed by a binary."""
    libs = []
    try:
        result = subprocess.run(["ldd", binary_path], capture_output=True, text=True, timeout=5)
        for line in result.stdout.splitlines():
            line = line.strip()
            # Format: "libfoo.so.1 => /lib/x86_64-linux-gnu/libfoo.so.1 (0x...)"
            if "=>" in line and "not found" not in line:
                parts = line.split("=>")
                if len(parts) == 2:
                    lib_path = parts[1].strip().split("(")[0].strip()
                    if lib_path and os.path.exists(lib_path):
                        libs.append(os.path.realpath(lib_path))
            # Format: "/lib64/ld-linux-x86-64.so.2 (0x...)" (no =>)
            elif line.startswith("/") and "(" in line:
                lib_path = line.split("(")[0].strip()
                if os.path.exists(lib_path):
                    libs.append(os.path.realpath(lib_path))
    except Exception:
        pass
    return libs


def _copy_binaries_into_rootfs(binaries: dict, rootfs: str):
    """
    Copy binaries and ALL their shared library dependencies into rootfs.
    For python3, also copies the entire stdlib (including C extension .so modules)
    and resolves their shared library dependencies too.
    This ensures commands work inside a chroot.
    """
    # Collect all files to copy: binaries + their libs
    files_to_copy = {}  # {arcname: host_path}
    all_so_files = []   # track all .so files to resolve deps from

    for arcname, host_path in binaries.items():
        files_to_copy[arcname] = host_path
        all_so_files.append(host_path)

    # ── If python3 is among the binaries, also copy its stdlib ────────────
    python_path = binaries.get("usr/bin/python3")
    if python_path:
        try:
            # Ask python where its stdlib lives
            result = subprocess.run(
                [python_path, "-c",
                 "import sys, sysconfig; "
                 "print(sysconfig.get_path('stdlib')); "
                 "print(sysconfig.get_path('platstdlib')); "
                 "print(sysconfig.get_path('purelib')); "
                 "print(sysconfig.get_path('platlib')); "
                 "print(sys.prefix)"],
                capture_output=True, text=True, timeout=10
            )
            paths = [p.strip() for p in result.stdout.strip().splitlines() if p.strip()]
            # Deduplicate and only copy paths that exist
            copied_dirs = set()
            for py_dir in paths:
                py_dir = os.path.realpath(py_dir)
                if py_dir in copied_dirs or not os.path.isdir(py_dir):
                    continue
                copied_dirs.add(py_dir)
                print(f"    → Copying Python dir: {py_dir}")
                for dirpath, dirnames, filenames in os.walk(py_dir):
                    dirnames.sort()
                    # Skip __pycache__, test dirs, and large optional packages to keep size down
                    dirnames[:] = [d for d in dirnames
                                   if d not in ("__pycache__", "test", "tests",
                                                "idle_test", "tkinter", "turtledemo")]
                    for fname in sorted(filenames):
                        src = os.path.join(dirpath, fname)
                        if not os.path.isfile(src):
                            continue
                        arc = os.path.relpath(src, "/")
                        files_to_copy[arc] = src
                        if fname.endswith(".so"):
                            all_so_files.append(src)
        except Exception as e:
            print(f"    ⚠ Could not detect Python stdlib: {e}")

    # ── Resolve shared library dependencies for ALL binaries + .so modules ─
    lib_files = {}
    for so_path in all_so_files:
        for lib_path in _get_shared_libs(so_path):
            lib_arc = lib_path.lstrip("/")
            lib_files[lib_arc] = lib_path

    files_to_copy.update(lib_files)

    # Also get the dynamic linker itself (critical for ELF execution)
    for ld_path in ["/lib64/ld-linux-x86-64.so.2", "/lib/ld-linux-aarch64.so.1",
                    "/lib/ld-linux.so.2"]:
        real = os.path.realpath(ld_path) if os.path.exists(ld_path) else None
        if real and os.path.exists(real):
            files_to_copy[ld_path.lstrip("/")] = real
            break

    print(f"    → Copying {len(files_to_copy)} files into rootfs ...")

    # Copy everything
    for arcname, host_path in sorted(files_to_copy.items()):
        dest = os.path.join(rootfs, arcname)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        try:
            shutil.copy2(host_path, dest)
            os.chmod(dest, 0o755)
        except Exception as e:
            pass  # silently skip unreadable files


def _tar_directory(rootfs: str) -> bytes:
    """
    Create a reproducible tar from a directory (sorted entries, zeroed timestamps).
    Uses scandir instead of os.walk so directory-symlinks (bin -> usr/bin, etc.)
    are preserved in the tar.
    """
    all_files = []

    def _walk(path: str):
        try:
            entries = sorted(os.scandir(path), key=lambda e: e.name)
        except PermissionError:
            return
        for entry in entries:
            all_files.append(entry.path)
            if entry.is_dir(follow_symlinks=False):
                _walk(entry.path)

    _walk(rootfs)

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:") as tar:
        for abs_path in sorted(all_files):
            rel = os.path.relpath(abs_path, rootfs)
            try:
                ti = tar.gettarinfo(abs_path, arcname=rel)
            except Exception:
                continue
            ti.mtime = 0; ti.uid = 0; ti.gid = 0; ti.uname = ""; ti.gname = ""
            if ti.isreg():
                with open(abs_path, "rb") as fh:
                    tar.addfile(ti, fh)
            else:
                tar.addfile(ti)
    return buf.getvalue()


def import_python_slim():
    """
    Tries to import python:3.11-slim from the host Docker daemon.
    Falls back to creating a minimal stub if Docker is unavailable.
    """
    print("\n[setup] Importing python:3.11-slim base image...")

    # Try Docker export first
    if shutil.which("docker"):
        try:
            print("  → Docker found — pulling and exporting python:3.11-slim ...")
            subprocess.run(["docker", "pull", "python:3.11-slim"], check=True, capture_output=True)

            with tempfile.TemporaryDirectory() as tmpdir:
                tar_path  = os.path.join(tmpdir, "image.tar")
                layer_dir = os.path.join(tmpdir, "layer")
                os.makedirs(layer_dir)

                subprocess.run(["docker", "save", "-o", tar_path, "python:3.11-slim"], check=True, capture_output=True)

                # Extract all layer tars and merge
                merged_files = {}
                with tarfile.open(tar_path) as outer:
                    manifest_json = json.loads(outer.extractfile("manifest.json").read())
                    layers_list   = manifest_json[0]["Layers"]
                    for layer_path in layers_list:
                        layer_tar = outer.extractfile(layer_path)
                        with tarfile.open(fileobj=layer_tar) as lt:
                            lt.extractall(layer_dir)

                # Re-tar the merged rootfs with zeroed timestamps
                all_files = []
                for root, dirs, files in os.walk(layer_dir):
                    dirs.sort()
                    for fname in sorted(files):
                        all_files.append(os.path.join(root, fname))

                buf = io.BytesIO()
                with tarfile.open(fileobj=buf, mode="w:") as tar:
                    for abs_path in sorted(all_files):
                        rel = os.path.relpath(abs_path, layer_dir)
                        ti  = tar.gettarinfo(abs_path, arcname=rel)
                        ti.mtime = 0; ti.uid = 0; ti.gid = 0; ti.uname = ""; ti.gname = ""
                        if ti.isreg():
                            with open(abs_path, "rb") as fh:
                                tar.addfile(ti, fh)
                        else:
                            tar.addfile(ti)

                tar_bytes = buf.getvalue()
                digest = store_layer(tar_bytes)

                save_manifest("python", "3.11-slim", [
                    {"digest": digest, "size": len(tar_bytes), "createdBy": "FROM python:3.11-slim"}
                ], {
                    "Env": ["PATH=/usr/local/bin:/usr/local/sbin:/usr/sbin:/usr/bin:/sbin:/bin",
                            "PYTHON_VERSION=3.11"],
                    "Cmd": ["python3"],
                    "WorkingDir": "",
                })
                print("  ✓ python:3.11-slim imported via Docker\n")
                return

        except Exception as e:
            print(f"  ⚠ Docker export failed ({e}), falling back to minimal stub ...")

    # ── Fallback: copy REAL host binaries into the layer ─────────────────────
    print("  → Creating python base layer from host binaries ...")

    with tempfile.TemporaryDirectory() as rootfs:
        binaries_to_copy = _find_host_binaries([
            "sh", "bash", "dash",      # shell (at least one needed)
            "echo", "cat", "ls", "mkdir", "rm", "cp", "mv", "chmod",
            "env",                      # /usr/bin/env
            "python3",                  # the actual python interpreter
        ])
        _copy_binaries_into_rootfs(binaries_to_copy, rootfs)

        # Essential dirs and files
        for d in ["tmp", "dev", "proc", "sys", "etc", "root", "var", "run"]:
            os.makedirs(os.path.join(rootfs, d), exist_ok=True)
        with open(os.path.join(rootfs, "etc", "hostname"), "w") as f:
            f.write("docksmith\n")
        with open(os.path.join(rootfs, "etc", "hosts"), "w") as f:
            f.write("127.0.0.1 localhost\n")

        tar_bytes = _tar_directory(rootfs)

    digest = store_layer(tar_bytes)
    save_manifest("python", "3.11-slim", [
        {"digest": digest, "size": len(tar_bytes), "createdBy": "FROM python:3.11-slim (host-binaries)"}
    ], {
        "Env": ["PATH=/usr/local/bin:/usr/local/sbin:/usr/sbin:/usr/bin:/sbin:/bin"],
        "Cmd": ["python3"],
        "WorkingDir": "",
    })
    print("  ✓ Python base layer created from host binaries\n")


def import_alpine():
    """Same logic for alpine:latest."""
    print("\n[setup] Importing alpine:latest base image...")

    if shutil.which("docker"):
        try:
            print("  → Docker found — pulling and exporting alpine:latest ...")
            subprocess.run(["docker", "pull", "alpine:latest"], check=True, capture_output=True)

            with tempfile.TemporaryDirectory() as tmpdir:
                tar_path  = os.path.join(tmpdir, "alpine.tar")
                layer_dir = os.path.join(tmpdir, "layer")
                os.makedirs(layer_dir)

                subprocess.run(["docker", "save", "-o", tar_path, "alpine:latest"], check=True, capture_output=True)

                merged_files = {}
                with tarfile.open(tar_path) as outer:
                    manifest_json = json.loads(outer.extractfile("manifest.json").read())
                    layers_list   = manifest_json[0]["Layers"]
                    for lp in layers_list:
                        lt = outer.extractfile(lp)
                        with tarfile.open(fileobj=lt) as ltar:
                            ltar.extractall(layer_dir)

                all_files = []
                for root, dirs, files in os.walk(layer_dir):
                    dirs.sort()
                    for fname in sorted(files):
                        all_files.append(os.path.join(root, fname))

                buf = io.BytesIO()
                with tarfile.open(fileobj=buf, mode="w:") as tar:
                    for abs_path in sorted(all_files):
                        rel = os.path.relpath(abs_path, layer_dir)
                        ti  = tar.gettarinfo(abs_path, arcname=rel)
                        ti.mtime = 0; ti.uid = 0; ti.gid = 0; ti.uname = ""; ti.gname = ""
                        if ti.isreg():
                            with open(abs_path, "rb") as fh:
                                tar.addfile(ti, fh)
                        else:
                            tar.addfile(ti)

                tar_bytes = buf.getvalue()
                digest = store_layer(tar_bytes)
                save_manifest("alpine", "latest", [
                    {"digest": digest, "size": len(tar_bytes), "createdBy": "FROM alpine:latest"}
                ], {
                    "Env": ["PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"],
                    "Cmd": ["/bin/sh"],
                    "WorkingDir": "",
                })
                print("  ✓ alpine:latest imported via Docker\n")
                return
        except Exception as e:
            print(f"  ⚠ Docker export failed ({e}), falling back to host-binary layer ...")

    # ── Fallback: copy real host binaries ──────────────────────────────────
    print("  → Creating alpine base layer from host binaries ...")

    with tempfile.TemporaryDirectory() as rootfs:
        binaries_to_copy = _find_host_binaries([
            "sh", "bash", "dash",
            "echo", "cat", "ls", "mkdir", "rm", "cp", "mv", "chmod",
            "env",
        ])
        _copy_binaries_into_rootfs(binaries_to_copy, rootfs)

        for d in ["tmp", "dev", "proc", "sys", "etc", "root", "var", "run"]:
            os.makedirs(os.path.join(rootfs, d), exist_ok=True)
        with open(os.path.join(rootfs, "etc", "alpine-release"), "w") as f:
            f.write("3.18.0\n")

        tar_bytes = _tar_directory(rootfs)

    digest = store_layer(tar_bytes)
    save_manifest("alpine", "latest", [
        {"digest": digest, "size": len(tar_bytes), "createdBy": "FROM alpine:latest (host-binaries)"}
    ], {
        "Env": ["PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"],
        "Cmd": ["/bin/sh"],
        "WorkingDir": "",
    })
    print("  ✓ Alpine base layer created from host binaries\n")


if __name__ == "__main__":
    print("=" * 60)
    print("  DOCKSMITH — Base Image Setup")
    print("=" * 60)
    ensure_dirs()
    import_python_slim()
    import_alpine()
    print("=" * 60)
    print("  Setup complete! You can now run:")
    print("    docksmith build -t myapp:latest .")
    print("=" * 60)
