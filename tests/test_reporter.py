# tests/test_reporter.py
# Run: python3 -m pytest tests/test_reporter.py -v

import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import time
from io import StringIO
from unittest.mock import patch
from datetime import datetime, timezone, timedelta

from docksmith.reporter import (
    print_step, print_build_success,
    print_images_table, _format_created, StepTimer
)

def capture(fn, *args, **kwargs):
    with patch("sys.stdout", new_callable=StringIO) as mock_out:
        fn(*args, **kwargs)
        return mock_out.getvalue()

# ── print_step tests ──────────────────────────────────────────────────────────

def test_step_info_no_cache_status():
    out = capture(print_step, 1, 6, "FROM alpine:latest", "INFO")
    assert "Step 1/6 : FROM alpine:latest" in out
    assert "CACHE" not in out

def test_step_cache_hit():
    out = capture(print_step, 3, 6, "COPY . /app", "HIT")
    assert "[CACHE HIT]" in out
    assert "Step 3/6 : COPY . /app" in out

def test_step_cache_miss_shows_time():
    out = capture(print_step, 4, 6, "RUN echo hi", "MISS", elapsed=2.34)
    assert "[CACHE MISS]" in out
    assert "2.34s" in out

def test_step_numbering():
    out = capture(print_step, 2, 5, "WORKDIR /app", "INFO")
    assert "Step 2/5" in out

# ── print_build_success tests ─────────────────────────────────────────────────

def test_build_success_output():
    out = capture(print_build_success, "sha256:abc123def456", "myapp", "latest", 5.23)
    assert "Successfully built" in out
    assert "myapp:latest" in out
    assert "5.23s" in out

def test_build_success_truncates_digest():
    out = capture(print_build_success, "sha256:" + "a" * 64, "app", "v1", 1.0)
    assert "sha256:" in out

# ── print_images_table tests ──────────────────────────────────────────────────

class FakeManifest:
    def __init__(self, name, tag, digest, created):
        self.name    = name
        self.tag     = tag
        self.digest  = digest
        self.created = created

def test_images_table_shows_headers():
    m   = FakeManifest("myapp", "latest", "sha256:abc123", datetime.now(timezone.utc).isoformat())
    out = capture(print_images_table, [m])
    assert "NAME"   in out
    assert "TAG"    in out
    assert "DIGEST" in out

def test_images_table_shows_image():
    m   = FakeManifest("myapp", "latest", "sha256:abc123", datetime.now(timezone.utc).isoformat())
    out = capture(print_images_table, [m])
    assert "myapp"  in out
    assert "latest" in out

def test_empty_images_table():
    out = capture(print_images_table, [])
    assert "No images" in out

# ── _format_created tests ─────────────────────────────────────────────────────

def test_just_now():
    t = datetime.now(timezone.utc).isoformat()
    assert _format_created(t) == "just now"

def test_minutes_ago():
    t = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    assert "minute" in _format_created(t)

def test_hours_ago():
    t = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
    assert "hour" in _format_created(t)

def test_days_ago():
    t = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    assert "day" in _format_created(t)

# ── StepTimer tests ───────────────────────────────────────────────────────────

def test_step_timer():
    with StepTimer() as t:
        time.sleep(0.05)
    assert t.elapsed >= 0.05