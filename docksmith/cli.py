import argparse
import sys

from docksmith.builder import build_image
from docksmith.runtime import run_image
from docksmith.state import list_manifests, load_manifest, remove_image


def _parse_image_ref(ref: str) -> tuple[str, str]:
    if ":" in ref:
        name, tag = ref.split(":", 1)
    else:
        name, tag = ref, "latest"
    name = name.strip()
    tag = tag.strip()
    if not name or not tag:
        raise ValueError(f"[CLI ERROR] Invalid image reference: {ref!r}")
    return name, tag


def _parse_env_overrides(pairs: list[str]) -> dict[str, str]:
    out = {}
    for item in pairs:
        if "=" not in item:
            raise ValueError(f"[CLI ERROR] -e must be KEY=VALUE, got: {item!r}")
        key, _, value = item.partition("=")
        if not key:
            raise ValueError(f"[CLI ERROR] Invalid environment key in: {item!r}")
        out[key] = value
    return out


def _cmd_build(args: argparse.Namespace) -> int:
    name, tag = _parse_image_ref(args.tag)
    build_image(
        context_dir=args.context_dir,
        name=name,
        tag=tag,
        no_cache=args.no_cache,
    )
    return 0


def _cmd_images(_: argparse.Namespace) -> int:
    images = list_manifests()
    if not images:
        print("No images found.")
        return 0

    print(f"{'NAME':20} {'TAG':12} {'ID':14} CREATED")
    for m in images:
        image_id = (m.digest or "sha256:")[:12]
        print(f"{m.name:20} {m.tag:12} {image_id:14} {m.created}")
    return 0


def _cmd_rmi(args: argparse.Namespace) -> int:
    name, tag = _parse_image_ref(args.image)
    removed = remove_image(name, tag)
    if not removed:
        print(f"Image not found: {name}:{tag}")
        return 1
    print(f"Removed image {name}:{tag}")
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    name, tag = _parse_image_ref(args.image)
    manifest = load_manifest(name, tag)
    if manifest is None:
        raise RuntimeError(f"[RUNTIME ERROR] Image not found: {name}:{tag}")

    env = _parse_env_overrides(args.env or [])
    command_override = args.command if args.command else None
    return run_image(
        manifest=manifest,
        command_override=command_override,
        env_overrides=env,
    )


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="docksmith")
    sub = parser.add_subparsers(dest="command", required=True)

    p_build = sub.add_parser("build", help="Build an image from Docksmithfile")
    p_build.add_argument("-t", "--tag", required=True, help="Image tag, e.g. myapp:latest")
    p_build.add_argument("context_dir", help="Build context directory")
    p_build.add_argument("--no-cache", action="store_true", help="Disable build cache")
    p_build.set_defaults(fn=_cmd_build)

    p_images = sub.add_parser("images", help="List local images")
    p_images.set_defaults(fn=_cmd_images)

    p_rmi = sub.add_parser("rmi", help="Remove a local image")
    p_rmi.add_argument("image", help="Image reference, e.g. myapp:latest")
    p_rmi.set_defaults(fn=_cmd_rmi)

    p_run = sub.add_parser("run", help="Run an image")
    p_run.add_argument("-e", "--env", action="append", default=[], help="Env override KEY=VALUE")
    p_run.add_argument("image", help="Image reference, e.g. myapp:latest")
    p_run.add_argument("command", nargs=argparse.REMAINDER, help="Optional command override")
    p_run.set_defaults(fn=_cmd_run)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
