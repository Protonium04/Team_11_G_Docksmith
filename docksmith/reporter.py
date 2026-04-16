# docksmith/reporter.py
# ============================================================
#  PREKSHA — Build output formatting & images table
# ============================================================

import os


def print_step(step_idx: int, total: int, instruction_type: str, args: str,
               status: str = "", elapsed: float = None):
    """
    Prints a build step line.
    status: 'hit', 'miss', or '' (for non-caching steps)
    """
    label = f"Step {step_idx}/{total} : {instruction_type} {args}"

    if status == "hit":
        print(f"{label} [CACHE HIT]")
    elif status == "miss":
        t = f" {elapsed:.2f}s" if elapsed is not None else ""
        print(f"{label} [CACHE MISS]{t}")
    else:
        print(label)


def print_build_success(digest: str, name: str, tag: str, elapsed: float):
    short = digest[:19] if digest else "sha256:?"
    print(f"\nSuccessfully built {short} {name}:{tag} ({elapsed:.2f}s)\n")


def print_images_table(manifests: list):
    """Formats and prints the docksmith images table."""
    if not manifests:
        print("No images found. Run: docksmith build -t <name:tag> <context>")
        return

    fmt = "{:<22} {:<10} {:<16} {:<8} {}"
    print(fmt.format("NAME", "TAG", "DIGEST", "LAYERS", "CREATED"))
    print("-" * 72)
    for m in manifests:
        short_digest = m.digest[:15] if m.digest else "—"
        created      = m.created[:19].replace("T", " ") if m.created else "—"
        print(fmt.format(m.name[:21], m.tag[:9], short_digest, len(m.layers), created))
