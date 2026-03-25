import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from docksmith.cache import CacheManager
from docksmith.layers import collect_all_paths, create_delta_tar, store_layer
from docksmith.models import ImageConfig, ImageManifest, LayerEntry
from docksmith.paths import get_cache_dir
from docksmith.state import load_manifest, save_manifest


def _reset_state_root(tmp_root: str):
    import docksmith.paths as paths

    os.environ["DOCKSMITH_HOME"] = tmp_root
    paths._RESOLVED_STATE_DIR = None


def test_manifest_digest_deterministic_for_same_payload():
    tmp_root = tempfile.mkdtemp()
    _reset_state_root(tmp_root)

    base = ImageManifest(
        name="demo",
        tag="latest",
        digest="",
        created="2026-03-25T00:00:00+00:00",
        config=ImageConfig(Env=["A=1"], Cmd=["/bin/sh"], WorkingDir="/"),
        layers=[LayerEntry(digest="sha256:abc", size=1, createdBy="test")],
    )

    first = save_manifest(base)
    second = save_manifest(base)
    loaded = load_manifest("demo", "latest")

    assert first.digest == second.digest
    assert loaded is not None
    assert loaded.digest == first.digest


def test_cache_lookup_ignores_missing_layer():
    tmp_root = tempfile.mkdtemp()
    _reset_state_root(tmp_root)

    cache = CacheManager(no_cache=False)
    cache.store(
        prev_digest="sha256:base",
        instruction_text="RUN echo hi",
        workdir="/",
        env_serialized="A=1",
        copy_hashes=None,
        result_digest="sha256:thislayerdoesnotexist",
    )

    hit = cache.lookup(
        prev_digest="sha256:base",
        instruction_text="RUN echo hi",
        workdir="/",
        env_serialized="A=1",
        copy_hashes=None,
    )
    assert hit is None


def test_cache_hit_when_layer_exists():
    tmp_root = tempfile.mkdtemp()
    _reset_state_root(tmp_root)

    src = tempfile.mkdtemp()
    with open(os.path.join(src, "x.txt"), "w", encoding="utf-8") as f:
        f.write("x")

    digest = store_layer(create_delta_tar(src, collect_all_paths(src)))
    cache = CacheManager(no_cache=False)
    cache.store(
        prev_digest="sha256:base",
        instruction_text="COPY . /app",
        workdir="/app",
        env_serialized="",
        copy_hashes=["x.txt:abc"],
        result_digest=digest,
    )

    hit = cache.lookup(
        prev_digest="sha256:base",
        instruction_text="COPY . /app",
        workdir="/app",
        env_serialized="",
        copy_hashes=["x.txt:abc"],
    )
    assert hit == digest
    assert os.path.isdir(get_cache_dir())
