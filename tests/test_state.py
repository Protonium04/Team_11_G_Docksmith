# tests/test_state.py
# Run: python3 -m pytest tests/test_state.py -v

import sys, os, tempfile, json, pytest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Patch IMAGES_DIR to use a temp dir so tests don't touch real ~/.docksmith
import docksmith.state as state_module

@pytest.fixture(autouse=True)
def patch_dirs(tmp_path, monkeypatch):
    monkeypatch.setattr(state_module, "IMAGES_DIR", str(tmp_path / "images"))
    monkeypatch.setattr(state_module, "LAYERS_DIR", str(tmp_path / "layers"))
    monkeypatch.setattr(state_module, "CACHE_DIR",  str(tmp_path / "cache"))

from docksmith.state import save_manifest, load_manifest, list_manifests, delete_manifest, image_exists
from docksmith.models import ImageManifest, LayerEntry, ImageConfig

def make_manifest(name="myapp", tag="latest"):
    return ImageManifest(
        name    = name,
        tag     = tag,
        digest  = "",
        created = "2024-01-01T00:00:00+00:00",
        config  = ImageConfig(Env=["X=1"], Cmd=["python","main.py"], WorkingDir="/app"),
        layers  = [LayerEntry(digest="sha256:abc123", size=512, createdBy="COPY . /app")],
    )


def test_save_then_load():
    m = save_manifest(make_manifest())
    loaded = load_manifest("myapp", "latest")
    assert loaded is not None
    assert loaded.name == "myapp"
    assert loaded.tag == "latest"
    assert loaded.config.WorkingDir == "/app"
    assert loaded.layers[0].digest == "sha256:abc123"


def test_save_computes_digest():
    m = save_manifest(make_manifest())
    assert m.digest.startswith("sha256:")
    assert len(m.digest) > 10


def test_digest_is_deterministic():
    m1 = save_manifest(make_manifest())
    m2 = save_manifest(make_manifest())
    assert m1.digest == m2.digest


def test_load_returns_none_if_missing():
    result = load_manifest("nonexistent", "latest")
    assert result is None


def test_image_exists():
    assert not image_exists("myapp", "latest")
    save_manifest(make_manifest())
    assert image_exists("myapp", "latest")


def test_list_manifests_empty():
    assert list_manifests() == []


def test_list_manifests_returns_all():
    save_manifest(make_manifest("app1", "latest"))
    save_manifest(make_manifest("app2", "v1"))
    result = list_manifests()
    names = {m.name for m in result}
    assert names == {"app1", "app2"}


def test_delete_manifest():
    save_manifest(make_manifest())
    digests = delete_manifest("myapp", "latest")
    assert not image_exists("myapp", "latest")
    assert "sha256:abc123" in digests


def test_delete_nonexistent_raises():
    with pytest.raises(FileNotFoundError):
        delete_manifest("ghost", "latest")


def test_env_roundtrip():
    m = make_manifest()
    m.config.Env = ["A=1", "B=hello=world"]
    saved = save_manifest(m)
    loaded = load_manifest("myapp", "latest")
    assert "A=1" in loaded.config.Env
    assert "B=hello=world" in loaded.config.Env