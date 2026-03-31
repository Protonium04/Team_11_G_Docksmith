# tests/test_layers.py
# Run: python3 -m pytest tests/test_layers.py -v

import os, sys, io, tarfile, tempfile, pytest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from docksmith.layers import (
    create_delta_tar, collect_all_paths, store_layer,
    layer_exists, get_layer_size, extract_layer,
    hash_copy_sources, snapshot_filesystem,
    compute_delta_paths, sha256_of_bytes,
)

def make_dir_with_files(files: dict) -> str:
    """Creates a temp dir with given {filename: content} dict."""
    d = tempfile.mkdtemp()
    for name, content in files.items():
        with open(os.path.join(d, name), "w") as f:
            f.write(content)
    return d

def test_returns_bytes():
    d = make_dir_with_files({"hello.txt": "hello"})
    tar = create_delta_tar(d, collect_all_paths(d))
    assert isinstance(tar, bytes) and len(tar) > 0

def test_entries_sorted():
    d = make_dir_with_files({"z.txt":"z","a.txt":"a","m.txt":"m"})
    paths = [os.path.join(d,n) for n in ["z.txt","a.txt","m.txt"]]
    tar = create_delta_tar(d, paths)
    with tarfile.open(fileobj=io.BytesIO(tar)) as t:
        names = [m.name for m in t.getmembers()]
    assert names == sorted(names), f"Not sorted: {names}"

def test_timestamps_zeroed():
    d = make_dir_with_files({"test.txt": "content"})
    tar = create_delta_tar(d, collect_all_paths(d))
    with tarfile.open(fileobj=io.BytesIO(tar)) as t:
        for m in t.getmembers():
            assert m.mtime == 0, f"mtime not zero for {m.name}"

def test_identical_content_same_digest():
    """CRITICAL: reproducibility test."""
    def make(content):
        d = make_dir_with_files({"app.py": content})
        return create_delta_tar(d, collect_all_paths(d))
    assert sha256_of_bytes(make("hello")) == sha256_of_bytes(make("hello"))

def test_different_content_different_digest():
    def make(content):
        d = make_dir_with_files({"app.py": content})
        return create_delta_tar(d, collect_all_paths(d))
    assert sha256_of_bytes(make("hello")) != sha256_of_bytes(make("world"))

def test_store_creates_file():
    d = make_dir_with_files({"f.txt": "test"})
    tar = create_delta_tar(d, collect_all_paths(d))
    digest = store_layer(tar)
    assert digest.startswith("sha256:")
    assert layer_exists(digest)

def test_store_idempotent():
    tar = b"idempotent test bytes"
    assert store_layer(tar) == store_layer(tar)

def test_extract_unpacks_files():
    d = make_dir_with_files({"hello.txt": "hello world"})
    tar = create_delta_tar(d, collect_all_paths(d))
    digest = store_layer(tar)
    out = tempfile.mkdtemp()
    extract_layer(digest, out)
    assert open(os.path.join(out, "hello.txt")).read() == "hello world"

def test_snapshot_filesystem():
    d = make_dir_with_files({"a.txt":"aaa","b.txt":"bbb"})
    snap = snapshot_filesystem(d)
    assert "a.txt" in snap and "b.txt" in snap
    assert len(snap["a.txt"]) == 64

def test_compute_delta_detects_changes():
    d = make_dir_with_files({"unchanged.txt":"same","changed.txt":"original"})
    before = snapshot_filesystem(d)
    with open(os.path.join(d,"changed.txt"),"w") as f: f.write("modified")
    with open(os.path.join(d,"new.txt"),"w") as f: f.write("new")
    after = snapshot_filesystem(d)
    delta = [os.path.basename(p) for p in compute_delta_paths(before,after,d)]
    assert "changed.txt" in delta
    assert "new.txt" in delta
    assert "unchanged.txt" not in delta

def test_hash_copy_sources_sorted():
    d = make_dir_with_files({"z.py":"z","a.py":"a","m.py":"m"})
    result = hash_copy_sources(".", d)
    paths = [r.split(":")[0] for r in result]
    assert paths == sorted(paths)