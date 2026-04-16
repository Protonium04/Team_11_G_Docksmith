# tests/test_cache.py
import os, sys, tempfile, pytest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from docksmith.cache import compute_cache_key, CacheManager, lookup, store

def test_cache_key_deterministic():
    k1 = compute_cache_key("sha256:abc", "COPY . /app", "/app", "X=1", ["file.py:deadbeef"])
    k2 = compute_cache_key("sha256:abc", "COPY . /app", "/app", "X=1", ["file.py:deadbeef"])
    assert k1 == k2

def test_different_inputs_different_keys():
    k1 = compute_cache_key("sha256:abc", "COPY . /app", "/app", "X=1")
    k2 = compute_cache_key("sha256:abc", "COPY . /app", "/app", "X=2")
    assert k1 != k2

def test_copy_hashes_order_independent():
    k1 = compute_cache_key("d", "COPY . /app", "/", "", ["b:2", "a:1"])
    k2 = compute_cache_key("d", "COPY . /app", "/", "", ["a:1", "b:2"])
    assert k1 == k2

def test_cache_miss_on_empty_index():
    result = lookup("sha256:x", "RUN echo hi", "/", "", None)
    assert result is None

def test_cache_store_and_lookup(tmp_path, monkeypatch):
    import docksmith.cache as cache_mod
    monkeypatch.setattr(cache_mod, "CACHE_DIR",   str(tmp_path / "cache"))
    monkeypatch.setattr(cache_mod, "CACHE_INDEX", str(tmp_path / "cache" / "index.json"))
    monkeypatch.setattr(cache_mod, "LAYERS_DIR",  str(tmp_path / "layers"))

    os.makedirs(str(tmp_path / "layers"), exist_ok=True)
    fake_layer = str(tmp_path / "layers" / "abc123")
    with open(fake_layer, "wb") as f:
        f.write(b"fake layer")

    store("prev", "RUN echo hi", "/app", "X=1", "sha256:abc123", None)
    result = lookup("prev", "RUN echo hi", "/app", "X=1", None)
    assert result == "sha256:abc123"

def test_cascade_miss():
    cm = CacheManager(no_cache=False)
    cm._force_miss = True
    result = cm.lookup("x", "RUN anything", "/", "", None)
    assert result is None

def test_no_cache_flag():
    cm = CacheManager(no_cache=True)
    result = cm.lookup("x", "RUN echo hi", "/", "", None)
    assert result is None
