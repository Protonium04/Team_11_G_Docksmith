# docksmith/builder.py
# ============================================================
#  PROTHAM — File 3: Build Engine / Orchestrator
#  Test: python3 -m pytest tests/test_builder.py -v
# ============================================================

import os
import glob
import shutil
import tempfile
import time
from datetime import datetime, timezone

from docksmith.parser import (
    parse_docksmithfile,
    parse_cmd_args,
    parse_env_args,
    parse_copy_args,
    parse_from_args,
)
from docksmith.layers import (
    create_delta_tar,
    collect_all_paths,
    store_layer,
    extract_layer,
    get_layer_size,
    layer_exists,
    hash_copy_sources,
    snapshot_filesystem,
    compute_delta_paths,
)


def build_image(
    context_dir: str,
    name: str,
    tag: str,
    no_cache: bool = False,
):
    """
    Main build function. Called by Piyush's CLI (main.py).
    Parses Docksmithfile, executes all steps, saves manifest.

    Args:
        context_dir: Directory containing the Docksmithfile + source files
        name:        Image name  e.g. 'myapp'
        tag:         Image tag   e.g. 'latest'
        no_cache:    Skip all cache lookups/writes if True
    """
    # ── Import teammates' modules ────────────────────────────────────────────
    from docksmith.state import load_manifest, save_manifest
    from docksmith.cache import CacheManager
    from docksmith.runtime import isolate_and_run
    from docksmith.models import ImageManifest, LayerEntry, ImageConfig

    docksmithfile_path = os.path.join(context_dir, "Docksmithfile")
    if not os.path.exists(docksmithfile_path):
        raise FileNotFoundError(
            f"[BUILD ERROR] No Docksmithfile found in: {context_dir}"
        )

    instructions = parse_docksmithfile(docksmithfile_path)
    total_steps  = len(instructions)

    # ── Build state ──────────────────────────────────────────────────────────
    layers           = []    # list of LayerEntry
    env_dict         = {}    # accumulated ENV  key → value
    workdir          = ""    # current WORKDIR (empty = not set = /)
    cmd              = []    # CMD value
    prev_digest      = None  # digest of last COPY/RUN layer (or base manifest)
    cache_busted     = False # True = all remaining steps are forced misses
    build_start      = datetime.now(timezone.utc)
    original_created = None  # preserved from existing manifest on full cache hit

    cache = CacheManager(no_cache=no_cache)

    print()  # blank line before step output

    for step_idx, instr in enumerate(instructions, start=1):
        label = f"Step {step_idx}/{total_steps} : {instr.type} {instr.args}"

        # ── FROM ─────────────────────────────────────────────────────────────
        if instr.type == "FROM":
            print(label)  # FROM: no cache status, no timing
            base_name, base_tag = parse_from_args(instr.args)
            base_manifest = load_manifest(base_name, base_tag)

            if base_manifest is None:
                raise RuntimeError(
                    f"[BUILD ERROR] FROM: Image '{instr.args}' not found.\n"
                    f"  Run setup_base_image.py first to import base images."
                )

            layers      = list(base_manifest.layers)
            prev_digest = base_manifest.digest

            for env_str in (base_manifest.config.Env or []):
                if "=" in env_str:
                    k, _, v = env_str.partition("=")
                    env_dict[k] = v

            workdir = base_manifest.config.WorkingDir or ""
            cmd     = base_manifest.config.Cmd or []

            existing = load_manifest(name, tag)
            if existing:
                original_created = existing.created
            continue

        # ── WORKDIR ──────────────────────────────────────────────────────────
        elif instr.type == "WORKDIR":
            print(label)
            workdir = instr.args
            continue

        # ── ENV ──────────────────────────────────────────────────────────────
        elif instr.type == "ENV":
            print(label)
            k, v = parse_env_args(instr.args)
            env_dict[k] = v
            continue

        # ── CMD ──────────────────────────────────────────────────────────────
        elif instr.type == "CMD":
            print(label)
            cmd = parse_cmd_args(instr.args)
            continue

        # ── COPY (produces a layer) ───────────────────────────────────────────
        elif instr.type == "COPY":
            src_pattern      = parse_copy_args(instr.args)[0]
            dest             = parse_copy_args(instr.args)[1]
            instruction_text = f"COPY {instr.args}"
            env_serialized   = _serialize_env(env_dict)
            copy_hashes      = hash_copy_sources(src_pattern, context_dir)

            cached_digest = None
            if not cache_busted:
                cached_digest = cache.lookup(
                    prev_digest      = prev_digest or "",
                    instruction_text = instruction_text,
                    workdir          = workdir,
                    env_serialized   = env_serialized,
                    copy_hashes      = copy_hashes,
                )

            if cached_digest:
                print(f"{label} [CACHE HIT]")
                layers.append(LayerEntry(
                    digest    = cached_digest,
                    size      = get_layer_size(cached_digest),
                    createdBy = instruction_text,
                ))
                prev_digest = cached_digest

            else:
                cache_busted = True
                t0 = time.perf_counter()

                digest = _execute_copy(
                    src_pattern    = src_pattern,
                    dest           = dest,
                    context_dir    = context_dir,
                    current_layers = layers,
                    workdir        = workdir,
                )

                elapsed = time.perf_counter() - t0
                print(f"{label} [CACHE MISS] {elapsed:.2f}s")

                cache.store(
                    prev_digest      = prev_digest or "",
                    instruction_text = instruction_text,
                    workdir          = workdir,
                    env_serialized   = env_serialized,
                    copy_hashes      = copy_hashes,
                    result_digest    = digest,
                )

                layers.append(LayerEntry(
                    digest    = digest,
                    size      = get_layer_size(digest),
                    createdBy = instruction_text,
                ))
                prev_digest = digest

        # ── RUN (produces a layer) ────────────────────────────────────────────
        elif instr.type == "RUN":
            instruction_text = f"RUN {instr.args}"
            env_serialized   = _serialize_env(env_dict)

            cached_digest = None
            if not cache_busted:
                cached_digest = cache.lookup(
                    prev_digest      = prev_digest or "",
                    instruction_text = instruction_text,
                    workdir          = workdir,
                    env_serialized   = env_serialized,
                    copy_hashes      = None,
                )

            if cached_digest:
                print(f"{label} [CACHE HIT]")
                layers.append(LayerEntry(
                    digest    = cached_digest,
                    size      = get_layer_size(cached_digest),
                    createdBy = instruction_text,
                ))
                prev_digest = cached_digest

            else:
                cache_busted = True
                t0 = time.perf_counter()

                digest = _execute_run(
                    command        = instr.args,
                    current_layers = layers,
                    env_dict       = env_dict,
                    workdir        = workdir,
                    isolate_fn     = isolate_and_run,
                )

                elapsed = time.perf_counter() - t0
                print(f"{label} [CACHE MISS] {elapsed:.2f}s")

                cache.store(
                    prev_digest      = prev_digest or "",
                    instruction_text = instruction_text,
                    workdir          = workdir,
                    env_serialized   = env_serialized,
                    copy_hashes      = None,
                    result_digest    = digest,
                )

                layers.append(LayerEntry(
                    digest    = digest,
                    size      = get_layer_size(digest),
                    createdBy = instruction_text,
                ))
                prev_digest = digest

    # ── Save final manifest ───────────────────────────────────────────────────
    config = ImageConfig(
        Env       = [f"{k}={v}" for k, v in env_dict.items()],
        Cmd       = cmd,
        WorkingDir= workdir,
    )

    # Timestamp preservation:
    # If ALL steps were cache hits reuse original created timestamp
    # so the manifest digest is identical across rebuilds.
    all_hits = not cache_busted
    if all_hits and original_created:
        created = original_created
    else:
        created = build_start.isoformat()

    manifest = ImageManifest(
        name    = name,
        tag     = tag,
        digest  = "",      # save_manifest (Piyush) computes the real digest
        created = created,
        config  = config,
        layers  = layers,
    )

    saved      = save_manifest(manifest)
    total_time = (datetime.now(timezone.utc) - build_start).total_seconds()
    short      = saved.digest[:19] if saved.digest else "sha256:?"
    print(f"\nSuccessfully built {short} {name}:{tag} ({total_time:.2f}s)\n")
    return saved


# ── Private helpers ───────────────────────────────────────────────────────────

def _serialize_env(env_dict: dict) -> str:
    """
    Converts env dict to a stable string for cache key computation.
    Keys sorted lexicographically so order never matters.
    e.g. {'Z': '1', 'A': '2'} → 'A=2&Z=1'
    """
    if not env_dict:
        return ""
    return "&".join(f"{k}={v}" for k, v in sorted(env_dict.items()))


def _assemble_rootfs(layers: list, target_dir: str):
    """Extracts all layers in order into target_dir."""
    for layer in layers:
        extract_layer(layer.digest, target_dir)


def _execute_copy(
    src_pattern: str,
    dest: str,
    context_dir: str,
    current_layers: list,
    workdir: str,
) -> str:
    """
    Executes a COPY instruction:
    1. Assembles current layers into temp rootfs
    2. Creates WORKDIR inside rootfs if needed
    3. Copies matched files from context into rootfs/dest
    4. Creates delta tar of just the dest directory
    5. Stores + returns layer digest
    """
    import glob as glob_module

    with tempfile.TemporaryDirectory(prefix="docksmith_copy_") as rootfs:
        _assemble_rootfs(current_layers, rootfs)

        if workdir:
            os.makedirs(os.path.join(rootfs, workdir.lstrip("/")), exist_ok=True)

        dest_abs = os.path.join(rootfs, dest.lstrip("/"))
        os.makedirs(dest_abs, exist_ok=True)

        # Resolve source pattern
        if src_pattern == ".":
            matched = []
            for root, dirs, files in os.walk(context_dir):
                dirs.sort()
                for f in sorted(files):
                    matched.append(os.path.join(root, f))
        else:
            full_pattern = os.path.join(context_dir, src_pattern)
            matched = sorted(glob_module.glob(full_pattern, recursive=True))

        if not matched:
            raise FileNotFoundError(
                f"[COPY ERROR] No files matched '{src_pattern}' in '{context_dir}'"
            )

        for src_path in matched:
            if os.path.isfile(src_path):
                rel     = os.path.relpath(src_path, context_dir)
                dst_dir = os.path.join(dest_abs, os.path.dirname(rel))
                os.makedirs(dst_dir, exist_ok=True)
                shutil.copy2(src_path, os.path.join(dst_dir, os.path.basename(rel)))
            elif os.path.isdir(src_path):
                shutil.copytree(
                    src_path,
                    os.path.join(dest_abs, os.path.basename(src_path)),
                    dirs_exist_ok=True,
                )

        all_paths = collect_all_paths(dest_abs)
        tar_bytes = create_delta_tar(dest_abs, all_paths)
        return store_layer(tar_bytes)


def _execute_run(
    command: str,
    current_layers: list,
    env_dict: dict,
    workdir: str,
    isolate_fn,
) -> str:
    """
    Executes a RUN instruction:
    1. Assembles current layers into temp rootfs
    2. Creates WORKDIR inside rootfs if needed
    3. Snapshots filesystem before
    4. Runs command inside Pranav's isolation primitive
    5. Snapshots filesystem after
    6. Creates delta tar of changed files
    7. Stores + returns layer digest
    """
    with tempfile.TemporaryDirectory(prefix="docksmith_run_") as rootfs:
        _assemble_rootfs(current_layers, rootfs)

        effective_workdir = workdir or "/"
        os.makedirs(
            os.path.join(rootfs, effective_workdir.lstrip("/")),
            exist_ok=True,
        )

        before = snapshot_filesystem(rootfs)

        exit_code = isolate_fn(
            rootfs  = rootfs,
            command = ["/bin/sh", "-c", command],
            env     = dict(env_dict),
            workdir = effective_workdir,
        )

        if exit_code != 0:
            raise RuntimeError(
                f"[BUILD ERROR] RUN failed (exit {exit_code}):\n  {command}"
            )

        after         = snapshot_filesystem(rootfs)
        changed_paths = compute_delta_paths(before, after, rootfs)
        tar_bytes     = create_delta_tar(rootfs, changed_paths) if changed_paths else create_delta_tar(rootfs, [])
        return store_layer(tar_bytes)