# tests/test_builder.py
# Run: python3 -m pytest tests/test_builder.py -v
# NOTE: These are unit tests for builder helpers only.
# Full integration test requires all teammates' code.

import os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from docksmith.builder import _serialize_env, _assemble_rootfs, _execute_copy
from docksmith.layers import store_layer, create_delta_tar, collect_all_paths

def test_serialize_env_sorted():
    result = _serialize_env({"Z": "1", "A": "2", "M": "3"})
    assert result == "A=2&M=3&Z=1"

def test_serialize_env_empty():
    assert _serialize_env({}) == ""

def test_serialize_env_deterministic():
    d1 = {"B": "2", "A": "1"}
    d2 = {"A": "1", "B": "2"}
    assert _serialize_env(d1) == _serialize_env(d2)

def test_assemble_rootfs_extracts_layers():
    # Create a fake layer with one file
    src = tempfile.mkdtemp()
    with open(os.path.join(src, "layer1.txt"), "w") as f:
        f.write("layer1 content")
    tar = create_delta_tar(src, collect_all_paths(src))

    from docksmith.models import LayerEntry
    digest = store_layer(tar)
    layers = [LayerEntry(digest=digest, size=len(tar), createdBy="test")]

    dest = tempfile.mkdtemp()
    _assemble_rootfs(layers, dest)
    assert os.path.exists(os.path.join(dest, "layer1.txt"))

def test_execute_copy_copies_files():
    # Make a context dir with some files
    context = tempfile.mkdtemp()
    with open(os.path.join(context, "app.py"), "w") as f:
        f.write("print('hello')")

    digest = _execute_copy(
        src_pattern    = ".",
        dest           = "/app",
        context_dir    = context,
        current_layers = [],
        workdir        = "",
    )
    assert digest.startswith("sha256:")