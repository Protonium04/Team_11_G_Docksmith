# tests/test_cache.py
# Run: python3 -m pytest tests/test_cache.py -v

import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from docksmith.cache import compute_cache_key, CacheManager, _load_index, _save_index

# ── compute_cache_key tests ───────────────────────────────────────────────────

def test_same_inputs_same_key():
    k1 = compute_cache_key("d1", "RUN echo hi", "/app", "A=1")
    k2 = compute_cache_key("d1", "RUN echo hi", "/app", "A=1")
    assert k1 == k2

def test_different_instruction_different_key():
    k1 = compute_cache_key("d1", "RUN echo hi",    "/app", "A=1")
    k2 = compute_cache_key("d1", "RUN echo hello", "/app", "A=1")
    assert k1 != k2

def test_different_prev_digest_different_key():
    k1 = compute_cache_key("digest_A", "RUN echo hi", "/app", "")
    k2 = compute_cache_key("digest_B", "RUN echo hi", "/app", "")
    assert k1 != k2

def test_different_workdir_different_key():
    k1 = compute_cache_key("d1", "RUN echo hi", "/app",   "")
    k2 = compute_cache_key("d1", "RUN echo hi", "/other", "")
    assert k1 != k2

def test_different_env_different_key():
    k1 = compute_cache_key("d1", "COPY . /app", "/app", "A=1")
    k2 = compute_cache_key("d1", "COPY . /app", "/app", "A=2")
    assert k1 != k2

def test_copy_hashes_affect_key():
    k1 = compute_cache_key("d1", "COPY . /app", "/app", "", ["file.py:aaa"])
    k2 = compute_cache_key("d1", "COPY . /app", "/app", "", ["file.py:bbb"])
    assert k1 != k2

def test_copy_hashes_order_independent():
    k1 = compute_cache_key("d1", "COPY . /app", "/app", "", ["a.py:111", "b.py:222"])
    k2 = compute_cache_key("d1", "COPY . /app", "/app", "", ["b.py:222", "a.py:111"])
    assert k1 == k2

def test_returns_64_char_hex():
    k = compute_cache_key("d1", "RUN echo hi", "/app", "A=1")
    assert len(k) == 64
    assert all(c in "0123456789abcdef" for c in k)

# ── CacheManager tests ────────────────────────────────────────────────────────

def fresh_cache():
    c = CacheManager(no_cache=False)
    c.clear_index()
    c._force_miss = False
    return c

def test_miss_on_empty_index():
    c = fresh_cache()
    result = c.lookup("d1", "RUN echo hi", "/app", "")
    assert result is None

def test_store_then_lookup_hits(tmp_path, monkeypatch):
    # Write a real dummy layer so the disk-existence check passes
    from docksmith.layers import store_layer
    digest = store_layer(b"dummy-layer-bytes-for-cache-test")
    c = fresh_cache()
    c.store("d1", "RUN echo hi", "/app", "", None, digest)
    c._force_miss = False   # reset cascade so we can test lookup
    result = c.lookup("d1", "RUN echo hi", "/app", "")
    assert result == digest

def test_no_cache_always_misses():
    c = CacheManager(no_cache=True)
    c.store("d1", "RUN echo hi", "/app", "", None, "sha256:abc")
    result = c.lookup("d1", "RUN echo hi", "/app", "")
    assert result is None

def test_cascade_blocks_lookup():
    c = fresh_cache()
    c.store("d1", "RUN echo hi", "/app", "", None, "sha256:abc")
    # force_miss is now True after store — should block lookup
    result = c.lookup("d1", "RUN echo hi", "/app", "")
    assert result is None

def test_clear_index_empties_cache():
    c = fresh_cache()
    c.store("d1", "RUN echo hi", "/app", "", None, "sha256:abc")
    c.clear_index()
    index = _load_index()
    assert index == {}

def test_no_cache_does_not_write_index():
    c = CacheManager(no_cache=True)
    c.clear_index()
    c.store("d1", "RUN echo hi", "/app", "", None, "sha256:abc")
    index = _load_index()
    assert index == {}