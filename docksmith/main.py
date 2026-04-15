# docksmith/main.py
# ============================================================
#  PIYUSH — File 3: CLI Entry Point
#  All 4 commands: build, images, rmi, run
#  Write this LAST — wires everything together
# ============================================================

import os
import sys
import click

from docksmith.state import (
    load_manifest, list_manifests, delete_manifest, image_exists, ensure_dirs
)


# ── CLI group ─────────────────────────────────────────────────────────────────

@click.group()
def cli():
    """docksmith — a minimal container image builder."""
    ensure_dirs()


# ── build ─────────────────────────────────────────────────────────────────────

@cli.command()
@click.option("-t", "--tag",      required=True, help="Image name and tag e.g. myapp:latest")
@click.option("--no-cache",       is_flag=True,  help="Disable build cache")
@click.argument("context", default=".")
def build(tag, no_cache, context):
    """
    Build an image from a Docksmithfile.

    \b
    Usage:
      docksmith build -t myapp:latest .
      docksmith build -t myapp:latest /path/to/context --no-cache
    """
    from docksmith.builder import build_image

    # Parse -t myapp:latest
    if ":" in tag:
        name, image_tag = tag.split(":", 1)
    else:
        name, image_tag = tag, "latest"

    context_dir = os.path.abspath(context)
    if not os.path.isdir(context_dir):
        click.echo(f"[ERROR] Context directory not found: {context_dir}", err=True)
        sys.exit(1)

    try:
        build_image(
            context_dir = context_dir,
            name        = name,
            tag         = image_tag,
            no_cache    = no_cache,
        )
    except (FileNotFoundError, RuntimeError, ValueError) as e:
        click.echo(str(e), err=True)
        sys.exit(1)


# ── images ────────────────────────────────────────────────────────────────────

@cli.command("images")
def images_cmd():
    """
    List all locally stored images.

    \b
    Usage:
      docksmith images
    """
    manifests = list_manifests()

    if not manifests:
        click.echo("No images found. Build one with: docksmith build -t name:tag .")
        return

    # Print table header — rubric: Name, Tag, ID, Created
    header = f"{'NAME':<20} {'TAG':<15} {'IMAGE ID':<15} {'CREATED'}"
    click.echo(header)
    click.echo("-" * len(header))

    for m in manifests:
        short_id = m.digest.replace("sha256:", "")[:12] if m.digest else "unknown"
        created_short = m.created[:19].replace("T", " ") if m.created else "unknown"
        click.echo(f"{m.name:<20} {m.tag:<15} {short_id:<15} {created_short}")


# ── rmi ───────────────────────────────────────────────────────────────────────

@cli.command()
@click.argument("image")
def rmi(image):
    """
    Remove a locally stored image.

    \b
    Usage:
      docksmith rmi myapp:latest
    """
    from docksmith.layers import delete_layer, layer_exists

    if ":" in image:
        name, tag = image.split(":", 1)
    else:
        name, tag = image, "latest"

    try:
        layer_digests = delete_manifest(name, tag)
    except FileNotFoundError as e:
        click.echo(str(e), err=True)
        sys.exit(1)

    # Delete layer files that are no longer referenced
    # (Simple approach: delete all layers owned by this image)
    deleted_layers = 0
    for digest in layer_digests:
        if layer_exists(digest):
            delete_layer(digest)
            deleted_layers += 1

    click.echo(f"Deleted {name}:{tag} ({deleted_layers} layer(s) removed)")


# ── run ───────────────────────────────────────────────────────────────────────

@cli.command()
@click.argument("image")
@click.argument("cmd_args", nargs=-1)
@click.option("-e", "env_overrides", multiple=True, help="Set env variable KEY=value")
def run(image, cmd_args, env_overrides):
    """
    Run a command inside a container from a stored image.

    \b
    Usage:
      docksmith run myapp:latest
      docksmith run myapp:latest python main.py
      docksmith run myapp:latest -e GREETING=hi
    """
    from docksmith.runtime import isolate_and_run
    from docksmith.layers import extract_layer
    import tempfile, shutil

    if ":" in image:
        name, tag = image.split(":", 1)
    else:
        name, tag = image, "latest"

    manifest = load_manifest(name, tag)
    if manifest is None:
        click.echo(
            f"[ERROR] Image '{name}:{tag}' not found.\n"
            f"  Run 'docksmith images' to see available images.",
            err=True
        )
        sys.exit(1)

    # Build the env dict from image config + -e overrides
    env_dict = {}
    for env_str in (manifest.config.Env or []):
        if "=" in env_str:
            k, _, v = env_str.partition("=")
            env_dict[k] = v

    for override in env_overrides:
        if "=" not in override:
            click.echo(
                f"[ERROR] -e flag must be KEY=value format. Got: {override!r}",
                err=True
            )
            sys.exit(1)
        k, _, v = override.partition("=")
        env_dict[k] = v

    # Determine command to run
    if cmd_args:
        command = list(cmd_args)
    elif manifest.config.Cmd:
        command = manifest.config.Cmd
    else:
        click.echo(
            f"[ERROR] Image '{name}:{tag}' has no CMD defined and no command was provided.\n"
            f"  Usage: docksmith run {name}:{tag} <command> [args...]",
            err=True,
        )
        sys.exit(1)

    workdir = manifest.config.WorkingDir or "/"

    # Assemble rootfs in a temp dir
    rootfs = tempfile.mkdtemp(prefix="docksmith_run_")
    try:
        for layer in manifest.layers:
            extract_layer(layer.digest, rootfs)

        exit_code = isolate_and_run(
            rootfs  = rootfs,
            command = command,
            env     = env_dict,
            workdir = workdir,
        )

        sys.exit(exit_code)

    except Exception as e:
        click.echo(f"[RUNTIME ERROR] {e}", err=True)
        sys.exit(1)
    finally:
        shutil.rmtree(rootfs, ignore_errors=True)


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    cli()