#!/usr/bin/env python3
# docksmith/main.py
# ============================================================
#  PIYUSH — CLI entry point: build, images, rmi, run
# ============================================================

import os
import sys
import click

from docksmith.state import list_manifests, load_manifest, delete_manifest, LAYERS_DIR
from docksmith.layers import delete_layer


@click.group()
def cli():
    """Docksmith — a minimal container build system."""
    pass


# ── docksmith build ───────────────────────────────────────────────────────────

@cli.command("build")
@click.option("-t", "--tag", required=True, help="Name and tag: name:tag")
@click.option("--no-cache", is_flag=True, default=False, help="Disable layer cache")
@click.argument("context", default=".")
def build(tag, no_cache, context):
    """Build an image from a Docksmithfile."""
    from docksmith.builder import build_image

    if ":" in tag:
        name, image_tag = tag.split(":", 1)
    else:
        name, image_tag = tag, "latest"

    context = os.path.abspath(context)

    try:
        build_image(
            context_dir=context,
            name=name,
            tag=image_tag,
            no_cache=no_cache,
        )
    except Exception as e:
        click.echo(f"\n{e}", err=True)
        sys.exit(1)


# ── docksmith images ──────────────────────────────────────────────────────────

@cli.command("images")
def images():
    """List all locally built images."""
    manifests = list_manifests()
    if not manifests:
        click.echo("No images found. Run: docksmith build -t <name:tag> <context>")
        return

    fmt = "{:<20} {:<10} {:<15} {}"
    click.echo(fmt.format("NAME", "TAG", "IMAGE ID", "CREATED"))
    click.echo("-" * 60)
    for m in manifests:
        # IMAGE ID = first 12 hex characters of the digest (strip sha256: prefix)
        image_id = m.digest.replace("sha256:", "")[:12] if m.digest else "—"
        created  = m.created[:19].replace("T", " ") if m.created else "—"
        click.echo(fmt.format(m.name[:19], m.tag[:9], image_id, created))


# ── docksmith rmi ─────────────────────────────────────────────────────────────

@cli.command("rmi")
@click.argument("image_ref")
def rmi(image_ref):
    """Remove an image and its exclusive layers."""
    if ":" in image_ref:
        name, tag = image_ref.split(":", 1)
    else:
        name, tag = image_ref, "latest"

    m = load_manifest(name, tag)
    if m is None:
        click.echo(f"Error: Image '{image_ref}' not found.", err=True)
        sys.exit(1)

    # Collect layer digests used by base images — never delete these.
    # This lets users do: docksmith rmi myapp:latest && docksmith build ... without
    # having to re-run setup_base_image.py every time.
    base_digests = set()
    for other in list_manifests():
        if f"{other.name}:{other.tag}" in BASE_IMAGES:
            for layer in other.layers:
                base_digests.add(layer.digest)

    deleted_layers = 0
    skipped_layers = 0
    for layer in m.layers:
        if layer.digest in base_digests:
            skipped_layers += 1  # shared with a base image — keep it
        else:
            delete_layer(layer.digest)
            deleted_layers += 1

    delete_manifest(name, tag)
    msg = f"Deleted: {name}:{tag}  ({deleted_layers} layer files removed"
    if skipped_layers:
        msg += f", {skipped_layers} shared base-image layers kept"
    msg += ")"
    click.echo(msg)


# ── docksmith clean ───────────────────────────────────────────────────────────

# Base images to preserve (these take a long time to re-create)
BASE_IMAGES = {"python:3.11-slim", "alpine:latest", "alpine:3.18"}

@cli.command("clean")
@click.option("--all", "clean_all", is_flag=True, default=False,
              help="Also remove base images (requires re-running setup_base_image.py)")
def clean(clean_all):
    """Clear cache and user-built images, keeping base images intact."""
    import shutil
    from docksmith.state import CACHE_DIR

    # 1. Clear the entire build cache
    if os.path.exists(CACHE_DIR):
        shutil.rmtree(CACHE_DIR, ignore_errors=True)
        os.makedirs(CACHE_DIR, exist_ok=True)
    click.echo("✓ Build cache cleared")

    all_manifests = list_manifests()

    # 2. Collect layer digests that belong to base images — never delete these
    protected_digests = set()
    if not clean_all:
        for m in all_manifests:
            if f"{m.name}:{m.tag}" in BASE_IMAGES:
                for layer in m.layers:
                    protected_digests.add(layer.digest)

    # 3. Remove user-built images (keep base images unless --all)
    removed = 0
    for m in all_manifests:
        image_ref = f"{m.name}:{m.tag}"
        if not clean_all and image_ref in BASE_IMAGES:
            click.echo(f"  ⏭ Keeping base image: {image_ref}")
            continue
        for layer in m.layers:
            if layer.digest not in protected_digests:
                delete_layer(layer.digest)
        delete_manifest(m.name, m.tag)
        click.echo(f"  🗑 Removed: {image_ref}")
        removed += 1

    click.echo(f"\n✓ Cleaned {removed} image(s). Ready for a fresh build!")



@cli.command("run")
@click.argument("image_ref")
@click.argument("cmd_args", nargs=-1)
@click.option("-e", "--env", multiple=True, help="KEY=VALUE env overrides")
def run(image_ref, cmd_args, env):
    """Run a container from a local image."""
    from docksmith.runtime import isolate_and_run
    from docksmith.layers import extract_layer
    import tempfile, shutil

    if ":" in image_ref:
        name, tag = image_ref.split(":", 1)
    else:
        name, tag = image_ref, "latest"

    m = load_manifest(name, tag)
    if m is None:
        click.echo(f"Error: Image '{image_ref}' not found.", err=True)
        sys.exit(1)

    # Parse -e overrides
    env_overrides = {}
    for e in env:
        if "=" in e:
            k, _, v = e.partition("=")
            env_overrides[k] = v

    # Build env dict: image config + overrides
    container_env = {}
    for env_str in (m.config.Env or []):
        if "=" in env_str:
            k, _, v = env_str.partition("=")
            container_env[k] = v
    container_env.update(env_overrides)

    # Determine command — fail with clear error if no CMD and no override (spec section 6)
    if cmd_args:
        command = list(cmd_args)
    elif m.config.Cmd:
        command = m.config.Cmd
    else:
        click.echo(
            f"Error: No CMD defined in image '{image_ref}' and no command given.\n"
            f"  Usage: docksmith run {image_ref} <command>",
            err=True,
        )
        sys.exit(1)

    workdir = m.config.WorkingDir or "/"

    # Extract layers into temp rootfs
    tmpdir = tempfile.mkdtemp(prefix="docksmith_run_")
    try:
        for layer in m.layers:
            extract_layer(layer.digest, tmpdir)

        exit_code = isolate_and_run(
            rootfs=tmpdir,
            command=command,
            env=container_env,
            workdir=workdir,
        )
        click.echo(f"\n[docksmith] Container exited with code: {exit_code}")

        # Auto-refresh dashboard so HTML shows updated state without manual step
        try:
            import importlib.util, pathlib
            here       = pathlib.Path(__file__).resolve().parent
            data_gen_p = here.parent / "dashboard" / "data_gen.py"
            if data_gen_p.exists():
                spec   = importlib.util.spec_from_file_location("data_gen", data_gen_p)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                module.generate()
                click.echo("  [dashboard] data.json refreshed automatically.")
        except Exception:
            pass

        sys.exit(exit_code)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    cli()