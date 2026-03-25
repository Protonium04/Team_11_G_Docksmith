# docksmith/reporter.py
# ============================================================
#  PREKSHA — File 2: Build Output Formatter
#  Test: python3 -m pytest tests/test_reporter.py -v
# ============================================================

from datetime import datetime, timezone, timedelta


# ── Build step output ─────────────────────────────────────────────────────────

def print_step(
    step_idx:    int,
    total_steps: int,
    instruction: str,
    status:      str,
    elapsed:     float = 0.0,
):
    """
    Prints a single build step line.

    Examples:
        Step 1/6 : FROM alpine:latest
        Step 3/6 : COPY . /app [CACHE HIT]
        Step 4/6 : RUN echo hi [CACHE MISS] 2.34s
    """
    prefix = f"Step {step_idx}/{total_steps} : {instruction}"

    if status == "HIT":
        print(f"{prefix} [CACHE HIT]")
    elif status == "MISS":
        print(f"{prefix} [CACHE MISS] {elapsed:.2f}s")
    else:
        print(prefix)


def print_build_success(digest: str, name: str, tag: str, elapsed: float):
    """
    Example:
        Successfully built sha256:3f2a1b9c7d4e myapp:latest (5.23s)
    """
    short = digest[:19] if digest else "sha256:?"
    print(f"\nSuccessfully built {short} {name}:{tag} ({elapsed:.2f}s)\n")


def print_build_error(message: str):
    print(f"\n[BUILD ERROR] {message}\n")


# ── docksmith images table ────────────────────────────────────────────────────

def print_images_table(manifests: list):
    """
    Prints the 'docksmith images' output table.

    Example:
        NAME       TAG        DIGEST           CREATED
        myapp      latest     sha256:3f2a1b9c  2 hours ago
    """
    if not manifests:
        print("No images found.")
        return

    headers = ["NAME", "TAG", "DIGEST", "CREATED"]

    rows = []
    for m in manifests:
        short_digest = m.digest[:19] if m.digest else "sha256:?"
        created      = _format_created(m.created)
        rows.append([m.name, m.tag, short_digest, created])

    col_widths = []
    for i, header in enumerate(headers):
        max_width = len(header)
        for row in rows:
            max_width = max(max_width, len(row[i]))
        col_widths.append(max_width + 2)

    header_line = "".join(h.ljust(col_widths[i]) for i, h in enumerate(headers))
    print(header_line)

    for row in rows:
        row_line = "".join(str(row[i]).ljust(col_widths[i]) for i in range(len(headers)))
        print(row_line)


def _format_created(created_str: str) -> str:
    """Formats ISO timestamp into human-readable relative time."""
    if not created_str:
        return "unknown"
    try:
        created = datetime.fromisoformat(created_str)
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        now     = datetime.now(timezone.utc)
        delta   = now - created
        seconds = int(delta.total_seconds())

        if seconds < 60:
            return "just now"
        elif seconds < 3600:
            mins = seconds // 60
            return f"{mins} minute{'s' if mins != 1 else ''} ago"
        elif seconds < 86400:
            hours = seconds // 3600
            return f"{hours} hour{'s' if hours != 1 else ''} ago"
        elif seconds < 86400 * 30:
            days = seconds // 86400
            return f"{days} day{'s' if days != 1 else ''} ago"
        else:
            months = seconds // (86400 * 30)
            return f"{months} month{'s' if months != 1 else ''} ago"
    except (ValueError, TypeError):
        return created_str


# ── Timing helper ─────────────────────────────────────────────────────────────

class StepTimer:
    """
    Usage:
        with StepTimer() as t:
            # do work
        print(t.elapsed)
    """
    def __init__(self):
        self.elapsed = 0.0
        self._start  = None

    def __enter__(self):
        import time
        self._start = time.perf_counter()
        return self

    def __exit__(self, *args):
        import time
        self.elapsed = time.perf_counter() - self._start